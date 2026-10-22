"""Integração oficial com a Instagram API (Meta) — webhooks e envio de mensagens.

Usa a "Instagram API com login do Instagram" (graph.instagram.com), que exige
conta profissional (Empresa ou Criador de conteúdo) e as permissões
instagram_business_basic + instagram_business_manage_messages.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

LIMITE_TEXTO = 1000  # a Send API aceita até 1000 bytes UTF-8 por mensagem de texto


def assinatura_valida(corpo: bytes, cabecalho: str | None, app_secret: str) -> bool:
    """Confere o X-Hub-Signature-256 que a Meta manda em todo POST do webhook."""
    if not app_secret or not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho.removeprefix("sha256="))


@dataclass
class Evento:
    """Uma mensagem de direct recebida pelo webhook."""
    conversa: str        # IGSID do lead (id do usuário com escopo no Instagram)
    mid: str
    texto: str
    eco: bool            # True quando a mensagem saiu da sua conta (agente ou você no app)
    story_url: str = ""  # mídia do story em que a pessoa marcou a conta (para repostar)


def contas_do_aviso(payload: dict) -> set[str]:
    """Ids das contas (Instagram ou página) a que um aviso da Meta se refere."""
    return {str(e.get("id", "")) for e in payload.get("entry", [])} - {""}


def _entradas(payload: dict, contas: frozenset | set = frozenset()) -> list[dict]:
    """Só as entradas desta conta; sem `contas`, todas."""
    return [e for e in payload.get("entry", []) if not contas or str(e.get("id", "")) in contas]


def extrair_eventos(payload: dict, ig_user_id: str = "", contas: frozenset | set = frozenset()) -> list[Evento]:
    """Converte o JSON do webhook em eventos de mensagem. Ignora leituras, reações etc."""
    eventos: list[Evento] = []
    if payload.get("object") not in ("instagram", "page"):
        return eventos
    prefixo = "fb:" if payload.get("object") == "page" else ""
    for entrada in _entradas(payload, contas):
        conta = str(entrada.get("id", ""))
        for item in entrada.get("messaging", []):
            msg = item.get("message")
            if not msg or msg.get("is_deleted") or msg.get("is_unsupported"):
                continue
            remetente = str(item.get("sender", {}).get("id", ""))
            destinatario = str(item.get("recipient", {}).get("id", ""))
            eco = bool(msg.get("is_echo")) or remetente in {conta, ig_user_id} - {""}
            conversa = prefixo + (destinatario if eco else remetente)
            story_url = next((str((a.get("payload") or {}).get("url", "")) for a in msg.get("attachments", []) or []
                              if a.get("type") == "story_mention"), "")
            eventos.append(Evento(conversa=conversa, mid=msg.get("mid", ""), texto=_texto(msg), eco=eco,
                                  story_url=story_url))
    return eventos


@dataclass
class Comentario:
    """Um comentário num post da conta (webhook, campo "comments")."""
    id: str
    texto: str
    usuario_id: str      # id com escopo no Instagram; serve de conversa no direct
    username: str
    media_id: str
    resposta_a: str      # id do comentário-pai, se for resposta dentro de um fio
    canal: str = "instagram"  # "instagram" ou "facebook"
    nome: str = ""


def extrair_comentarios(payload: dict, contas: frozenset | set = frozenset()) -> list[Comentario]:
    comentarios: list[Comentario] = []
    if payload.get("object") == "page":
        return _comentarios_facebook(payload, contas)
    if payload.get("object") != "instagram":
        return comentarios
    for entrada in _entradas(payload, contas):
        for mudanca in entrada.get("changes", []):
            if mudanca.get("field") != "comments":
                continue
            v = mudanca.get("value") or {}
            de = v.get("from") or {}
            if not v.get("id") or not de.get("id"):
                continue
            comentarios.append(Comentario(
                id=str(v["id"]), texto=v.get("text", ""), usuario_id=str(de["id"]),
                username=(de.get("username") or "").lower(),
                media_id=str((v.get("media") or {}).get("id", "")), resposta_a=str(v.get("parent_id") or "")))
    return comentarios


def _comentarios_facebook(payload: dict, contas: frozenset | set = frozenset()) -> list[Comentario]:
    """Comentários novos nos posts da página (webhook "feed")."""
    saida = []
    for entrada in _entradas(payload, contas):
        pagina = str(entrada.get("id", ""))
        for mudanca in entrada.get("changes", []):
            v = mudanca.get("value") or {}
            de = v.get("from") or {}
            if (mudanca.get("field") != "feed" or v.get("item") != "comment" or v.get("verb") != "add"
                    or not v.get("comment_id") or not de.get("id") or str(de["id"]) == pagina):
                continue
            saida.append(Comentario(
                id=str(v["comment_id"]), texto=v.get("message", ""), usuario_id="fb:" + str(de["id"]),
                username="", media_id=str(v.get("post_id", "")),
                resposta_a=str(v.get("parent_id") or "") if v.get("parent_id") != v.get("post_id") else "",
                canal="facebook", nome=de.get("name", "")))
    return saida


def _texto(msg: dict) -> str:
    """Texto da mensagem, com uma descrição entre colchetes para anexos e respostas a stories."""
    partes = []
    reply_to = msg.get("reply_to") or {}
    if "story" in reply_to:
        partes.append("[o lead respondeu a um story seu]")
    for anexo in msg.get("attachments", []) or []:
        tipo = anexo.get("type", "arquivo")
        nomes = {"audio": "um áudio", "image": "uma imagem", "video": "um vídeo",
                 "share": "uma publicação compartilhada", "story_mention": "uma marcação sua no story dele",
                 "ig_reel": "um reel", "file": "um arquivo"}
        partes.append(f"[o lead enviou {nomes.get(tipo, 'um anexo')}]")
    if msg.get("text"):
        partes.append(msg["text"])
    return " ".join(partes) or "[mensagem sem texto]"


def dividir(texto: str, limite: int = LIMITE_TEXTO) -> list[str]:
    """Quebra um texto longo em pedaços que cabem no limite de bytes da Send API."""
    pedacos, atual = [], ""
    for palavra in texto.split(" "):
        candidato = f"{atual} {palavra}".strip()
        if len(candidato.encode()) > limite and atual:
            pedacos.append(atual)
            atual = palavra
        else:
            atual = candidato
    if atual:
        pedacos.append(atual)
    return pedacos


class ClienteInstagram:
    """api="instagram": token IGAA em graph.instagram.com.
    api="facebook": token de página EAA em graph.facebook.com (Messenger Platform para
    Instagram). O webhook e o envio têm o mesmo formato; muda o host e a conta."""

    def __init__(self, access_token: str, versao: str = "v23.0", modo_teste: bool = False,
                 http: httpx.AsyncClient | None = None, api: str = "instagram"):
        self.token = access_token
        self.api = api
        host = "graph.facebook.com" if api == "facebook" else "graph.instagram.com"
        self.base = f"https://{host}/{versao}"
        self.modo_teste = modo_teste
        self.http = http or httpx.AsyncClient(timeout=20)

    async def enviar_texto(self, igsid: str, texto: str) -> list[str]:
        """Envia texto ao lead e devolve os message_id gerados."""
        mids = []
        for pedaco in dividir(texto):
            if self.modo_teste:
                log.info("[MODO_TESTE] para %s: %s", igsid, pedaco)
                mids.append(f"teste-{len(mids)}-{hash(pedaco)}")
                continue
            resp = await self.http.post(
                f"{self.base}/me/messages",
                headers={"Authorization": f"Bearer {self.token}"},
                json=_corpo(igsid, {"message": {"text": pedaco}}),
            )
            if resp.status_code >= 400:
                log.error("Falha ao enviar para %s: %s %s", igsid, resp.status_code, resp.text)
                resp.raise_for_status()
            mids.append(resp.json().get("message_id", ""))
        return mids

    async def responder_comentario(self, comentario_id: str, texto: str, canal: str = "instagram") -> str:
        """Resposta pública ao comentário. Devolve o id da resposta."""
        if self.modo_teste:
            log.info("[MODO_TESTE] resposta pública a %s: %s", comentario_id, texto)
            return "teste"
        rota = "comments" if canal == "facebook" else "replies"
        resp = await self.http.post(f"{self.base}/{comentario_id}/{rota}",
                                    headers={"Authorization": f"Bearer {self.token}"},
                                    data={"message": texto})
        if resp.status_code >= 400:
            raise ErroMeta(_mensagem_erro(resp))
        return resp.json().get("id", "")

    async def resposta_privada(self, comentario_id: str, texto: str) -> str:
        """Mensagem no direct de quem comentou (Private Reply: uma por comentário, até 7 dias)."""
        if self.modo_teste:
            log.info("[MODO_TESTE] direct para quem comentou %s: %s", comentario_id, texto)
            return f"teste-privada-{comentario_id}"
        resp = await self.http.post(
            f"{self.base}/me/messages", headers={"Authorization": f"Bearer {self.token}"},
            json={"recipient": {"comment_id": comentario_id}, "message": {"text": texto[:LIMITE_TEXTO]}})
        if resp.status_code >= 400:
            raise ErroMeta(_mensagem_erro(resp))
        return resp.json().get("message_id", "")

    async def baixar(self, url: str) -> tuple[bytes, str]:
        """Baixa a mídia de um story em que a conta foi marcada. Devolve (conteúdo, content-type)."""
        resp = await self.http.get(url, follow_redirects=True)
        if resp.status_code != 200:  # o CDN da Meta às vezes exige o token
            resp = await self.http.get(url, follow_redirects=True,
                                       headers={"Authorization": f"Bearer {self.token}"})
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "").split(";")[0]

    async def publicar_story(self, ig_user_id: str, url_publica: str, video: bool) -> str:
        """Publica um story na conta a partir de uma URL pública (Content Publishing API)."""
        if self.modo_teste:
            log.info("[MODO_TESTE] repostaria story: %s", url_publica)
            return "teste"
        auth = {"Authorization": f"Bearer {self.token}"}
        dados = {"media_type": "STORIES", ("video_url" if video else "image_url"): url_publica}
        resp = await self.http.post(f"{self.base}/{ig_user_id}/media", headers=auth, data=dados)
        if resp.status_code >= 400:
            raise ErroMeta(_mensagem_erro(resp))
        container = resp.json()["id"]
        for _ in range(30):  # vídeo precisa ser processado antes de publicar
            estado = await self.http.get(f"{self.base}/{container}", headers=auth,
                                         params={"fields": "status_code"})
            codigo = estado.json().get("status_code", "FINISHED") if estado.status_code == 200 else "FINISHED"
            if codigo == "FINISHED":
                break
            if codigo == "ERROR":
                raise ErroMeta("a Meta não conseguiu processar a mídia do story")
            await asyncio.sleep(5)
        resp = await self.http.post(f"{self.base}/{ig_user_id}/media_publish", headers=auth,
                                    data={"creation_id": container})
        if resp.status_code >= 400:
            raise ErroMeta(_mensagem_erro(resp))
        return resp.json().get("id", "")

    async def legenda(self, media_id: str, canal: str = "instagram") -> str:
        """Legenda do post, para o agente entender o contexto do comentário."""
        if self.modo_teste or not media_id:
            return ""
        campo = "message" if canal == "facebook" else "caption"
        try:
            resp = await self.http.get(f"{self.base}/{media_id}", params={"fields": campo},
                                       headers={"Authorization": f"Bearer {self.token}"})
            return resp.json().get(campo, "") if resp.status_code == 200 else ""
        except httpx.HTTPError:
            return ""

    async def digitando(self, igsid: str) -> None:
        """Mostra "digitando..." para o lead (melhor esforço, ignora erro)."""
        if self.modo_teste:
            return
        try:
            await self.http.post(
                f"{self.base}/me/messages",
                headers={"Authorization": f"Bearer {self.token}"},
                json=_corpo(igsid, {"sender_action": "typing_on"}),
            )
        except httpx.HTTPError:
            pass

    async def perfil(self, igsid: str) -> dict:
        """Nome e @ do lead (permitido depois que ele te mandou mensagem)."""
        if self.modo_teste:
            return {}
        campos = "name,username,is_user_follow_business,follower_count"
        if igsid.startswith("fb:"):
            igsid, campos = igsid[3:], "name"
        try:
            resp = await self.http.get(
                f"{self.base}/{igsid}",
                params={"fields": campos},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            return resp.json() if resp.status_code == 200 else {}
        except httpx.HTTPError:
            return {}

    async def renovar_token(self) -> dict:
        """Renova o token de longa duração (vale 60 dias; o servidor renova sozinho toda semana)."""
        resp = await self.http.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": self.token},
        )
        resp.raise_for_status()
        return resp.json()

    # --- configuração da conta (usado pelo comando agente-perito) -----------
    async def conta(self) -> dict:
        """Confere o token e devolve {user_id, username} da conta profissional."""
        if self.api == "facebook":
            # token de página: /me é a página; a conta do Instagram vem ligada a ela
            resp = await self.http.get(f"{self.base}/me", params={
                "fields": "instagram_business_account{id,username}", "access_token": self.token})
            if resp.status_code != 200:
                raise ErroMeta(_mensagem_erro(resp))
            conta = resp.json().get("instagram_business_account")
            if not conta:
                raise ErroMeta("a página deste token não tem conta do Instagram ligada")
            return {"user_id": conta["id"], "username": conta.get("username", ""),
                    "page_id": str(resp.json().get("id", "")),
                    "account_type": "profissional, via página do Facebook"}
        resp = await self.http.get(f"{self.base}/me", params={
            "fields": "user_id,username,account_type", "access_token": self.token})
        if resp.status_code != 200:
            raise ErroMeta(_mensagem_erro(resp))
        return resp.json()

    async def inscrever_mensagens(self) -> None:
        """Liga o envio de DMs desta conta para o webhook do app."""
        # página do Facebook: também os comentários dos posts dela ("feed")
        campos = "messages,feed" if self.api == "facebook" else "messages"
        resp = await self.http.post(f"{self.base}/me/subscribed_apps", params={
            "subscribed_fields": campos, "access_token": self.token})
        if resp.status_code != 200 or not resp.json().get("success"):
            raise ErroMeta(_mensagem_erro(resp))

    async def inscricoes(self) -> list[str]:
        resp = await self.http.get(f"{self.base}/me/subscribed_apps", params={"access_token": self.token})
        if resp.status_code != 200:
            raise ErroMeta(_mensagem_erro(resp))
        campos: list[str] = []
        for app in resp.json().get("data", []):
            campos += app.get("subscribed_fields", [])
        return campos


def _corpo(destino: str, extra: dict) -> dict:
    """Corpo da Send API. Conversa do Messenger vem como "fb:<PSID>" e exige messaging_type."""
    if destino.startswith("fb:"):
        return {"recipient": {"id": destino[3:]}, "messaging_type": "RESPONSE", **extra}
    return {"recipient": {"id": destino}, **extra}


class ErroMeta(Exception):
    pass


def _mensagem_erro(resp: httpx.Response) -> str:
    try:
        erro = resp.json().get("error", {})
        return f"{erro.get('message', resp.text)} (código {erro.get('code', resp.status_code)})"
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
