#!/usr/bin/env bash
# Instala o Agente Perito (direct do Instagram) numa VPS Linux (Ubuntu ou Debian).
# O repositório é privado: clone com o seu login do GitHub e rode
#
#   sudo bash /opt/agente-perito/instalar.sh
#
# Para atualizar depois:   agente-perito atualizar
set -euo pipefail

REPO="${AGENTE_REPO:-edilsonaguiais/agente-instagram-perito}"
RAMO="${AGENTE_RAMO:-main}"
SUBPASTA="${AGENTE_SUBPASTA-}"
PASTA="${AGENTE_PASTA:-/opt/agente-perito}"
COMANDO="${AGENTE_COMANDO:-agente-perito}"
# SUBPASTA vazia = o agente está na raiz do repositório
URL_INSTALADOR="https://raw.githubusercontent.com/$REPO/$RAMO/${SUBPASTA:+$SUBPASTA/}instalar.sh"
ATUALIZAR=0
[ "${1:-}" = "--atualizar" ] && ATUALIZAR=1

passo() { printf '\n\033[1m▶ %s\033[0m\n' "$1"; }
falha() { printf '\n\033[31m✖ %s\033[0m\n' "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || falha "Rode como administrador: curl -fsSL $URL_INSTALADOR | sudo bash"
[ "$(uname -s)" = "Linux" ] || falha "Este instalador é para servidores Linux (Ubuntu ou Debian)."

passo "1/5 Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || falha "O Docker Compose não está disponível. Instale o pacote docker-compose-plugin."
echo "Docker pronto."

passo "2/5 Baixando o agente"
# Rodando de dentro de um clone (repositório privado: git clone + sudo bash instalar.sh),
# usa a própria pasta; via curl | bash, baixa o repositório público.
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]:-/nao/existe}")" 2>/dev/null && pwd || true)"
if [ -n "$AQUI" ] && [ -f "$AQUI/docker-compose.yml" ]; then
  origem="$AQUI"
else
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$RAMO" | tar -xz -C "$tmp" \
    || falha "Não consegui baixar $REPO. Repositório privado? Clone com git e rode: sudo bash instalar.sh"
  if [ -z "$SUBPASTA" ]; then
    origem="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n1)"
  else
    origem="$(find "$tmp" -mindepth 2 -maxdepth 2 -type d -name "$SUBPASTA" | head -n1)"
  fi
fi
[ -n "$origem" ] && [ -f "$origem/docker-compose.yml" ] || falha "Não achei o agente no repositório $REPO ($RAMO)."
mkdir -p "$PASTA"
# .env, conhecimento/ e dados/ não vêm do repositório: suas configurações ficam intactas.
if [ "$(cd "$origem" && pwd)" != "$(cd "$PASTA" && pwd)" ]; then
  cp -a "$origem/." "$PASTA/"
fi
cd "$PASTA"
touch .env && chmod 600 .env
mkdir -p dados conhecimento
echo "Arquivos em $PASTA."

passo "3/5 Comando $COMANDO"
cat > "/usr/local/bin/$COMANDO" <<WRAPPER
#!/usr/bin/env bash
# Atalho para controlar o Agente Perito instalado em $PASTA.
set -e
cd "$PASTA"
rodando() { [ -n "\$(docker compose ps -q --status running perito 2>/dev/null)" ]; }
python_no_agente() {
  if rodando; then docker compose exec perito python -m agente_direct "\$@"
  else docker compose run --rm perito python -m agente_direct "\$@"; fi
}
case "\${1:-ajuda}" in
  logs)       docker compose logs -f --tail 100 perito ;;
  reiniciar)  docker compose up -d --force-recreate ;;
  parar)      docker compose down ;;
  atualizar)
    if [ -d "$PASTA/.git" ]; then git -C "$PASTA" pull --ff-only && sudo bash "$PASTA/instalar.sh" --atualizar
    else curl -fsSL "$URL_INSTALADOR" | sudo bash -s -- --atualizar; fi ;;
  editar)     \${EDITOR:-nano} "conhecimento/\${2:-servicos.md}" && docker compose restart perito && echo "Agente reiniciado com o conhecimento novo." ;;
  configurar) python_no_agente configurar && docker compose up -d --force-recreate ;;
  ajuda|-h|--help)
    cat <<'AJUDA'
$COMANDO configurar      pergunta e confere as chaves (Claude, Instagram, Telegram)
$COMANDO conectar        liga o webhook da Meta à sua conta
$COMANDO verificar       checklist do que está funcionando
$COMANDO testar          conversa com o agente no terminal
$COMANDO editar [arq]    edita conhecimento/servicos.md (ou tom_de_voz.md, metodo_vendas.md)
$COMANDO gerar-tom ARQ   rascunho do tom de voz a partir de conhecimento/ARQ
$COMANDO logs            acompanha as conversas em tempo real
$COMANDO leads           lista quem conversou e grava a planilha dados/leads.csv
$COMANDO reiniciar | parar | atualizar
AJUDA
    ;;
  *) python_no_agente "\$@" ;;
esac
WRAPPER
chmod +x "/usr/local/bin/$COMANDO"
echo "Pronto: digite $COMANDO para ver os comandos."

passo "4/5 Montando o agente"
# Portas 80/443 livres: o agente sobe com o próprio Caddy (HTTPS automático).
# Ocupadas por outro serviço (outro agente, um site): fica sem Caddy e o proxy que já
# existe passa a encaminhar o endereço dele (veja "Mesma máquina" no README).
if ! grep -q '^COMPOSE_PROFILES=' .env; then
  if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE ':(80|443)$'; then
    echo "COMPOSE_PROFILES=" >> .env
    echo "Portas 80/443 já em uso: o agente sobe sem Caddy (proxy compartilhado)."
  else
    echo "COMPOSE_PROFILES=caddy" >> .env
  fi
fi
docker compose build -q
if grep -q '^COMPOSE_PROFILES=caddy' .env && command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && echo "Firewall: portas 80 e 443 liberadas."
fi

if [ "$ATUALIZAR" = 1 ]; then
  docker compose up -d --force-recreate
  printf '\n✅ Atualizado. Suas configurações e conversas foram mantidas.\n'
  exit 0
fi

passo "5/5 Configuração"
"$COMANDO" configurar </dev/tty
docker compose up -d

dominio="$(grep -E '^DOMINIO=' .env | cut -d= -f2-)"
if [ -n "$dominio" ]; then
  printf 'Esperando o certificado HTTPS de %s ' "$dominio"
  for _ in $(seq 1 45); do
    curl -fsS -o /dev/null "https://$dominio/saude" 2>/dev/null && { echo " ok"; break; }
    printf '.'; sleep 2
  done
  echo
fi

"$COMANDO" conectar </dev/tty || true

cat <<FIM

✅ Instalação concluída.

Agora:
  1. Escreva seu conhecimento:   $COMANDO editar tom_de_voz.md
                                 $COMANDO editar servicos.md
                                 $COMANDO editar metodo_vendas.md
  2. Converse com o agente:      $COMANDO testar
  3. Confira tudo:               $COMANDO verificar
  4. Acompanhe as conversas:     $COMANDO logs
FIM
