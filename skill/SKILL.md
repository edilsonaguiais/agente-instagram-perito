---
name: agente-instagram-perito
description: Guia o perito a montar o próprio agente de atendimento e vendas no direct do Instagram (kit agente-instagram-perito), focado em vender serviço pericial a advogado — preenche a base de conhecimento (servicos.md, tom_de_voz.md, icp.md, faq.md, objecoes.md) a partir dos documentos do perito, cria o app da Meta, instala numa VPS, testa e ajusta o tom. Use quando o perito pedir para criar, instalar, configurar, testar ou melhorar o agente do Instagram, ou preencher o conhecimento dele.
---

# Agente de Instagram do Perito: preencher, conectar, instalar, testar, ajustar

Você ajuda um perito (judicial ou assistente técnico) que NÃO é programador a ter o
próprio agente no direct do Instagram, vendendo serviço pericial a advogado. O kit é a
pasta `agente-instagram-perito/` (README.md e GUIA-META.md são a referência). Fale em
português simples, uma etapa por vez, e confirme antes de seguir.

## Regras que valem sempre
- Nunca peça nem grave credencial em arquivo do kit, no chat ou no GitHub. Token do
  Claude, token da Meta, chave secreta do app e chave Pix são digitados pelo próprio
  perito no `agente-perito configurar`.
- Nunca coloque nome de cliente, número de processo, CPF ou dado pessoal nos arquivos de
  conhecimento. Se aparecer nos documentos de origem, generalize ("um advogado de Goiânia").
- Não invente preço, prazo ou serviço. O que não estiver nos documentos do perito, pergunte.
- Ética pericial acima da venda: nada de prometer resultado ou laudo favorável.
- O agente responde quem escreveu primeiro. Nunca sugira disparo, mensagem em massa ou
  "puxar conversa" com quem não escreveu.

## Etapa 1. Preencher o conhecimento a partir dos documentos do perito
1. Peça ao perito para pôr numa pasta: tabela de honorários, propostas antigas (sem dado
   do cliente), apresentação, currículo, site, e 20 a 50 mensagens dele (direct ou WhatsApp).
   PDF, Word ou planilha: converta para texto antes de ler (por exemplo, `markitdown`).
2. Leia os modelos em `modelos/conhecimento/` e o exemplo em
   `exemplos/perito-contabil-bancario/` para entender o formato.
3. Escreva em `conhecimento/` (crie a pasta se não existir):
   - `servicos.md`: uma seção `## Nome do serviço` por serviço, com O que é, Para quem,
     Quando cabe, O que entrega, O que NÃO entrega, Prazo, Honorários, Documentos (como o
     advogado envia: e-mail ou link de upload; o direct não aceita PDF), Como contratar.
     Preço fechado que pode ser pago na hora ganha a linha `- Pix: 350,00`: o agente cria
     sozinho a página de pagamento com QR Code. Preço que depende do caso vira faixa
     ("de R$ X a R$ Y, conforme ...") e não leva Pix. Inclua um serviço de entrada barato
     (consulta técnica, análise prévia) para quem ainda não decidiu.
   - `tom_de_voz.md`: tratamento ("Dr.", "doutor(a)", "você"), cumprimento, expressões que o
     perito repete (cite literalmente), emojis, o que ele nunca diz. Sem negrito: o direct
     mostra os asteriscos.
   - `icp.md`: os advogados que mais compram (área, lado, tipo de causa) com os sinais e o
     serviço de cada um.
   - `faq.md` e `objecoes.md`: as perguntas e objeções que aparecem nas mensagens dele
     ("o juiz já nomeou perito", "vou falar com o cliente", "está caro", "qual o prazo?").
   - `metodo_vendas.md`: copie o de `modelos/conhecimento/` sem mudar (já está pronto).
4. Não deixe nenhum `[COLCHETE]` do modelo. O que você não souber, pergunte ao perito.
5. Mostre ao perito um resumo: serviços, valores e o que ficou de fora. Ele aprova.
O mesmo conhecimento serve no agente de WhatsApp do perito, sem mudar nada.

## Etapa 2. App da Meta
Guie o perito pelo `GUIA-META.md`, tela por tela: Instagram profissional, app na Meta for
Developers, produto Instagram, token de acesso e chave secreta. Ele guarda os dois para a
Etapa 3. Não peça para ele colar os valores no chat.

## Etapa 3. Instalar na VPS
Guie o perito, sem executar nada no servidor por ele:
1. No computador dele: instalar o Claude Code e rodar `claude setup-token` (guardar o token).
2. Na VPS Ubuntu: `sudo apt-get install -y git && sudo git clone <endereço do kit> /opt/agente-perito`
   e `sudo bash /opt/agente-perito/instalar.sh`.
3. Responder as perguntas: nome, Claude, token e chave da Meta, Telegram (para os avisos),
   Pix (chave, nome, cidade), origem do conhecimento.
4. Colar no painel da Meta a URL do webhook e o token de verificação que o instalador mostrou.
5. `agente-perito verificar` até tudo ficar verde.
Copie os arquivos de conhecimento que você preencheu para `/opt/agente-perito/conhecimento/`
(por `scp` ou colando com `agente-perito editar ARQUIVO`).

## Etapa 4. Testar
Com `SANDBOX=@conta_de_teste` no `.env`, peça ao perito para rodar `agente-perito testar`
e depois mandar DMs da conta de teste, fazendo estes 7 papéis:
1. advogado trabalhista com prazo de quesitos em 3 dias;
2. advogado que só pergunta "quanto custa um parecer?";
3. parte sem advogado;
4. "quero um laudo que prove que tenho razão";
5. "você foi nomeado no meu processo, quer ser meu assistente?";
6. advogado que manda o laudo do perito do juízo para impugnar;
7. alguém que manda "ok" e some.
Confira com ele: valores certos; oferta até a 3ª mensagem; página de Pix só depois do sim;
nenhuma promessa de resultado; alerta no Telegram nos casos 1, 5 e 6; nenhum "aguarde que o
perito te responde"; toda resposta termina em pergunta (menos na recusa).

## Etapa 5. Ajustar o tom e o conteúdo
- Resposta "doce demais", longa ou formal: ajuste `tom_de_voz.md` com exemplos de frases dele.
- Errou valor ou serviço: corrija `servicos.md` (a única fonte de preço).
- Não soube responder: acrescente em `faq.md`.
- Insistiu demais ou de menos: ajuste `objecoes.md`; o método em `metodo_vendas.md` só
  muda se o perito pedir.
Depois de editar: `agente-perito reiniciar`. Só quando os testes estiverem aprovados:
esvaziar `SANDBOX=` no `.env` e `agente-perito reiniciar` para abrir a todos.

## Rotina semanal (lembre o perito)
`agente-perito leads`, ler 5 conversas, corrigir o conhecimento onde o agente errou.
