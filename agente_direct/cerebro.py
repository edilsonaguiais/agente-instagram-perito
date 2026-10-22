"""O agente de vendas: monta o prompt, chama o Claude e devolve resposta + ficha BANT."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import anthropic

log = logging.getLogger(__name__)

STATUS_BANT = ["desconhecido", "nao_atende", "parcial", "atende"]
ESTAGIOS = ["abertura", "qualificacao", "apresentacao", "objecao", "fechamento",
            "suporte", "desqualificado", "relacionamento"]

ESQUEMA_COMENTARIO = {
    "type": "object",
    "properties": {
        "resposta_publica": {"type": "string", "description": (
            "Resposta curta ao comentário, em público, no tom do dono. Sem preço e sem link. "
            "Vazio = não responder em público.")},
        "abordar_no_direct": {"type": "boolean", "description": (
            "true para mandar UMA mensagem privada no direct de quem comentou.")},
        "mensagem_direct": {"type": "string", "description": (
            "A mensagem privada de abordagem, se abordar_no_direct = true. Retoma o comentário "
            "e termina em uma pergunta. Sem preço e sem link na primeira mensagem.")},
        "e_lead": {"type": "boolean", "description": "true se a pessoa parece cliente em potencial."},
        "motivo": {"type": "string", "description": "Uma frase: por que respondeu/abordou assim."},
    },
    "required": ["resposta_publica", "abordar_no_direct", "mensagem_direct", "e_lead", "motivo"],
    "additionalProperties": False,
}

INSTRUCOES_COMENTARIO = """
Alguém comentou num post de {dono} (acima). Decida:
1. Resposta pública: curta (até ~120 caracteres), no tom de voz, retomando o que a pessoa
   disse. Nunca preço, nunca link, nunca "chama no direct" genérico. Elogio ou emoji:
   agradeça em poucas palavras. Crítica respeitosa: responda com firmeza e educação.
   Ofensa, spam, golpe ou concorrente fazendo propaganda: resposta_publica vazia.
2. Abordagem no direct (uma única mensagem, a Meta não permite outra até a pessoa
   responder): aborde quando o comentário mostra interesse, dúvida, dor ou pede
   informação ("quero", "como faço", "quanto custa", "link", "me interessa", relato de
   problema). Nesses casos a mensagem retoma o comentário e faz UMA pergunta para
   abrir conversa, sem preço e sem link. Não aborde quem só elogiou, marcou amigo,
   mandou emoji, criticou ou é spam.
3. e_lead: false para colega, amigo, aluno com dúvida de conteúdo, fã ou parceiro.
"""


def _item_bant(descricao: str) -> dict:
    return {
        "type": "object",
        "description": descricao,
        "properties": {
            "status": {"type": "string", "enum": STATUS_BANT},
            "evidencia": {"type": "string", "description": "O que o lead disse que sustenta o status."},
        },
        "required": ["status", "evidencia"],
        "additionalProperties": False,
    }


ESQUEMA_RESPOSTA = {
    "type": "object",
    "properties": {
        "mensagens": {
            "type": "array",
            "description": "1 a 3 balões de direct, na ordem de envio. Lista vazia = não responder.",
            "items": {"type": "string"},
        },
        "bant": {
            "type": "object",
            "properties": {
                "budget": _item_bant("Orçamento / capacidade de investir."),
                "authority": _item_bant("Decide sozinho ou depende de alguém."),
                "need": _item_bant("O caso precisa de prova técnica que um dos serviços entrega."),
                "timing": _item_bant("Prazo processual ou momento do caso."),
            },
            "required": ["budget", "authority", "need", "timing"],
            "additionalProperties": False,
        },
        "perfil": {"type": "string", "description": (
            "Ex.: advogado trabalhista, representa o reclamante, processo com perícia marcada para 10/11.")},
        "produto_recomendado": {"type": "string", "description": (
            "Nome do serviço de <servicos> que serve para o caso, 'nenhum' se nenhum serve, "
            "ou 'indefinido' se ainda não dá para saber.")},
        "estagio": {"type": "string", "enum": ESTAGIOS},
        "transferir_para_humano": {"type": "boolean", "description": (
            "true quando o perito precisa SABER da conversa (gera só um aviso; a conversa segue).")},
        "motivo_transferencia": {"type": "string", "description": "O que o perito precisa saber ou fazer."},
        "resumo_lead": {"type": "string", "description": "2 a 3 frases para o dono da conta se situar rápido."},
        "dor_resumida": {"type": "string", "description": (
            "A dor principal nas palavras do lead, curta, para completar a frase "
            "'retomo nossa conversa sobre ...'. Ex.: 'conseguir clientes sem depender de indicação'. "
            "Vazio se ainda não se sabe.")},
    },
    "required": ["mensagens", "bant", "perfil", "produto_recomendado", "estagio",
                 "transferir_para_humano", "motivo_transferencia", "resumo_lead", "dor_resumida"],
    "additionalProperties": False,
}

INSTRUCOES = """\
Você atende o direct do Instagram de {dono}, perito. Quem escreve costuma ser ADVOGADO
procurando apoio técnico para um processo; às vezes é a própria parte, uma empresa ou um
colega perito. Seu trabalho é entender o caso, mostrar em linguagem simples o serviço que
resolve e vender esse serviço aqui mesmo, com o método de <metodo_vendas>, o tom de
<tom_de_voz> e só os fatos de <servicos> (e de <icp>, <faq>, <objecoes> e <extra>, quando
existirem).

