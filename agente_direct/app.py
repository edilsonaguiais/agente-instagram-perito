"""Servidor do webhook: recebe o direct do Instagram e responde com o agente.

Rodar:  uvicorn agente_direct.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from .cerebro import Cerebro, links_permitidos, montar_sistema
from .config import Config, contas_da_config
from .instagram import (ClienteInstagram, Comentario, Evento, assinatura_valida, contas_do_aviso,
                        dividir, extrair_comentarios, extrair_eventos)
from .memoria import Memoria
from .paginas import ler_pagina, renderizar

log = logging.getLogger("agente_direct")

# Usada quando a conversa precisa do dono da conta e o modelo não escreveu a mensagem de espera
# (recusa, link bloqueado, teto de mensagens, resposta inválida).
MENSAGEM_ESPERA = "Essa eu quero te responder pessoalmente. Vou ver e te retorno aqui mesmo, pode ser?"


class Orquestrador:
    """Agrupa as mensagens de cada lead, chama o agente e envia a resposta."""

    def __init__(self, cfg: Config, memoria: Memoria, ig: ClienteInstagram, cerebro: Cerebro):
        self.cfg, self.memoria, self.ig, self.cerebro = cfg, memoria, ig, cerebro
        self._timers: dict[str, asyncio.Task] = {}
        self._ocupado: set[str] = set()
        self._pendente: set[str] = set()
        self._ecos_esperados: set[tuple[str, str]] = set()

    # --- entrada ---------------------------------------------------------
    def receber(self, evento: Evento) -> None:
        if evento.eco:
            self._receber_eco(evento)
            return
        if not self.memoria.registrar(evento.conversa, "user", evento.texto, evento.mid or None):
            return  # a Meta reenviou um webhook que já processamos
        if not self.memoria.lead(evento.conversa).get("origem"):
            origem = "story" if evento.story_url else ("facebook" if evento.conversa.startswith("fb:") else "direct")
            self.memoria.atualizar_lead(evento.conversa, origem=origem)
        if evento.story_url and self.cfg.repostar_stories:
            asyncio.create_task(self._repostar_story(evento.conversa, evento.story_url))
        self.agendar(evento.conversa)

    def _receber_eco(self, evento: Evento) -> None:
        chave = (evento.conversa, evento.texto)
        if chave in self._ecos_esperados:
            self._ecos_esperados.discard(chave)
            return
        if not evento.mid or self.memoria.foi_enviado_pelo_agente(evento.mid):
            return
        # Você respondeu pelo app: registra, tira o agente da conversa por um tempo e,
        # se ela estava esperando por você, devolve ao agente depois desse tempo.
        if self.memoria.registrar(evento.conversa, "humano", evento.texto, evento.mid):
            self.memoria.atualizar_lead(evento.conversa, transferido=0)
            self.memoria.pausar(evento.conversa, self.cfg.pausa_humano_horas)
            log.info("Você respondeu %s manualmente; agente pausado por %sh.",
                     evento.conversa, self.cfg.pausa_humano_horas)

    def agendar(self, conversa: str) -> None:
        if conversa in self._ocupado:
            self._pendente.add(conversa)
            return
        anterior = self._timers.get(conversa)
        if anterior and not anterior.done():
            anterior.cancel()
        self._timers[conversa] = asyncio.create_task(self._esperar_e_responder(conversa))

    async def _esperar_e_responder(self, conversa: str) -> None:
        # Espera o lead terminar de digitar: quem manda 3 balões seguidos recebe 1 resposta.
        await asyncio.sleep(self.cfg.espera_agrupar_s)
        self._ocupado.add(conversa)
        try:
            await self.responder(conversa)
        except Exception as erro:
            log.exception("Erro ao responder %s", conversa)
            # Claude fora do ar, chave errada etc.: o lead não fica no vácuo.
            try:
                await self.esperar_dono(conversa, f"erro técnico ao responder ({type(erro).__name__}); veja os logs")
            except Exception:
                log.exception("Também não consegui pedir para %s aguardar", conversa)
        finally:
            self._ocupado.discard(conversa)
            if conversa in self._pendente:
                self._pendente.discard(conversa)
                self.agendar(conversa)

    # --- resposta --------------------------------------------------------
    async def responder(self, conversa: str) -> None:
        if self.memoria.esta_pausado(conversa):
            return
        historico = self.memoria.historico(conversa)
        if not historico or historico[-1]["role"] != "user":
            return

        lead = self.memoria.lead(conversa)
        if not lead["username"]:
            perfil = await self.ig.perfil(conversa)
            if perfil:
                self.memoria.atualizar_lead(conversa, username=perfil.get("username"),
                                            nome=perfil.get("name"))
                lead = self.memoria.lead(conversa)

        if not self.liberado(conversa, lead["username"], lead["nome"]):
            return
        if self.memoria.enviadas_desde(conversa, time.time() - 86400) >= self.cfg.max_msgs_sessao:
            await self.esperar_dono(conversa, f"conversa longa: {self.cfg.max_msgs_sessao} mensagens em 24 h")
            return

        hoje = datetime.now(ZoneInfo(self.cfg.fuso)).strftime("%d/%m/%Y")
        origem = {"story": "marcou você num story" + (
                      " (você já repostou o story dele)" if self.memoria.ajuste(f"story_repostado:{conversa}") else ""),
                  "comentario": "comentou num post seu e você o abordou no direct",
                  "facebook": "Messenger da página do Facebook"}.get(lead.get("origem") or "", "")
        contexto = ", ".join(f"{k}: {v}" for k, v in
                             (("data de hoje", hoje), ("nome", lead["nome"]), ("@", lead["username"]),
                              ("origem do contato", origem)) if v)
        # Memória de longo prazo: a ficha guardada vale além das 60 últimas mensagens do histórico.
        ficha = lead["ficha"] or {}
        if ficha:
            sabido = "; ".join(f"{k}: {ficha[k]}" for k in
                               ("resumo_lead", "perfil", "dor_resumida", "produto_recomendado", "estagio")
                               if ficha.get(k))
            if sabido:
                contexto += f". O que você já sabe desta pessoa, de toda a conversa até aqui: {sabido}"

        await self.ig.digitando(conversa)
        decisao = await self.cerebro.decidir(historico, contexto)

        if decisao.ficha:
            self.memoria.atualizar_lead(conversa, ficha=decisao.ficha)
        for texto in decisao.mensagens:
            if self.memoria.esta_pausado(conversa):
                return  # você assumiu a conversa enquanto o agente pensava
            await self.enviar(conversa, texto)
        if decisao.transferir:
            if decisao.mensagens:  # o agente assume: avisa o perito e a conversa segue com ele
                await self.notificar(conversa, decisao.motivo, esperando=False)
            else:  # falha do modelo ou link bloqueado: aí sim pede para aguardar
                await self.esperar_dono(conversa, decisao.motivo)

    async def enviar(self, conversa: str, texto: str) -> None:
        texto = rastrear_links(texto, conversa)
        for pedaco in dividir(texto):
            self._ecos_esperados.add((conversa, pedaco))
        mids = await self.ig.enviar_texto(conversa, texto)
        for mid in mids:
            self.memoria.marcar_enviado(mid)
        self.memoria.registrar(conversa, "assistant", texto, mids[0] if mids else None)

    async def esperar_dono(self, conversa: str, motivo: str, avisar_lead: bool = True) -> None:
        """O agente pede para o lead aguardar, sai da conversa e avisa o dono da conta."""
        if avisar_lead and not self.memoria.esta_pausado(conversa):
            await self.enviar(conversa, MENSAGEM_ESPERA)
        self.memoria.atualizar_lead(conversa, transferido=1)
        await self.notificar(conversa, motivo)

    def liberado(self, conversa: str, username: str | None, nome: str | None) -> bool:
        """Bloqueados nunca; em SANDBOX, só quem está na lista (@ no Instagram, nome no Facebook)."""
        usuario, nome = (username or "").lower(), (nome or "").lower()
        if usuario in self.cfg.bloqueados or conversa in self.cfg.bloqueados or (nome and nome in self.cfg.bloqueados):
            return False  # sócio, família, equipe: o agente nunca responde
        if self.cfg.sandbox and not ({usuario, nome} - {""}) & self.cfg.sandbox:
            log.info("SANDBOX: ignorando %s (fora da lista de teste).", username or nome or conversa)
            return False
        return True

    # --- comentários --------------------------------------------------------
    def receber_comentario(self, c: Comentario) -> None:
        if not self.cfg.responder_comentarios or c.usuario_id in {self.cfg.ig_user_id, ""}:
            return
        if self.memoria.ajuste(f"comentario:{c.id}"):
            return  # webhook repetido
        self.memoria.gravar_ajuste(f"comentario:{c.id}", "recebido")
        asyncio.create_task(self._tratar_comentario(c))

    async def _tratar_comentario(self, c: Comentario) -> None:
        try:
            if not self.liberado(c.usuario_id, c.username, c.nome):
                return
            lead = self.memoria.lead(c.usuario_id)
            sabido = (lead["ficha"] or {}).get("resumo_lead", "")
            legenda = await self.ig.legenda(c.media_id, c.canal)
            dados = await self.cerebro.decidir_comentario(c.texto, c.username or c.nome, legenda, sabido)
            if not dados:
                return
            log.info("Comentário de %s: e_lead=%s abordar=%s (%s)", c.username or c.nome,
                     dados.get("e_lead"), dados.get("abordar_no_direct"), dados.get("motivo"))
            if dados["resposta_publica"]:
                await self.ig.responder_comentario(c.id, dados["resposta_publica"], c.canal)
            if dados.get("abordar_no_direct") and dados["mensagem_direct"]:
                texto = rastrear_links(dados["mensagem_direct"], c.usuario_id)
                self._ecos_esperados.add((c.usuario_id, texto))
                mid = await self.ig.resposta_privada(c.id, texto)
                if mid:
                    self.memoria.marcar_enviado(mid)
                onde = "num post" if c.canal == "instagram" else "num post da página do Facebook"
                self.memoria.registrar(c.usuario_id, "user", f"[comentou {onde}: {c.texto}]", f"comentario:{c.id}")
                self.memoria.registrar(c.usuario_id, "assistant", texto, mid or None)
                self.memoria.atualizar_lead(c.usuario_id, username=c.username or None, nome=c.nome or None,
                                            origem=lead.get("origem") or "comentario")
        except Exception:
            log.exception("Erro ao tratar o comentário %s", c.id)

    # --- marcação em story ----------------------------------------------------
    async def _repostar_story(self, conversa: str, url: str) -> None:
        """Reposta nos seus stories o story em que a pessoa marcou você (sem o @ clicável:
        a API da Meta não cria o adesivo de menção)."""
        try:
            if self.memoria.ajuste(f"story_repostado:{conversa}") or not self.cfg.dominio:
                return
            perfil = await self.ig.perfil(conversa)
            if not self.liberado(conversa, perfil.get("username"), perfil.get("name")):
                return
            agora = time.time()
            recentes = [float(x) for x in self.memoria.ajuste("reposts_recentes", "").split(",") if x]
            recentes = [x for x in recentes if agora - x < 3600]
            if len(recentes) >= self.cfg.max_reposts_hora:
                log.warning("Repost de story adiado: teto de %s por hora.", self.cfg.max_reposts_hora)
                return
            conteudo, tipo = await self.ig.baixar(url)
            video = tipo.startswith("video")
            nome = hashlib.sha256(conteudo).hexdigest()[:24] + (".mp4" if video else ".jpg")
            pasta = self.cfg.banco.parent / "midia"
            pasta.mkdir(parents=True, exist_ok=True)
            (pasta / nome).write_bytes(conteudo)
            await self.ig.publicar_story(self.cfg.ig_user_id, f"https://{self.cfg.dominio}/midia/{nome}", video)
            self.memoria.gravar_ajuste(f"story_repostado:{conversa}", str(agora))
            self.memoria.gravar_ajuste("reposts_recentes", ",".join(map(str, recentes + [agora])))
            log.info("Story de %s repostado.", perfil.get("username") or conversa)
        except Exception:
            log.exception("Não consegui repostar o story de %s", conversa)

    # --- follow-up ---------------------------------------------------------
    async def verificar_followups(self, agora: float | None = None) -> int:
        """Até 2 retomadas quando o lead some, sempre dentro da janela de 24 h da Meta:
        a 1ª ~30 min depois da mensagem do agente que ficou sem resposta, a 2ª ~2 h depois
        dela ("ficou alguma dúvida?"). Se o lead responde, a contagem zera.
        """
        agora = agora or time.time()
        hora = datetime.fromtimestamp(agora, ZoneInfo(self.cfg.fuso)).hour
        if not (self.cfg.followup_hora_inicio <= hora < self.cfg.followup_hora_fim):
            return 0
        enviados = 0
        for lead in self.memoria.listar_leads():
            conversa = lead["conversa"]
            if self.memoria.esta_pausado(conversa) or conversa in self._ocupado:
                continue
            if not self.liberado(conversa, lead["username"], lead["nome"]):
                continue
            ultima, ultima_do_lead = self.memoria.ultimas(conversa)
            ficha = lead["ficha"] or {}
            if (not ultima or ultima["papel"] != "assistant" or not ultima_do_lead
                    or ficha.get("estagio") in ("desqualificado", "suporte", "relacionamento")
                    or ficha.get("produto_recomendado") == "nenhum"
                    or agora - ultima_do_lead >= 23.5 * 3600):
                continue
            feitas = (lead.get("retomadas") or 0) if lead.get("retomadas_ref") == ultima_do_lead else 0
            if feitas >= 2:
                continue
            sem_resposta = self.memoria.primeira_sem_resposta(conversa, ultima_do_lead)
            espera = self.cfg.retomada_1_min if feitas == 0 else self.cfg.retomada_2_min
            if not sem_resposta or agora < sem_resposta + espera * 60:
                continue
            if feitas and agora - (lead["followup_em"] or 0) < 30 * 60:
                continue  # depois do silêncio noturno, não manda as duas de uma vez
            texto = await self.texto_retomada(conversa, feitas + 1, lead, ficha)
            if not texto:
                continue
            await self.enviar(conversa, texto)
            self.memoria.atualizar_lead(conversa, followup_em=agora, retomadas=feitas + 1,
                                        retomadas_ref=ultima_do_lead)
            enviados += 1
        return enviados

    async def texto_retomada(self, conversa: str, numero: int, lead: dict, ficha: dict) -> str:
        """O Claude escreve a retomada a partir da conversa; se falhar, usa o texto padrão."""
        pedido = ("[instrução interna, não é fala do lead] O lead não respondeu sua última mensagem. "
                  + ("Escreva UMA retomada curta e natural, que continue de onde a conversa parou "
                     "e termine em uma pergunta simples." if numero == 1 else
                     "Escreva UMA última mensagem curta para conferir se ficou tudo certo ou se ficou "
                     "alguma dúvida. Sem pressão e sem repetir preço ou link.")
                  + " Não diga que é uma retomada automática. Uma mensagem só.")
        try:
            historico = self.memoria.historico(conversa) + [{"role": "user", "content": pedido}]
            decisao = await self.cerebro.decidir(historico, f"nome: {lead['nome'] or ''}")
            if decisao.mensagens and not decisao.transferir:
                return decisao.mensagens[0]
        except Exception:
            log.exception("Falha ao escrever a retomada de %s; usando o texto padrão", conversa)
        return texto_followup(lead["nome"], ficha.get("dor_resumida", ""))

    async def renovar_token_se_preciso(self, agora: float | None = None) -> bool:
        """Renova o token a cada 7 dias e guarda no banco: ninguém precisa lembrar."""
        agora = agora or time.time()
        if self.ig.api == "facebook":
            return False  # token de página não expira e não tem renovação
        if agora - float(self.memoria.ajuste("ig_token_renovado_em", "0")) < 7 * 86400:
            return False
        dados = await self.ig.renovar_token()
        self.ig.token = dados["access_token"]
        self.memoria.gravar_ajuste("ig_token", self.ig.token)
        self.memoria.gravar_ajuste("ig_token_renovado_em", str(agora))
        log.info("Token do Instagram renovado (vale mais %s dias).", int(dados.get("expires_in", 0)) // 86400)
        return True

    async def laco_token(self, intervalo_s: float = 6 * 3600) -> None:
        while True:
            try:
                await self.renovar_token_se_preciso()
            except Exception:
                log.exception("Não consegui renovar o token do Instagram; rode `agente-perito verificar`.")
            await asyncio.sleep(intervalo_s)

    async def laco_followup(self, intervalo_s: float = 120) -> None:
        while True:
            try:
                await self.verificar_followups()
            except Exception:
                log.exception("Erro no follow-up")
            await asyncio.sleep(intervalo_s)

    async def notificar(self, conversa: str, motivo: str, esperando: bool = True) -> None:
        """Avisa o dono da conta: alguém esperando resposta, ou só algo que ele precisa saber."""
        lead = self.memoria.lead(conversa)
        quem = f"@{lead['username']}" if lead["username"] else conversa
        log.warning("%s %s: %s", "ESPERANDO RESPOSTA MANUAL" if esperando else "AVISO AO PERITO", quem, motivo)
        ficha = lead["ficha"] or {}
        cabeca = (f"📩 {quem} ({lead['nome'] or 'sem nome'}) está esperando sua resposta no direct.\n"
                  f"O que responder: {motivo or 'ver conversa'}\n") if esperando else (
                  f"🔔 {quem} ({lead['nome'] or 'sem nome'}): o agente segue atendendo; você precisa saber.\n"
                  f"O quê: {motivo or 'ver conversa'}\n")
        texto = (cabeca + f"Resumo: {ficha.get('resumo_lead', '')}\n"
                 f"Serviço: {ficha.get('produto_recomendado', '')}")
        async with httpx.AsyncClient(timeout=10) as http:
            if self.cfg.telegram_token and self.cfg.telegram_chat_id:
                try:
                    await http.post(f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage",
                                    json={"chat_id": self.cfg.telegram_chat_id, "text": texto})
                except httpx.HTTPError:
                    log.exception("Falha ao avisar no Telegram")
            if self.cfg.notificar_url:
                try:
                    await http.post(self.cfg.notificar_url, json={
                        "evento": "lead_esperando_resposta", "conversa": conversa,
                        "username": lead["username"], "nome": lead["nome"],
                        "motivo": motivo, "ficha": lead["ficha"], "texto": texto, "em": time.time(),
                    })
                except httpx.HTTPError:
                    log.exception("Falha ao notificar %s", self.cfg.notificar_url)


async def encaminhar(urls: tuple, corpo: bytes, assinatura: str | None) -> None:
    """Repassa o aviso da Meta, byte a byte, para o agente de outra conta do mesmo app."""
    async with httpx.AsyncClient(timeout=10) as http:
        for url in urls:
            try:
                resp = await http.post(url, content=corpo, headers={
                    "Content-Type": "application/json", "X-Hub-Signature-256": assinatura or "",
                    "X-Encaminhado": "1"})
                if resp.status_code >= 400:
                    log.error("Encaminhar aviso para %s falhou: %s", url, resp.status_code)
            except httpx.HTTPError:
                log.exception("Não consegui encaminhar o aviso para %s", url)


def rastrear_links(texto: str, conversa: str) -> str:
    """Troca o campo "lead" do src/sck dos links do catálogo pelo ID da conversa,
    para a venda na Hotmart mostrar de qual conversa do direct ela veio."""
    return texto.replace("%7Clead%7C", f"%7C{conversa}%7C")


def texto_followup(nome: str | None, dor: str) -> str:
    """Copy do atalho /sumiu1 da casa."""
    primeiro = (nome or "").split(" ")[0]
    sobre = f" sobre {dor.strip().rstrip('.')}" if dor and dor.strip() else ""
    frase = f"retomo nossa conversa{sobre}. Ficou algum ponto sem resposta para você decidir?"
    return f"{primeiro}, {frase}" if primeiro else frase[0].upper() + frase[1:]


def criar_app(cfg: Config | None = None, orquestrador: Orquestrador | None = None,
              followup: bool = True) -> FastAPI:
    cfg = cfg or Config.do_ambiente()
    if orquestrador is None:
        memoria = Memoria(cfg.banco)
        # o token renovado pelo próprio servidor (no banco) vale mais que o do .env,
        # a não ser que o .env tenha sido trocado depois (agente-perito configurar)
        token = cfg.ig_access_token
        if memoria.ajuste("ig_token_origem") == cfg.ig_access_token and memoria.ajuste("ig_token"):
            token = memoria.ajuste("ig_token")
        else:
            memoria.gravar_ajuste("ig_token_origem", cfg.ig_access_token)
            memoria.gravar_ajuste("ig_token", cfg.ig_access_token)
            memoria.gravar_ajuste("ig_token_renovado_em", str(time.time()))
        ig = ClienteInstagram(token, cfg.graph_versao, cfg.modo_teste, api=cfg.ig_api)
        cerebro = Cerebro(montar_sistema(cfg.pasta_conhecimento, cfg.dono, cfg.dominio), cfg.modelo, cfg.esforco,
                          links=links_permitidos(cfg.pasta_conhecimento, cfg.dominio), motor=cfg.motor_claude,
                          dono=cfg.dono)
        orquestrador = Orquestrador(cfg, memoria, ig, cerebro)
    orq = orquestrador

    @contextlib.asynccontextmanager
    async def ciclo(_app):
        tarefas = [asyncio.create_task(orq.laco_followup()),
                   asyncio.create_task(orq.laco_token())] if followup else []
        yield
        for tarefa in tarefas:
            tarefa.cancel()

    app = FastAPI(title=f"Agente Direct — {cfg.dono}", lifespan=ciclo)
    app.state.orquestrador = orq
    contas = contas_da_config(cfg)

    def _admin(autorizacao: str | None) -> None:
        if not cfg.admin_token or autorizacao != f"Bearer {cfg.admin_token}":
            raise HTTPException(401, "não autorizado")

    @app.get("/saude")
    async def saude():
        return {"ok": True, "modelo": cfg.modelo, "modo_teste": cfg.modo_teste}

    @app.get("/privacidade")
    async def privacidade():
        """Política de privacidade mínima: a Meta exige uma URL dessas para publicar o app."""
        return Response(media_type="text/html; charset=utf-8", content=f"""<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Privacidade — {cfg.dono}</title>
