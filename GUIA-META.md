# Guia da Meta: criar o app e pegar as chaves

A única parte que não dá para automatizar. Leva uns 10 minutos e é feita uma vez.

## Antes de começar
- Sua conta do Instagram precisa ser **profissional**: no app do Instagram, vá em
  Configurações > Tipo de conta e ferramentas > Mudar para conta profissional.
- No app do Instagram: Configurações > Mensagens e respostas a stories > Controles de
  mensagens > **Ferramentas conectadas > Permitir acesso a mensagens: LIGADO**.

## 1. Criar o app
1. Acesse <https://developers.facebook.com/apps> e entre com seu Facebook.
2. Clique em **Criar app**.
3. Em caso de uso, escolha a opção de **gerenciar mensagens e conteúdo no Instagram**
   (o nome muda de vez em quando; é a que fala de Instagram). Se pedir o tipo de app,
   escolha **Empresa**.
4. Dê um nome (ex.: "Direct Maria Silva") e conclua.

## 2. Gerar o token e a chave secreta
1. No menu do app, abra **Instagram > Configuração da API com login do Instagram**.
2. Em **Gerar tokens de acesso**, clique em **Adicionar conta** e entre com o
   Instagram que o agente vai atender.
3. Clique em **Gerar token** ao lado da conta e copie. Esse é o **token de acesso**.
4. Na mesma tela, copie a **Chave secreta do app do Instagram**.

Guarde os dois para colar no instalador. Não mande para ninguém.

## 3. Webhook (o instalador te guia)
O comando `agente-perito conectar` mostra os dois valores para colar em
**Instagram > Configuração da API com login do Instagram > Configurar webhooks**:

- **URL de callback:** `https://SEU_DOMINIO/webhook`
- **Token de verificação:** o que o instalador mostrar

Clique em **Verificar e salvar** e ative os campos **messages** e **comments**.

## 4. Publicar o app
1. Em **Configurações do app > Básico**, preencha:
   - **URL da política de privacidade:** `https://SEU_DOMINIO/privacidade`
     (o agente já publica essa página para você)
   - **URL de exclusão de dados:** a mesma
   - categoria e ícone, se pedir
2. Mude o app para o modo **Ativo** (Live), no topo do painel.

## Preciso de aprovação da Meta (App Review)?
Para atender **a sua própria conta**, a Meta diz que o acesso padrão (Standard Access)
basta, sem App Review. É por isso que cada pessoa cria o próprio app: assim ninguém
precisa passar pela análise da Meta.

Se mesmo com o app publicado as mensagens de pessoas desconhecidas não chegarem
(só as das contas de teste), peça **acesso avançado** à permissão
`instagram_business_manage_messages` em **Análise do app**. A Meta pede verificação
da empresa e um vídeo curto do agente funcionando.

## Limites que a Meta impõe
- O agente só responde até **24 horas** depois da última mensagem do lead. Ele nunca
  começa conversa.
- Cada mensagem tem até 1000 caracteres (o agente quebra as maiores sozinho).
- Áudio e imagem chegam como aviso; o agente pede para a pessoa escrever.

## Caminho B: você já tem uma página do Facebook ligada ao Instagram

Se o seu Instagram está ligado a uma página do Facebook e você tem um app da Meta com
login do Facebook, dá para usar um **token de página** (começa com `EAA`). Vantagens:
não expira e o mesmo agente atende também o **Messenger** e os **comentários da página**.

1. No Explorador da Graph API (<https://developers.facebook.com/tools/explorer>), escolha
   o seu app, peça as permissões `instagram_basic`, `instagram_manage_messages`,
   `instagram_manage_comments`, `pages_messaging`, `pages_manage_metadata`,
   `pages_read_engagement` e `pages_show_list`, e gere o token de usuário.
2. Troque por token de longa duração e pegue o token da página em `GET /me/accounts`.
3. No instalador, cole esse token. A chave secreta é a do app (Configurações do app >
   Básico), não a do Instagram.
4. Em **Webhooks**, cadastre a URL de callback e o token de verificação duas vezes:
   no objeto **Instagram** (campos `messages` e `comments`) e no objeto **Page**
   (campos `messages` e `feed`). O `agente-perito conectar` inscreve a sua página.

Para atender pessoas que não têm papel no app, o app precisa estar no modo **Ativo** e,
em alguns casos, com acesso avançado às permissões de mensagem (Análise do app).