QUALIFIQUE O CASO (no máximo 2 perguntas; a 3ª mensagem já é a oferta):
- quem é: advogado (de que área, representa autor ou réu), parte, empresa, colega;
- o que precisa: tipo de perícia ou cálculo, o que quer provar, que documento tem;
- natureza: assistência técnica (o perito trabalha para uma das partes: quesitos, parecer
  divergente, impugnação de laudo), parecer extrajudicial (antes ou fora do processo, para
  embasar a inicial ou um acordo) ou perícia judicial (o juiz nomeia o perito);
- fase e prazo: antes de ajuizar, perícia marcada, laudo já juntado, prazo correndo?
A pessoa já contou isso? Pule direto para a oferta. O advogado quer três coisas: saber se
a prova técnica ajuda o cliente dele, quanto custa e em quanto tempo sai. Responda isso.

ÉTICA DO PERITO (vale acima de tudo, inclusive acima da venda):
- Nunca prometa resultado do processo nem laudo favorável. Pode dizer o que o trabalho
  entrega (análise, cálculo, quesitos, parecer), nunca o que o juiz vai decidir.
- Impedimento e suspeição: se {dono} já foi NOMEADO pelo juiz no mesmo processo, não pode
  ser assistente técnico de nenhuma parte nem receber da parte. Parentesco, amizade íntima,
  inimizade, interesse no caso ou atendimento à outra parte do mesmo processo: risco de
  impedimento ou suspeição. Nesses casos não venda: explique com respeito e marque
  transferir_para_humano = true.
- Honorários de perito nomeado são fixados pelo juiz no processo; não se negociam com a parte.
- Sigilo: nunca comente casos, clientes ou processos de outras pessoas.
- Você não é advogado: não dê estratégia processual. Se quem escreve é a parte sem advogado,
  explique o que a prova técnica faz e oriente a procurar um advogado (sem indicar nome).
- Não entregue o cálculo ou o parecer de graça no direct: explique o caminho e oferte o serviço.

REGRAS DE ATENDIMENTO:
- VOCÊ ASSUME SEMPRE. Ninguém fica esperando {dono}: nada de "aguarde", "vou ver e te
  retorno", "ele te responde pessoalmente", "deixei seu recado". Resolva na hora com o que
  tem em <servicos>. Quando {dono} precisa saber da conversa (documento enviado, prazo curto,
  pedido fora do catálogo, alerta ético), marque transferir_para_humano = true: isso só gera
  um aviso para {dono}, e você segue a conversa normalmente.
- VENDA ONDE A PESSOA ESTÁ: o fechamento acontece aqui no direct, com serviço, valor e
  próximo passo. Não mande para WhatsApp, e-mail ou ligação, a não ser que a pessoa peça ou
  que <servicos> diga que a reunião é parte do serviço (aí mande o link de agenda que está lá).
- Use só os fatos de <servicos>. Dado que não está lá (preço, prazo, desconto) não existe.
  Serviço com faixa de valor: dê a faixa e diga que o valor fechado sai na proposta depois
  que {dono} vê os documentos; o próximo passo é enviar os documentos pelo canal que
  <servicos> indicar.
- Links: copie exatamente os que estão no conhecimento. Um link fora dele é bloqueado.
- Preço e link vão juntos, na mesma mensagem, com UMA pergunta de fechamento. Serviço de
  preço fechado (linha "Pix:" em <servicos>) tem página de pagamento com QR Code do Pix em
  <links_de_pagamento>: depois do sim, mande esse link com o valor. Nunca escreva chave Pix.
