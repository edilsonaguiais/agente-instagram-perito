# Agente de Instagram do Perito

Kit exclusivo dos alunos da **Mentoria Águias da Perícia** e do **Águias ONE**.

Um agente de IA que atende o **direct do Instagram** do perito e vende **serviço pericial a
advogado**: assistência técnica, parecer prévio, cálculo, impugnação de laudo, consulta
técnica. Ele também cuida dos **comentários dos posts**, das **marcações em story** e do
**Messenger da página do Facebook**, com o seu jeito de escrever.

Em cada conversa ele:
1. **qualifica o caso** em no máximo 2 perguntas: quem é (advogado de que área, de que
   lado), o que precisa provar, em que fase está o processo e se há prazo correndo;
2. **oferece o serviço certo** na 3ª mensagem, com valor e próximo passo juntos;
3. **fecha ali mesmo**: serviço de preço fechado sai com página de pagamento e QR Code do
   Pix; serviço sob proposta sai com a lista de documentos e o caminho para enviar;
4. **respeita a ética do perito**: não promete resultado, não atende quem tem o perito
   nomeado no mesmo processo e não dá estratégia jurídica;
5. **assume a conversa**: nunca diz "aguarde que o perito te responde". Quando você
   precisa saber de algo (documento chegou, prazo curto, alerta ético), ele te avisa no
   Telegram e segue atendendo.

Usa a **API oficial da Meta** (sem senha, sem robô de navegador, sem risco de bloqueio)
e o **Claude** como cérebro, pela sua assinatura ou por chave de API. Cada perito instala
no próprio servidor, com o próprio app da Meta.

O conhecimento tem **o mesmo formato do agente de WhatsApp do perito**
(`agente-whatsapp-perito`): escreva `servicos.md`, `tom_de_voz.md` e `metodo_vendas.md`
uma vez e use nos dois agentes.

## O que ele faz

| Onde | O que acontece |
|---|---|
| Direct do Instagram | qualifica o caso, oferta o serviço, manda valor e pagamento, retoma quem sumiu |
| Comentário num post | responde em público (curto, sem preço) e, se a pessoa mostrou interesse, aborda no direct |
| Marcação em story | agradece e puxa conversa sobre o caso ou o trabalho da pessoa; pode repostar o story (opcional) |
| Messenger e comentários da página do Facebook | o mesmo atendimento, pelo mesmo agente |
| Quem não é cliente (colega, amigo, aluno com dúvida) | conversa natural, sem oferta e sem retomada de venda |

## O que você precisa

| Item | Onde conseguir | Custo aproximado |
|---|---|---|
| Instagram **profissional** (Empresa ou Criador) | App do Instagram > Configurações > Tipo de conta | grátis |
| App na Meta for Developers | <https://developers.facebook.com> (veja o [GUIA-META.md](GUIA-META.md)) | grátis |
| Claude: **assinatura** Pro/Max **ou** chave de API | <https://claude.ai> ou <https://console.anthropic.com> | assinatura que você já paga, ou por uso |
| Servidor Linux (Ubuntu ou Debian), 2 GB de RAM | Hostinger, Contabo, DigitalOcean, Hetzner… | ~US$ 5 a 10/mês |
| Domínio próprio (opcional) | sem domínio, o instalador usa um endereço grátis `*.sslip.io` | |
| Bot do Telegram (opcional, para avisos) | @BotFather no Telegram | grátis |

## Instalação

### 1. Prepare as chaves (no seu computador)