<body style="font-family:sans-serif;max-width:680px;margin:40px auto;padding:0 16px;line-height:1.5">
<h1>Política de privacidade</h1>
<p>Este serviço responde mensagens enviadas ao Instagram de {cfg.dono}, com ajuda de
inteligência artificial. Guardamos o texto das conversas, o nome e o @ do Instagram
de quem escreve, apenas para continuar o atendimento e oferecer os serviços de {cfg.dono}.</p>
<p>Os dados não são vendidos nem compartilhados, exceto com os provedores técnicos
necessários para o funcionamento: Meta (Instagram) e Anthropic (Claude).</p>
<h2>Exclusão de dados</h2>
<p>Para apagar seus dados, envie no direct a mensagem "apagar meus dados". O pedido é
atendido manualmente por {cfg.dono} em até 15 dias.</p>
</body></html>""")

    @app.get("/webhook")
    async def verificar(modo: str = Query("", alias="hub.mode"),
                        token: str = Query("", alias="hub.verify_token"),
                        desafio: str = Query("", alias="hub.challenge")):
        # A Meta chama isto uma vez, quando você cadastra a URL do webhook no painel.
        if modo == "subscribe" and cfg.ig_verify_token and token == cfg.ig_verify_token:
            return Response(content=desafio, media_type="text/plain")
        raise HTTPException(403, "token de verificação inválido")

    @app.post("/webhook")
    async def webhook(request: Request, x_hub_signature_256: str | None = Header(None),
                      x_encaminhado: str | None = Header(None)):
        corpo = await request.body()
        if not assinatura_valida(corpo, x_hub_signature_256, cfg.ig_app_secret):
            raise HTTPException(401, "assinatura inválida")
        dados = await request.json()
        # Aviso de outra conta do mesmo app: repassa intacto (uma vez só, sem eco entre agentes).
        if contas and cfg.encaminhar_webhook and not x_encaminhado and contas_do_aviso(dados) - contas:
            asyncio.create_task(encaminhar(cfg.encaminhar_webhook, corpo, x_hub_signature_256))
        for evento in extrair_eventos(dados, cfg.ig_user_id, contas):
            orq.receber(evento)
        for comentario in extrair_comentarios(dados, contas):
            orq.receber_comentario(comentario)
        return {"ok": True}  # responder rápido: a Meta reenvia se demorar

    @app.get("/p/{endereco}")
    async def pagina_de_venda(endereco: str):
        """Página do serviço com preço e QR Code do Pix (servicos.md com "Pix:" ou conhecimento/paginas/)."""
        p = ler_pagina(cfg.pasta_conhecimento, endereco)
        if not p or not cfg.pix_chave:
            raise HTTPException(404)
        return Response(media_type="text/html; charset=utf-8",
                        content=renderizar(p, cfg.dono, cfg.pix_chave, cfg.pix_nome, cfg.pix_cidade))

    @app.get("/midia/{nome}")
    async def midia(nome: str):
        """Serve a mídia baixada para a Meta buscar na hora de publicar o story repostado."""
        if not re.fullmatch(r"[0-9a-f]{24}\.(jpg|mp4)", nome):
            raise HTTPException(404)
        arquivo = cfg.banco.parent / "midia" / nome
        if not arquivo.exists():
            raise HTTPException(404)
        return FileResponse(arquivo)

    @app.get("/leads")
    async def leads(authorization: str | None = Header(None)):
        _admin(authorization)
        return orq.memoria.listar_leads()

    @app.get("/leads/{conversa}")
    async def lead(conversa: str, authorization: str | None = Header(None)):
        _admin(authorization)
        return {**orq.memoria.lead(conversa), "historico": orq.memoria.historico(conversa, 200)}

    @app.post("/leads/{conversa}/retomar")
    async def retomar(conversa: str, authorization: str | None = Header(None)):
        """Devolve a conversa para o agente (depois de uma transferência ou pausa)."""
        _admin(authorization)
        orq.memoria.atualizar_lead(conversa, pausado_ate=0, transferido=0)
        return {"ok": True}

    @app.post("/leads/{conversa}/pausar")
    async def pausar(conversa: str, horas: float = 24 * 365, authorization: str | None = Header(None)):
        _admin(authorization)
        orq.memoria.pausar(conversa, horas)
        return {"ok": True}

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def __getattr__(nome: str):
    # `uvicorn agente_direct.app:app` cria o app só quando é pedido (os testes não precisam de .env).
    if nome == "app":
        return criar_app()
    raise AttributeError(nome)
