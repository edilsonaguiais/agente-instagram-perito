import asyncio
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agente_direct.app import Orquestrador, criar_app
from agente_direct.cerebro import ESQUEMA_RESPOSTA, Decisao, montar_sistema
from agente_direct.config import Config, RAIZ
from agente_direct.instagram import ClienteInstagram, dividir, extrair_eventos
from agente_direct.memoria import Memoria

SEGREDO = "segredo-do-app"
CONTA = "17841400000000000"
LEAD = "990011"


class CerebroFalso:
    def __init__(self, mensagens=("Fala, Doutor! Você já atua como perito?",), transferir=False):
        self.mensagens, self.transferir, self.chamadas = list(mensagens), transferir, []

    async def decidir(self, historico, contexto_lead=""):
        self.chamadas.append(historico)
        return Decisao(self.mensagens, {"produto_recomendado": "aguias_da_pericia"},
                       self.transferir, "lead pronto" if self.transferir else "")


def montar(cerebro=None, enviados=None):
    cfg = Config(ig_access_token="tok", ig_app_secret=SEGREDO, ig_verify_token="verifica",
                 ig_user_id=CONTA, espera_agrupar_s=0.05, admin_token="adm")
    enviados = enviados if enviados is not None else []

    def handler(request: httpx.Request):
        if request.method == "POST":
            corpo = json.loads(request.content)
            if "message" in corpo:
                enviados.append(corpo["message"]["text"])
            return httpx.Response(200, json={"recipient_id": LEAD, "message_id": f"m_bot_{len(enviados)}"})
        return httpx.Response(200, json={"username": "dra.carla", "name": "Carla"})

    ig = ClienteInstagram("tok", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    orq = Orquestrador(cfg, Memoria(":memory:"), ig, cerebro or CerebroFalso())
    return cfg, orq, enviados


def payload(texto, mid, eco=False):
    remetente, destino = (CONTA, LEAD) if eco else (LEAD, CONTA)
    msg = {"mid": mid, "text": texto}
    if eco:
        msg["is_echo"] = True
    return {"object": "instagram", "entry": [{"id": CONTA, "time": 1, "messaging": [
        {"sender": {"id": remetente}, "recipient": {"id": destino}, "timestamp": 1, "message": msg}]}]}


def assinar(corpo: bytes) -> str:
    return "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()


def test_verificacao_do_webhook():
    cfg, orq, _ = montar()
    cliente = TestClient(criar_app(cfg, orq))
    ok = cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verifica",
                                         "hub.challenge": "123"})
    assert ok.status_code == 200 and ok.text == "123"
    assert cliente.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                           "hub.challenge": "1"}).status_code == 403


def test_rejeita_assinatura_invalida():
    cfg, orq, _ = montar()
    cliente = TestClient(criar_app(cfg, orq))
    corpo = json.dumps(payload("oi", "m1")).encode()
    r = cliente.post("/webhook", content=corpo, headers={"X-Hub-Signature-256": "sha256=errado"})
    assert r.status_code == 401


def test_agrupa_mensagens_e_responde_uma_vez():
    async def cenario():
        _, orq, enviados = montar()
        for i, texto in enumerate(["oi", "vi seu post", "quero saber da mentoria"]):
            for ev in extrair_eventos(payload(texto, f"m{i}"), CONTA):
                orq.receber(ev)
        await asyncio.sleep(0.3)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert len(orq.cerebro.chamadas) == 1
    assert orq.cerebro.chamadas[0][-1]["content"] == "oi\nvi seu post\nquero saber da mentoria"
    assert enviados == ["Fala, Doutor! Você já atua como perito?"]
    lead = orq.memoria.lead(LEAD)
    assert lead["username"] == "dra.carla"
    assert lead["ficha"]["produto_recomendado"] == "aguias_da_pericia"


def test_webhook_repetido_nao_gera_segunda_resposta():
    async def cenario():
        _, orq, enviados = montar()
        for _ in range(2):
            for ev in extrair_eventos(payload("oi", "m-dup"), CONTA):
                orq.receber(ev)
        await asyncio.sleep(0.2)
        return enviados

    assert len(asyncio.run(cenario())) == 1