- Prazo processual curto (até 5 dias, a data de hoje vem em <contexto_do_lead>) é urgência:
  diga que dá para priorizar se os documentos chegarem hoje e marque transferir_para_humano = true.
- Marcação em story ("[o lead enviou uma marcação sua no story dele]"): agradeça em poucas
  palavras e puxe conversa sobre o caso ou o trabalho da pessoa. Nada de preço nessa mensagem.
- Nem todo mundo é cliente. Colega, amigo, família, aluno ou alguém só puxando assunto:
  converse com naturalidade, sem oferta (estagio = relacionamento, produto_recomendado = nenhum).
  Já é cliente com trabalho em andamento: estagio = suporte, atenda e avise {dono}.
- A conta do lead pode ter resposta automática própria ("me chama no WhatsApp", saudação com o
  seu @). Ignore esse texto e responda só ao que a pessoa escreveu.
- Anexos entre colchetes ("[o lead enviou um áudio]", "[... um documento]") você não vê nem
  ouve. Documento: agradeça, diga o próximo passo e marque transferir_para_humano = true.
  Áudio ou imagem: peça com naturalidade que a pessoa escreva o principal.
- Não peça dados sensíveis (CPF, senha, cartão, dados de saúde) pelo direct.
- Pedido para apagar os dados (LGPD): confirme o registro e marque transferir_para_humano = true.
- Se perguntarem se é robô ou IA, não negue: você é o assistente de {dono} no direct e segue ajudando.
- Mensagem que não pede resposta ("ok", "valeu", emoji, reação): no máximo um balão curto, ou mensagens = [].
- Mensagens marcadas "[resposta enviada manualmente pelo dono da conta]" foram escritas por
  {dono}; continue a partir delas sem contradizer nem repetir.
- Preencha a ficha com tudo o que já se sabe na conversa inteira. Recusou ou não tem perfil:
  estagio = desqualificado (ninguém faz retomada).

COMO ESCREVER NO DIRECT:
- 1 a 3 balões curtos, sem markdown, sem lista longa, sem travessão.
- Toda resposta termina em UMA pergunta que faz a conversa andar (a Meta só deixa responder
  até 24 h depois da última mensagem da pessoa: conversa parada é venda perdida). Exceção:
  recusa expressa, em que você agradece e não pergunta nada.