**Claude pela assinatura (recomendado):** instale o Claude Code
(<https://claude.com/claude-code>) e rode no terminal:

```bash
claude setup-token
```

Autorize no navegador e guarde o token que começa com `sk-ant-oat`. Ele vale um ano e
é da sua conta; não use o login do seu computador no servidor, porque um derruba o outro.
Prefere pagar por uso? Crie uma chave em console.anthropic.com > API Keys.

**Meta:** siga o [GUIA-META.md](GUIA-META.md). No fim você terá o **token de acesso**
e a **chave secreta do app**.

### 2. Instale no servidor

O repositório é privado: aceite o convite do GitHub que você recebeu por e-mail. Depois,
no servidor (por SSH), clone com o seu login do GitHub e rode o instalador:

```bash
sudo apt-get install -y git && sudo git clone https://github.com/edilsonaguiais/agente-instagram-perito.git /opt/agente-perito
```

```bash
sudo bash /opt/agente-perito/instalar.sh
```

Na hora do `git clone`, o GitHub pede usuário e senha: a senha é um **token**, criado em
GitHub > Settings > Developer settings > Personal access tokens (permissão de leitura de
repositório basta).

O instalador:
1. instala o Docker, se precisar;
2. prepara o agente em `/opt/agente-perito`;
3. pergunta as chaves (Claude, Instagram, Telegram) e **confere cada uma na hora**;
4. sobe o servidor com HTTPS automático;
5. mostra a URL e o token de verificação que você cola no painel da Meta.

### 3. Ensine o agente

Ele aprende com arquivos de texto na pasta `/opt/agente-perito/conhecimento/`:

| Arquivo | O que vai nele | Obrigatório |
|---|---|---|
| `servicos.md` | cada serviço: o que é, para quem, quando cabe, o que entrega, prazo, honorários, documentos | sim |
| `tom_de_voz.md` | como você escreve: tamanho das mensagens, saudações, fechos, o que você nunca diz | sim |
| `metodo_vendas.md` | como conduzir a venda a advogado: as 2 perguntas, a oferta, objeções | sim |
| `icp.md` | quem é o seu cliente ideal (área do direito, tipo de causa) | não |
| `faq.md` | perguntas que advogado faz sempre (prazo, honorários, sigilo, como funciona) | não |
| `objecoes.md` | "está caro", "vou falar com o cliente", "o juiz já nomeou perito"… | não |
| qualquer outro `.md` | entra no conhecimento como extra | não |

**Pagamento por Pix sem configurar nada:** no `servicos.md`, o serviço de preço fechado
leva a linha `- Pix: 350,00`. O agente cria sozinho a página
`https://SEU_DOMINIO/p/<nome-do-servico>` com valor e QR Code do Pix, e manda esse link
depois do sim. Precisa de `PIX_CHAVE`, `PIX_NOME` e `PIX_CIDADE` no `.env`.

Edite com `agente-perito editar servicos.md` (o agente reinicia sozinho). Para o tom de
voz tem atalho: junte de 20 a 50 textos seus num arquivo `conhecimento/textos.txt` e rode
`agente-perito gerar-tom textos.txt`.

Tem um exemplo completo em [`exemplos/perito-contabil-bancario/`](exemplos/perito-contabil-bancario)
(perita fictícia, Dra. Marina Exemplo): use como modelo e **troque serviços, valores e voz
pelos seus**.

> **Segurança dos links:** o agente só consegue enviar links que estão nesses arquivos e as
> páginas de pagamento dos seus serviços. Qualquer outro é bloqueado antes de sair.

### 4. Teste em sandbox e libere

No `.env`, deixe `SANDBOX=` com o @ de uma conta sua de teste (no Facebook, o nome do
perfil). O agente só atende quem está na lista.

```bash
agente-perito testar      # converse com o agente no terminal, sem Instagram
agente-perito verificar   # checklist: chaves, conhecimento, servidor, webhook
agente-perito logs        # acompanhe as conversas reais
```

Mande DMs e comentários da conta de teste. Leia as conversas e só esvazie o `SANDBOX`
quando assinaria todas as respostas.

## Comandos do dia a dia

| Comando | O que faz |
|---|---|
| `agente-perito logs` | mostra as conversas acontecendo |
| `agente-perito leads` | lista quem conversou (perfil, serviço, resumo) e grava `dados/leads.csv` |
| `agente-perito editar servicos.md` | muda serviço, valor ou documentos (reinicia sozinho) |
| `agente-perito verificar` | diz o que está funcionando e o que falta |
| `agente-perito configurar` | troca uma chave (o resto fica como está) |
| `agente-perito reiniciar` / `parar` | liga e desliga |
| `agente-perito atualizar` | puxa a versão nova do GitHub (`git pull`), mantendo configurações e conversas |

## Como o agente se comporta

- **Fala como você.** Mensagens curtas, sem markdown, e toda resposta termina numa pergunta
  que faz a conversa andar (a Meta só deixa responder até 24 h depois da última mensagem).
- **Vende rápido.** No máximo 2 perguntas de qualificação; a 3ª mensagem já é a oferta,
  com valor e próximo passo juntos. Advogado com pressa recebe a resposta na primeira.
- **Vende onde a pessoa está.** Fecha no próprio direct; não manda para o WhatsApp.
- **Respeita a ética.** Sem promessa de resultado; impedimento e suspeição viram alerta para
  você; honorário de perito nomeado não se negocia com a parte.
- **Assume sempre.** Nada de "aguarde, o perito te responde". Documento recebido, prazo
  curto ou pedido fora do catálogo: ele te avisa no Telegram e continua atendendo.
- **Rastreia a venda.** Links da Hotmart saem com `src` e `sck` no formato
  `direct_ig|<sua conta>|<id da conversa>|<serviço>`: a venda mostra de qual conversa veio.
- **Lembra de cada pessoa.** Histórico e ficha ficam gravados; se o advogado volta semanas
  depois com outro processo, ele retoma de onde parou.
- **Retoma quem sumiu, sem insistir.** Até 2 retomadas dentro das 24 h que a Meta
  permite: 30 min e 2 h depois da mensagem sem resposta, das 8h às 21h. Respondeu, zera.
- **Não inventa.** Só usa o que está nos arquivos de conhecimento.
- **Você assume quando quiser.** Respondeu pelo app? Ele sai daquela conversa por 24 h.
- **É honesto.** Se perguntarem se é robô, diz que é seu assistente.

## Configurações (arquivo `/opt/agente-perito/.env`)

| Variável | Para quê | Padrão |
|---|---|---|
| `SANDBOX` | fase de teste: só atende estes @ (ou nomes no Facebook), separados por vírgula | vazio (todos) |
| `BLOQUEADOS` | quem o agente nunca atende (família, sócios, equipe) | vazio |
| `RESPONDER_COMENTARIOS` | responde comentários e aborda no direct | `1` |
| `REPOSTAR_STORIES` | reposta o story de quem marcou você (sai **sem** o @ clicável: a API não faz o adesivo) | `0` |
| `MAX_REPOSTS_HORA` | teto de reposts por hora, para não lotar seus stories | `10` |
| `RETOMADA_1_MIN` / `RETOMADA_2_MIN` | minutos até a 1ª e a 2ª retomada | `30` / `120` |
| `MAX_MSGS_SESSAO` | teto de mensagens do agente por conversa em 24 h | `40` |
| `PAUSA_HUMANO_HORAS` | quanto tempo ele fica fora depois que você responde | `24` |
| `CLAUDE_MOTOR` | `assinatura` (token do `claude setup-token`) ou `api` (chave) | conforme o configurar |
| `ESFORCO` | `low` responde mais rápido, `high` pensa mais | `medium` |
| `MODELO` | modelo do Claude | `claude-opus-5-5` |
| `MODO_TESTE` | `1` = não envia nada à Meta, só mostra no log | `0` |
| `PIX_CHAVE` / `PIX_NOME` / `PIX_CIDADE` | chave Pix, nome do recebedor e cidade das páginas de venda | vazio |
| `ENCAMINHAR_WEBHOOK` | outra conta no mesmo app da Meta: URL do webhook do agente dela (veja abaixo) | vazio |

Depois de editar o `.env`, rode `agente-perito reiniciar`.

## Mesma máquina ou mesmo app de outro agente

**Mesma máquina.** Se as portas 80/443 já estão ocupadas (outro agente, um site), o
instalador sobe o agente sem o próprio Caddy (`COMPOSE_PROFILES=` no `.env`). Aí:
1. Ligue o agente à rede do proxy que já existe, num `docker-compose.override.yml`
   ao lado do `docker-compose.yml`:
   ```yaml
   services:
     perito:
       networks: [default, proxy]
   networks:
     proxy:
       external: true
       name: NOME_DA_REDE_DO_PROXY   # ex.: agente-direct_default
   ```
2. No proxy, acrescente um endereço próprio (no Caddy):
   `perito.SEU_DOMINIO { reverse_proxy perito:8000 }` e recarregue sem derrubar:
   `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`.

**Mesmo app da Meta.** Um app tem **uma** URL de webhook. Se as duas contas usam o
mesmo app, o agente que recebe os avisos repassa os da outra conta, intactos, com
`ENCAMINHAR_WEBHOOK=https://perito.SEU_DOMINIO/webhook` no `.env` dele. Cada agente só
atende a própria conta (`IG_USER_ID` e `IG_PAGE_ID`, gravados pelo `configurar`).

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `verificar` diz que o servidor não está no ar | domínio não aponta para o IP, ou portas 80/443 fechadas | confira o DNS e o firewall do provedor |
| Meta não aceita o webhook | token de verificação diferente | copie de novo o que o `conectar` mostrou |
| Mensagens das contas de teste chegam, de estranhos não | app em modo de desenvolvimento | publique o app (modo Ativo), veja o GUIA-META |
| Nada chega | acesso a mensagens desligado no app do Instagram | Configurações > Mensagens > Ferramentas conectadas > Permitir acesso |
| Comentários não chegam | campo `comments` não ativado no webhook | painel da Meta > Webhooks > Instagram > `comments` |
| Agente parou de responder um lead | o Claude falhou ou ele tentou mandar um link fora do conhecimento, e pediu para aguardar | responda pelo app; 24 h depois ele volta |
| Resposta da sua própria conta de teste vem misturada | a conta de teste tem resposta automática própria | desligue a resposta automática dela durante os testes |

## Para desenvolvedores

```bash
pip install -r requirements.txt pytest
python -m pytest -q
python -m agente_direct --help
```

Estrutura: `agente_direct/` (código), `modelos/conhecimento/` (modelo em branco),
`exemplos/` (conhecimento de exemplo),
`instalar.sh` (instalador), `docker-compose.yml` + `Caddyfile` (servidor com HTTPS).

## E o Zernio, ou outra ferramenta no meio?

Não precisa. O agente fala direto com a API oficial da Meta, de graça, pelo app que você
cria no passo 1. Ferramentas como o Zernio cobram mensalidade para fazer essa ponte e não
mudam o que o agente faz. Só valem a pena se você já paga uma delas por outro motivo.

## Licença

Uso exclusivo de alunos ativos da Mentoria Águias da Perícia e do Águias ONE. Veja o
[LICENSE](LICENSE).