def test_eco_do_agente_e_ignorado_e_resposta_humana_pausa():
    async def cenario():
        _, orq, enviados = montar()
        for ev in extrair_eventos(payload("oi", "m1"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        # eco da mensagem que o próprio agente enviou: não pausa
        for ev in extrair_eventos(payload(enviados[0], "m_bot_1", eco=True), CONTA):
            orq.receber(ev)
        assert not orq.memoria.esta_pausado(LEAD)
        # você responde pelo app: pausa e o agente fica quieto
        for ev in extrair_eventos(payload("Oi Carla, aqui é o Edilson!", "m_humano", eco=True), CONTA):
            orq.receber(ev)
        assert orq.memoria.esta_pausado(LEAD)
        for ev in extrair_eventos(payload("que legal!", "m2"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert len(enviados) == 1
    hist = orq.memoria.historico(LEAD)
    assert "[resposta enviada manualmente pelo dono da conta]" in hist[1]["content"]


def test_aviso_ao_perito_nao_tira_o_agente_da_conversa():
    async def cenario():
        _, orq, enviados = montar(CerebroFalso(["Recebi o laudo. Te mando a proposta hoje?"], transferir=True))
        for ev in extrair_eventos(payload("quero pagar à vista", "m1"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        for ev in extrair_eventos(payload("e aí?", "m2"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert enviados == ["Recebi o laudo. Te mando a proposta hoje?"] * 2  # seguiu atendendo
    assert orq.memoria.lead(LEAD)["transferido"] == 0


def test_anexos_viram_descricao():
    p = payload("", "m1")
    p["entry"][0]["messaging"][0]["message"] = {"mid": "m1", "attachments": [{"type": "audio"}]}
    assert extrair_eventos(p, CONTA)[0].texto == "[o lead enviou um áudio]"


def test_dividir_respeita_limite_de_bytes():
    texto = "perícia " * 400
    partes = dividir(texto)
    assert all(len(p.encode()) <= 1000 for p in partes)
    assert " ".join(partes) == texto.strip()


def test_prompt_inclui_os_tres_documentos():
    sistema = montar_sistema(RAIZ / "exemplos" / "perito-contabil-bancario", "Dra. Marina Exemplo", "agente.exemplo.com")
    for marca in ("<servicos>", "<tom_de_voz>", "<metodo_vendas>", "<icp>", "<faq>", "<objecoes>",
                  "Consulta técnica inicial", "ADVOGADO", "VOCÊ ASSUME SEMPRE",
                  "https://agente.exemplo.com/p/consulta-tecnica-inicial"):
        assert marca in sistema
    for proibido in ("IBCAPPA", "ÁGUIAS", "Central de Peritos", "edilsonaguiais"):
        assert proibido not in sistema


def _sem_propriedades_soltas(no):
    if isinstance(no, dict):
        if no.get("type") == "object":
            assert no.get("additionalProperties") is False
            assert set(no["required"]) == set(no["properties"])
        for v in no.values():
            _sem_propriedades_soltas(v)


def test_esquema_valido_para_saida_estruturada():
    _sem_propriedades_soltas(ESQUEMA_RESPOSTA)


# --- salvaguardas novas ----------------------------------------------------
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx2

from agente_direct.app import MENSAGEM_ESPERA, texto_followup
from agente_direct.cerebro import Cerebro, limpar, links_permitidos


def _resposta_claude(mensagens, **extra):
    corpo = {"mensagens": mensagens,
             "bant": {k: {"status": "desconhecido", "evidencia": ""} for k in ("budget", "authority", "need", "timing")},
             "perfil": "", "produto_recomendado": "aguias_one", "estagio": "apresentacao",
             "transferir_para_humano": False, "motivo_transferencia": "", "resumo_lead": "",
             "dor_resumida": "", **extra}

    def handler(request):
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(corpo)}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
    import anthropic
    return anthropic.AsyncAnthropic(api_key="x", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_links_oficiais_estao_na_lista_permitida():
    links = links_permitidos(RAIZ / "exemplos" / "perito-contabil-bancario", "agente.exemplo.com")
    assert "https://agente.exemplo.com/p/consulta-tecnica-inicial" in links
    assert "https://agente.exemplo.com/p/analise-previa-de-contrato-bancario" in links
    assert links_permitidos(RAIZ / "exemplos" / "perito-contabil-bancario") == links - {"https://agente.exemplo.com/p/consulta-tecnica-inicial",
                                               "https://agente.exemplo.com/p/analise-previa-de-contrato-bancario"}


def test_link_nao_autorizado_e_bloqueado_e_transfere():
    links = links_permitidos(RAIZ / "exemplos" / "perito-contabil-bancario", "agente.exemplo.com")
    cliente = _resposta_claude(["Segue o link: https://pix-falso.example/pagar"])
    cerebro = Cerebro("sistema", cliente=cliente, links=links)
    d = asyncio.run(cerebro.decidir([{"role": "user", "content": "quero o link"}]))
    assert d.mensagens == [] and d.transferir


def test_link_oficial_passa_mesmo_com_pontuacao():
    links = links_permitidos(RAIZ / "exemplos" / "perito-contabil-bancario", "agente.exemplo.com")
    texto = "Lá tem o QR Code: https://agente.exemplo.com/p/consulta-tecnica-inicial. Combinado?"
    cerebro = Cerebro("sistema", cliente=_resposta_claude([texto]), links=links)
    d = asyncio.run(cerebro.decidir([{"role": "user", "content": "quanto custa?"}]))
    assert d.mensagens == [texto] and not d.transferir


def test_tira_travessao():
    assert limpar("Não é sobre laudo — é sobre negócio") == "Não é sobre laudo, é sobre negócio"


def test_bloqueados_e_sandbox():
    async def cenario(cfg_extra):
        cfg, orq, enviados = montar()
        orq.cfg = Config(**{**cfg.__dict__, **cfg_extra})
        for ev in extrair_eventos(payload("oi", "m1"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        return enviados

    assert asyncio.run(cenario({"bloqueados": frozenset({"dra.carla"})})) == []
    assert asyncio.run(cenario({"sandbox": frozenset({"outra.pessoa"})})) == []
    assert len(asyncio.run(cenario({"sandbox": frozenset({"dra.carla"})}))) == 1


def test_teto_de_mensagens_passa_para_humano():
    async def cenario():
        cfg, orq, enviados = montar()
        orq.cfg = Config(**{**cfg.__dict__, "max_msgs_sessao": 1})
        for i in range(2):
            for ev in extrair_eventos(payload(f"msg {i}", f"m{i}"), CONTA):
                orq.receber(ev)
            await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert len(enviados) == 2
    assert enviados[-1] == MENSAGEM_ESPERA
    assert orq.memoria.lead(LEAD)["transferido"] == 1


def _conversa_parada(t_lead):
    """Lead falou em t_lead; o agente respondeu 1 min depois e o lead sumiu."""
    async def preparar():
        _, orq, enviados = montar()
        for ev in extrair_eventos(payload("quero saber do ONE", "m1"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        orq.memoria._db.execute("UPDATE mensagens SET criado_em = ? WHERE papel = 'user'", (t_lead,))
        orq.memoria._db.execute("UPDATE mensagens SET criado_em = ? WHERE papel = 'assistant'", (t_lead + 60,))
        orq.memoria.atualizar_lead(LEAD, ficha={"produto_recomendado": "aguias_one", "estagio": "apresentacao"})
        return orq, enviados
    return preparar


def test_retomadas_30_min_e_2_h_no_maximo_duas():
    fuso = ZoneInfo("America/Sao_Paulo")
    t_lead = datetime(2026, 10, 14, 14, 0, tzinfo=fuso).timestamp()   # lead falou às 14h
    base = t_lead + 60                                                # agente respondeu às 14h01

    async def cenario():
        orq, enviados = await _conversa_parada(t_lead)()
        r = [await orq.verificar_followups(base + m * 60) for m in (10, 31, 40, 121, 125, 300)]
        return r, enviados

    r, enviados = asyncio.run(cenario())
    # 10 min: cedo; 31 min: 1ª; 40 min: não repete; 2h01: 2ª; depois disso, nada
    assert r == [0, 1, 0, 1, 0, 0]
    assert len(enviados) == 3   # resposta + 2 retomadas


def test_retomada_zera_quando_o_lead_responde():
    fuso = ZoneInfo("America/Sao_Paulo")
    t_lead = datetime(2026, 10, 14, 14, 0, tzinfo=fuso).timestamp()

    async def cenario():
        orq, _ = await _conversa_parada(t_lead)()
        primeira = await orq.verificar_followups(t_lead + 60 + 31 * 60)
        orq.memoria.registrar(LEAD, "user", "voltei", "m2")      # lead respondeu
        orq.memoria.registrar(LEAD, "assistant", "boa, me conta", "m_bot_x")
        agora = __import__("time").time()
        orq.memoria._db.execute("UPDATE mensagens SET criado_em = ? WHERE mid = 'm2'", (agora,))
        orq.memoria._db.execute("UPDATE mensagens SET criado_em = ? WHERE mid = 'm_bot_x'", (agora + 60,))
        cedo = await orq.verificar_followups(agora + 60 + 10 * 60)
        return primeira, cedo

    assert asyncio.run(cenario()) == (1, 0)


def test_retomada_respeita_silencio_noturno():
    fuso = ZoneInfo("America/Sao_Paulo")
    t_lead = datetime(2026, 10, 14, 23, 0, tzinfo=fuso).timestamp()   # 30 min depois = 23h31

    async def cenario():
        orq, _ = await _conversa_parada(t_lead)()
        return await orq.verificar_followups(t_lead + 60 + 31 * 60)

    assert asyncio.run(cenario()) == 0


def test_retomada_pula_quem_nao_e_lead():
    fuso = ZoneInfo("America/Sao_Paulo")
    t_lead = datetime(2026, 10, 14, 14, 0, tzinfo=fuso).timestamp()

    async def cenario():
        orq, _ = await _conversa_parada(t_lead)()
        orq.memoria.atualizar_lead(LEAD, ficha={"produto_recomendado": "nenhum", "estagio": "relacionamento"})
        return await orq.verificar_followups(t_lead + 60 + 31 * 60)

    assert asyncio.run(cenario()) == 0


def test_texto_followup_sem_nome_e_sem_dor():
    assert texto_followup(None, "") == "Retomo nossa conversa. Ficou algum ponto sem resposta para você decidir?"


def test_sem_mensagem_do_modelo_pede_para_aguardar():
    async def cenario():
        _, orq, enviados = montar(CerebroFalso([], transferir=True))
        for ev in extrair_eventos(payload("qual a garantia do Águias?", "m1"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert enviados == [MENSAGEM_ESPERA]
    assert orq.memoria.esta_pausado(LEAD)


def test_resposta_manual_devolve_conversa_ao_agente_depois_da_pausa():
    async def cenario():
        _, orq, _ = montar(CerebroFalso([], transferir=True))  # sem resposta do modelo: aí pede para aguardar
        for ev in extrair_eventos(payload("quero desconto", "m1"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        assert orq.memoria.lead(LEAD)["transferido"] == 1
        for ev in extrair_eventos(payload("Oi Carla, sobre o desconto...", "m_ed", eco=True), CONTA):
            orq.receber(ev)
        return orq.memoria.lead(LEAD)

    lead = asyncio.run(cenario())
    assert lead["transferido"] == 0 and lead["pausado_ate"] > 0  # pausado agora, volta sozinho depois


def test_erro_no_claude_pede_para_aguardar():
    class CerebroQuebrado:
        async def decidir(self, historico, contexto_lead=""):
            raise RuntimeError("Claude fora do ar")

    async def cenario():
        _, orq, enviados = montar(CerebroQuebrado())
        for ev in extrair_eventos(payload("oi", "m1"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        for ev in extrair_eventos(payload("alô?", "m2"), CONTA):
            orq.receber(ev)
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert enviados == [MENSAGEM_ESPERA]          # uma vez só, não repete
    assert orq.memoria.lead(LEAD)["transferido"] == 1


# --- comando agente-direct -------------------------------------------------
import agente_direct.__main__ as cli


def test_env_ida_e_volta(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV", tmp_path / ".env")
    cli.gravar_env({"DONO_NOME": "Maria Silva", "IG_ACCESS_TOKEN": "abc=123", "EXTRA": "x"})
    lido = cli.ler_env()
    assert lido["DONO_NOME"] == "Maria Silva" and lido["IG_ACCESS_TOKEN"] == "abc=123"
    assert lido["MODELO"] == "claude-opus-5-5" and lido["EXTRA"] == "x"


def test_detecta_modelo_nao_preenchido():
    assert cli.placeholders(RAIZ / "modelos" / "conhecimento")            # modelo em branco: tem [SEU NOME] etc.
    assert cli.placeholders(RAIZ / "exemplos" / "perito-contabil-bancario") == []  # exemplo pronto: nada pendente


def test_preparar_conhecimento_copia_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONHECIMENTO", tmp_path / "conhecimento")
    monkeypatch.setattr("builtins.input", lambda _: "1")
    cli.preparar_conhecimento()
    for nome in cli.ARQUIVOS:
        assert (tmp_path / "conhecimento" / nome).exists()


# --- comentários, story, Facebook e rastreamento ----------------------------
from agente_direct.app import rastrear_links
from agente_direct.instagram import extrair_comentarios


def test_extrai_comentario_do_instagram():
    dados = {"object": "instagram", "entry": [{"id": CONTA, "time": 1, "changes": [{"field": "comments", "value": {
        "from": {"id": "555", "username": "Dra.Carla"}, "media": {"id": "m9"}, "id": "c1", "text": "quero saber"}}]}]}
    c = extrair_comentarios(dados)[0]
    assert (c.id, c.usuario_id, c.username, c.media_id, c.canal) == ("c1", "555", "dra.carla", "m9", "instagram")


def test_extrai_comentario_do_facebook_e_ignora_a_propria_pagina():
    def feed(de):
        return {"object": "page", "entry": [{"id": "PAG", "time": 1, "changes": [{"field": "feed", "value": {
            "item": "comment", "verb": "add", "comment_id": "c2", "post_id": "PAG_1", "message": "como faço?",
            "from": {"id": de, "name": "Carla Souza"}}}]}]}
    c = extrair_comentarios(feed("777"))[0]
    assert (c.usuario_id, c.nome, c.canal) == ("fb:777", "Carla Souza", "facebook")
    assert extrair_comentarios(feed("PAG")) == []


def test_messenger_vira_conversa_fb_e_marcacao_em_story_traz_a_midia():
    dados = {"object": "page", "entry": [{"id": "PAG", "time": 1, "messaging": [
        {"sender": {"id": "777"}, "recipient": {"id": "PAG"}, "timestamp": 1, "message": {"mid": "x", "text": "oi"}}]}]}
    assert extrair_eventos(dados)[0].conversa == "fb:777"
    story = payload("", "m5")
    story["entry"][0]["messaging"][0]["message"] = {"mid": "m5", "attachments": [
        {"type": "story_mention", "payload": {"url": "https://cdn.exemplo/story.jpg"}}]}
    ev = extrair_eventos(story, CONTA)[0]
    assert ev.story_url == "https://cdn.exemplo/story.jpg" and "story" in ev.texto


def test_rastreio_troca_lead_pelo_id_da_conversa():
    link = "https://pay.hotmart.com/X?off=a&src=direct_ig%7Cmarinaexemplo%7Clead%7Ccurso"
    assert rastrear_links(f"Link: {link}", "123") == f"Link: {link.replace('%7Clead%7C', '%7C123%7C')}"


def test_ignora_aviso_de_outra_conta_do_mesmo_app():
    outra = "17841499999999999"
    p = payload("oi", "m1")
    p["entry"][0]["id"] = outra
    assert extrair_eventos(p, CONTA, frozenset({CONTA})) == []
    assert len(extrair_eventos(p, CONTA)) == 1  # sem ids no .env: aceita tudo (instalação antiga)


def test_encaminha_aviso_de_outra_conta_com_corpo_e_assinatura_intactos(monkeypatch):
    import agente_direct.app as modulo
    repassados = []

    async def falso(urls, corpo, assinatura):
        repassados.append((urls, corpo, assinatura))

    monkeypatch.setattr(modulo, "encaminhar", falso)
    cfg = Config(ig_access_token="tok", ig_app_secret=SEGREDO, ig_verify_token="verifica",
                 ig_user_id=CONTA, espera_agrupar_s=0.05, encaminhar_webhook=("https://outro/webhook",))
    _, orq, _ = montar()
    cliente = TestClient(criar_app(cfg, orq, followup=False))
    p = payload("oi", "m1")
    p["entry"][0]["id"] = "17841499999999999"
    corpo = json.dumps(p).encode()
    r = cliente.post("/webhook", content=corpo, headers={"X-Hub-Signature-256": assinar(corpo)})
    assert r.status_code == 200
    assert repassados == [(("https://outro/webhook",), corpo, assinar(corpo))]
    # aviso já encaminhado não volta (sem eco entre os agentes)
    cliente.post("/webhook", content=corpo, headers={"X-Hub-Signature-256": assinar(corpo), "X-Encaminhado": "1"})
    assert len(repassados) == 1
    # aviso da própria conta não é encaminhado
    meu = json.dumps(payload("oi", "m2")).encode()
    cliente.post("/webhook", content=meu, headers={"X-Hub-Signature-256": assinar(meu)})
    assert len(repassados) == 1


# --- páginas de venda com Pix ------------------------------------------------
from decimal import Decimal

from agente_direct.paginas import _crc16, ler_pagina, pix_copia_e_cola


def test_crc_do_pix_bate_com_o_exemplo_do_banco_central():
    exemplo = ("00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
               "5913Fulano de Tal6008BRASILIA62070503***6304")
    assert _crc16(exemplo) == "1D3D"


def test_pix_copia_e_cola_tem_chave_valor_e_crc():
    codigo = pix_copia_e_cola("marina@exemplo.com.br", Decimal("997.00"), "Marina Exemplo", "Goiânia", "LAUDO")
    assert "0014br.gov.bcb.pix0121marina@exemplo.com.br" in codigo
    assert "5406997.00" in codigo and "5914MARINA EXEMPLO" in codigo and "6007GOIANIA" in codigo
    assert codigo[-4:] == _crc16(codigo[:-4])


def test_paginas_do_exemplo_abrem_com_preco_e_qr():
    pasta = RAIZ / "exemplos" / "perito-contabil-bancario"
    precos = {"consulta-tecnica-inicial": "350.00", "analise-previa-de-contrato-bancario": "890.00"}
    for endereco, preco in precos.items():
        assert str(ler_pagina(pasta, endereco).preco) == preco
    assert ler_pagina(pasta, "../.env") is None
    cfg = Config(ig_access_token="tok", ig_app_secret=SEGREDO, pasta_conhecimento=pasta, dono="Dra. Marina Exemplo",
                 pix_chave="marina@exemplo.com.br", pix_nome="Marina Exemplo", pix_cidade="Goiania")
    _, orq, _ = montar()
    cliente = TestClient(criar_app(cfg, orq, followup=False))
    r = cliente.get("/p/consulta-tecnica-inicial")
    assert r.status_code == 200 and "R$ 350,00" in r.text and "<svg" in r.text and "br.gov.bcb.pix" in r.text
    assert cliente.get("/p/nao-existe").status_code == 404