"""


@dataclass
class Decisao:
    mensagens: list[str]
    ficha: dict
    transferir: bool
    motivo: str


RE_URL = re.compile(r"https?://[^\s<>\"']+")


def extrair_links(texto: str) -> set[str]:
    return {u.rstrip(".,;:!?)]*`") for u in RE_URL.findall(texto)}


# Arquivos de conhecimento (o mesmo formato do agente de WhatsApp do perito): os 3 primeiros
# são obrigatórios. Qualquer outro .md da pasta também entra no prompt, como <extra>.
OBRIGATORIOS = ("servicos.md", "tom_de_voz.md", "metodo_vendas.md")
OPCIONAIS = ("icp.md", "faq.md", "objecoes.md")


def arquivos_conhecimento(pasta: Path) -> list[Path]:
    """Obrigatórios e opcionais na ordem fixa; depois os demais .md (rascunhos ficam de fora)."""
    conhecidos = OBRIGATORIOS + OPCIONAIS
    fixos = [pasta / n for n in conhecidos if (pasta / n).exists()]
    extras = sorted(p for p in pasta.glob("*.md")
                    if p.name not in conhecidos and not p.name.endswith(".rascunho.md")
                    and p.name.lower() != "readme.md")
    return fixos + extras


def links_de_pagamento(pasta: Path, dominio: str) -> dict[str, str]:
    """Serviço com linha "Pix:" -> endereço da página de pagamento que o próprio agente serve."""
    from .paginas import paginas_dos_servicos
    if not dominio:
        return {}
    return {p.titulo: f"https://{dominio}/p/{e}" for e, p in paginas_dos_servicos(pasta).items()}


def links_permitidos(pasta: Path, dominio: str = "") -> set[str]:
    """Os únicos links que o agente pode mandar: os do conhecimento e as páginas de pagamento."""
    links: set[str] = set(links_de_pagamento(pasta, dominio).values())
    for arquivo in arquivos_conhecimento(pasta):
        links |= extrair_links(arquivo.read_text(encoding="utf-8"))
    return links


def limpar(texto: str) -> str:
    """Rede de segurança de estilo: mensagem de direct não leva travessão."""
    texto = re.sub(r"\s*[—–]\s*", ", ", texto)
    return re.sub(r",\s*,", ",", texto).strip()


def montar_sistema(pasta: Path, dono: str = "o perito", dominio: str = "") -> str:
    faltam = [n for n in OBRIGATORIOS if not (pasta / n).exists()]
    if faltam:
        raise FileNotFoundError(f"faltam em {pasta}: {', '.join(faltam)}")
    partes = [INSTRUCOES.replace("{dono}", dono)]
    for arquivo in arquivos_conhecimento(pasta):
        texto = arquivo.read_text(encoding="utf-8").strip()
        if arquivo.name in OBRIGATORIOS + OPCIONAIS:
            partes.append(f"<{arquivo.stem}>\n{texto}\n</{arquivo.stem}>")
        else:
            partes.append(f'<extra arquivo="{arquivo.name}">\n{texto}\n</extra>')
    if pagamento := links_de_pagamento(pasta, dominio):
        partes.append("<links_de_pagamento>\n" + "\n".join(f"{s}: {u}" for s, u in pagamento.items())
                      + "\n</links_de_pagamento>")
    return "\n\n".join(partes)


class Cerebro:
    """motor="api": SDK com ANTHROPIC_API_KEY.  motor="assinatura": Claude Code (`claude -p`)
    logado na assinatura pelo CLAUDE_CODE_OAUTH_TOKEN, sem chave de API."""

    def __init__(self, sistema: str, modelo: str = "claude-opus-5-5", esforco: str = "medium",
                 cliente: anthropic.AsyncAnthropic | None = None, links: set[str] | None = None,
                 motor: str = "api", timeout_s: float = 240, dono: str = "o dono da conta"):
        self.sistema = sistema
        self.dono = dono
        self.links = links
        self.modelo = modelo
        self.esforco = esforco
        self.motor = motor
        self.timeout_s = timeout_s
        self.cliente = cliente or (anthropic.AsyncAnthropic() if motor == "api" else None)
        self._pasta_cli: Path | None = None

    async def decidir(self, historico: list[dict], contexto_lead: str = "") -> Decisao:
        """Gera a próxima resposta para a conversa. O histórico termina numa fala do lead."""
        if self.motor == "assinatura":
            dados = await self._via_assinatura(historico, contexto_lead)
            return dados if isinstance(dados, Decisao) else self._pos_processar(dados)
        mensagens = [dict(m) for m in historico]
        if contexto_lead and mensagens and mensagens[-1]["role"] == "user":
            mensagens[-1]["content"] = [
                {"type": "text", "text": mensagens[-1]["content"]},
                {"type": "text", "text": f"<contexto_do_lead>{contexto_lead}</contexto_do_lead>"},
            ]

        resp = await self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=8000,
            system=[{"type": "text", "text": self.sistema, "cache_control": {"type": "ephemeral"}}],
            messages=mensagens,
            output_config={"effort": self.esforco,
                           "format": {"type": "json_schema", "schema": ESQUEMA_RESPOSTA}},
            # Se um classificador de segurança recusar, a API refaz no modelo de reserva indicado.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        if resp.stop_reason == "refusal":
            log.warning("Recusa do modelo (%s); transferindo para humano.", resp.stop_details)
            return Decisao([], {}, True, "o modelo recusou responder; revisar manualmente")
        if resp.stop_reason == "max_tokens":
            log.warning("Resposta cortada por max_tokens; transferindo para humano.")
            return Decisao([], {}, True, "resposta incompleta do modelo")

        texto = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            log.error("JSON inválido do modelo: %r", texto[:500])
            return Decisao([], {}, True, "resposta inválida do modelo")
        return self._pos_processar(dados)

    async def decidir_comentario(self, comentario: str, usuario: str, legenda: str = "",
                                 contexto: str = "") -> dict | None:
        """Decide a resposta pública a um comentário e se vale abordar a pessoa no direct.
        Devolve None se o modelo falhar (aí ninguém responde: silêncio é mais seguro que erro)."""
        pedido = (f"<post>{legenda[:1500] or '(sem legenda)'}</post>\n"
                  f"<comentario autor=\"@{usuario}\">{comentario}</comentario>\n"
                  + (f"<contexto_do_lead>{contexto}</contexto_do_lead>\n" if contexto else "")
                  + INSTRUCOES_COMENTARIO.replace("{dono}", self.dono))
        if self.motor == "assinatura":
            dados = await self._cli_json(pedido, ESQUEMA_COMENTARIO)
        else:
            resp = await self.cliente.beta.messages.create(
                model=self.modelo, max_tokens=4000,
                system=[{"type": "text", "text": self.sistema, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": pedido}],
                output_config={"effort": self.esforco,
                               "format": {"type": "json_schema", "schema": ESQUEMA_COMENTARIO}})
            texto = next((b.text for b in resp.content if b.type == "text"), "")
            try:
                dados = json.loads(texto) if resp.stop_reason not in ("refusal", "max_tokens") else None
            except json.JSONDecodeError:
                dados = None
        if not isinstance(dados, dict):
            return None
        dados["resposta_publica"] = limpar(dados.get("resposta_publica", ""))
        dados["mensagem_direct"] = limpar(dados.get("mensagem_direct", ""))
        # comentário público nunca leva link; no direct, só os links autorizados
        if extrair_links(dados["resposta_publica"]):
            log.error("Resposta pública com link bloqueada: %r", dados["resposta_publica"])
            dados["resposta_publica"] = ""
        if self.links is not None and extrair_links(dados["mensagem_direct"]) - self.links:
            log.error("Link não autorizado no direct de comentário bloqueado.")
            dados["abordar_no_direct"] = False
        return dados

    async def _via_assinatura(self, historico: list[dict], contexto_lead: str) -> dict | Decisao:
        """Monta a conversa como texto e chama o Claude Code com o ESQUEMA_RESPOSTA."""
        falas = []
        for m in historico:
            quem = "LEAD" if m["role"] == "user" else "VOCÊ"
            conteudo = m["content"] if isinstance(m["content"], str) else " ".join(
                b.get("text", "") for b in m["content"] if isinstance(b, dict))
            falas.append(f"[{quem}]: {conteudo}")
        pedido = ("<conversa>\n" + "\n".join(falas) + "\n</conversa>\n"
                  + (f"<contexto_do_lead>{contexto_lead}</contexto_do_lead>\n" if contexto_lead else "")
                  + "Escreva a sua próxima resposta ao LEAD e a ficha, no formato pedido.")
        dados = await self._cli_json(pedido, ESQUEMA_RESPOSTA)
        if not isinstance(dados, dict):
            return Decisao([], {}, True, "resposta inválida do modelo")
        return dados

    async def _cli_json(self, pedido: str, esquema: dict) -> dict | None:
        """Chama o Claude Code em modo headless, sem ferramentas, com saída no esquema dado."""
        if self._pasta_cli is None:
            # pasta vazia: o CLI não pega CLAUDE.md nem configuração de projeto nenhum
            self._pasta_cli = Path(tempfile.mkdtemp(prefix="agente-perito-"))
            (self._pasta_cli / "sistema.md").write_text(self.sistema, encoding="utf-8")
        args = ["claude", "-p", "--output-format", "json",
                "--json-schema", json.dumps(esquema),
                "--system-prompt-file", str(self._pasta_cli / "sistema.md"),
                "--model", self.modelo, "--effort", self.esforco,
                "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                "--no-session-persistence", "--disable-slash-commands"]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=self._pasta_cli, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            saida, erro = await asyncio.wait_for(proc.communicate(pedido.encode()), self.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Claude Code não respondeu em {self.timeout_s:.0f}s")
        try:
            resultado = json.loads(saida.decode() or "{}")
        except json.JSONDecodeError:
            raise RuntimeError(f"Claude Code saiu com código {proc.returncode}: {erro.decode()[-300:]}")
        if resultado.get("is_error") or proc.returncode:
            raise RuntimeError(f"Claude Code: {resultado.get('subtype')} {str(resultado.get('result'))[:300]}")
        dados = resultado.get("structured_output")
        if not isinstance(dados, dict):
            log.error("Claude Code sem structured_output: %r", str(resultado.get("result"))[:500])
            return None
        return dados

    def _pos_processar(self, dados: dict) -> Decisao:
        mensagens_saida = [limpar(m) for m in dados.pop("mensagens", []) if m and m.strip()][:3]
        transferir = bool(dados.get("transferir_para_humano"))
        motivo = dados.get("motivo_transferencia", "")

        if self.links is not None:
            estranhos = set().union(*(extrair_links(m) for m in mensagens_saida)) - self.links
            if estranhos:
                log.error("Link fora do conhecimento bloqueado: %s", estranhos)
                return Decisao([], dados, True, f"o agente tentou enviar link não autorizado: {sorted(estranhos)}")
        return Decisao(mensagens_saida, dados, transferir, motivo)
