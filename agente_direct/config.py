"""Configuração lida do arquivo .env (criado por `agente-perito configurar`)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _carregar_dotenv(caminho: Path) -> None:
    """Carrega um .env simples (CHAVE=valor) sem sobrescrever o ambiente."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    # Quem é o dono da conta (como o agente se refere a ele)
    dono: str = "o dono da conta"

    # Instagram (API oficial da Meta — Instagram API com login do Instagram)
    ig_access_token: str = ""
    ig_app_secret: str = ""
    ig_verify_token: str = ""
    ig_user_id: str = ""
    ig_page_id: str = ""      # página do Facebook ligada ao Instagram (token EAA)
    graph_versao: str = "v23.0"
    # "instagram": token IGAA (login do Instagram, graph.instagram.com)
    # "facebook": token de página EAA (login do Facebook, graph.facebook.com), não expira
    ig_api: str = "instagram"

    # Claude
    modelo: str = "claude-opus-5-5"
    esforco: str = "medium"
    motor_claude: str = "api"  # "api" (ANTHROPIC_API_KEY) ou "assinatura" (CLAUDE_CODE_OAUTH_TOKEN)

    # Comportamento
    espera_agrupar_s: float = 8.0
    pausa_humano_horas: float = 24.0
    banco: Path = field(default_factory=lambda: RAIZ / "dados" / "direct.sqlite3")
    pasta_conhecimento: Path = field(default_factory=lambda: RAIZ / "conhecimento")
    notificar_url: str = ""
    telegram_token: str = ""     # bot do Telegram que te avisa quando alguém espera sua resposta
    telegram_chat_id: str = ""
    admin_token: str = ""
    modo_teste: bool = False  # True: não envia nada ao Instagram, só registra no log
    # Várias contas no mesmo app da Meta: o app tem uma URL de webhook só. O agente que
    # recebe repassa o aviso de outra conta para o agente dela (corpo e assinatura intactos).
    encaminhar_webhook: tuple = ()

    # Pix das páginas de venda (/p/<produto>)
    pix_chave: str = ""
    pix_nome: str = ""
    pix_cidade: str = ""

    # Freios
    max_msgs_sessao: int = 40           # mensagens do agente por conversa em 24 h; no teto, passa para humano
    bloqueados: frozenset = frozenset()  # @ (sem arroba) ou IGSID que o agente nunca atende
    sandbox: frozenset = frozenset()     # se preenchido, o agente SÓ atende estes @ (fase de teste)

    # Comentários e marcações em story
    responder_comentarios: bool = True   # responde em público e aborda no direct quem mostrou interesse
    repostar_stories: bool = False       # reposta o story de quem marcou a conta (sem o @ clicável)
    max_reposts_hora: int = 10           # freio para não lotar os seus stories em dia de evento
    dominio: str = ""                    # endereço público, usado para servir a mídia a repostar

    # Follow-up (um único toque, dentro da janela de 24 h do Instagram)
    followup_apos_h: float = 20.0       # (antigo; mantido só para compatibilidade do .env)
    retomada_1_min: float = 30          # 1ª retomada: minutos depois da mensagem sem resposta
    retomada_2_min: float = 120         # 2ª retomada ("ficou alguma dúvida?")
    fuso: str = "America/Sao_Paulo"
    followup_hora_inicio: int = 8
    followup_hora_fim: int = 21

    @classmethod
    def do_ambiente(cls) -> "Config":
        _carregar_dotenv(RAIZ / ".env")
        e = os.environ.get
        return cls(
            dono=e("DONO_NOME", "o dono da conta"),
            ig_access_token=e("IG_ACCESS_TOKEN", ""),
            ig_app_secret=e("IG_APP_SECRET", ""),
            ig_verify_token=e("IG_VERIFY_TOKEN", ""),
            ig_user_id=e("IG_USER_ID", ""),
            ig_page_id=e("IG_PAGE_ID", ""),
            graph_versao=e("GRAPH_VERSAO", "v23.0"),
            ig_api=e("IG_API") or ("facebook" if e("IG_ACCESS_TOKEN", "").startswith("EAA") else "instagram"),
            modelo=e("MODELO", "claude-opus-5-5"),
            esforco=e("ESFORCO", "medium"),
            motor_claude=e("CLAUDE_MOTOR") or ("assinatura" if e("CLAUDE_CODE_OAUTH_TOKEN")
                                               and not e("ANTHROPIC_API_KEY") else "api"),
            espera_agrupar_s=float(e("ESPERA_AGRUPAR_S", "8")),
            pausa_humano_horas=float(e("PAUSA_HUMANO_HORAS", "24")),
            banco=Path(e("BANCO", str(RAIZ / "dados" / "direct.sqlite3"))),
            pasta_conhecimento=Path(e("PASTA_CONHECIMENTO", str(RAIZ / "conhecimento"))),
            notificar_url=e("NOTIFICAR_URL", ""),
            telegram_token=e("TELEGRAM_TOKEN", ""),
            telegram_chat_id=e("TELEGRAM_CHAT_ID", ""),
            admin_token=e("ADMIN_TOKEN", ""),
            modo_teste=e("MODO_TESTE", "0").lower() in ("1", "true", "sim"),
            pix_chave=e("PIX_CHAVE", ""),
            pix_nome=e("PIX_NOME", ""),
            pix_cidade=e("PIX_CIDADE", ""),
            encaminhar_webhook=tuple(u.strip() for u in e("ENCAMINHAR_WEBHOOK", "").split(",") if u.strip()),
            max_msgs_sessao=int(e("MAX_MSGS_SESSAO", "40")),
            bloqueados=_lista(e("BLOQUEADOS", "")),
            sandbox=_lista(e("SANDBOX", "")),
            followup_apos_h=float(e("FOLLOWUP_APOS_H", "20")),
            retomada_1_min=float(e("RETOMADA_1_MIN", "30")),
            retomada_2_min=float(e("RETOMADA_2_MIN", "120")),
            responder_comentarios=e("RESPONDER_COMENTARIOS", "1").lower() in ("1", "true", "sim"),
            repostar_stories=e("REPOSTAR_STORIES", "0").lower() in ("1", "true", "sim"),
            max_reposts_hora=int(e("MAX_REPOSTS_HORA", "10")),
            dominio=e("DOMINIO", ""),
            fuso=e("FUSO", "America/Sao_Paulo"),
        )


def contas_da_config(cfg: "Config") -> frozenset:
    """Ids desta conta nos avisos da Meta: o do Instagram e o da página do Facebook.
    Vazio = aceita qualquer conta (instalação antiga, sem os ids no .env)."""
    return frozenset(i for i in (cfg.ig_user_id, cfg.ig_page_id) if i)


def _lista(valor: str) -> frozenset:
    return frozenset(v.strip().lstrip("@").lower() for v in valor.split(",") if v.strip())
