# Roteiro do curso: Agente de Instagram para vender perícia a advogados

Autor e professor: Edilson Aguiais. Público: peritos judiciais e assistentes técnicos,
alunos da Mentoria Águias da Perícia e do Águias ONE, que querem atender e vender os
próprios serviços pelo direct do Instagram, sem saber programar.

Cada módulo tem objetivo, o que mostrar, entrega do aluno e o erro mais comum.

---

## Módulo 1. Por que um agente no direct (15 min)
- **Objetivo:** entender o que o agente resolve e o que não resolve.
- **Mostrar:** `agente-perito testar` com o exemplo da Dra. Marina: advogado pergunta às 22h
  sobre impugnar um laudo e sai, na 3ª mensagem, com serviço, valor e próximo passo.
- **Pontos:** o advogado contrata quem responde primeiro e com clareza; post bom gera
  direct, e direct sem resposta em 24 h a Meta tranca; o agente qualifica e você só entra
  no trabalho técnico.
- **O que ele não é:** não prospecta, não faz o laudo, não promete resultado.
- **Entrega:** as 5 perguntas que advogados mais fazem no seu direct.
- **Erro comum:** achar que o agente gera seguidores. Ele converte quem já chega.

## Módulo 2. Conhecimento: o que você vende ao advogado (40 min)
- **Objetivo:** `servicos.md`, `tom_de_voz.md`, `icp.md`, `faq.md`, `objecoes.md` prontos.
- **Mostrar:** `/instalar-agente-instagram` no Claude Code, Etapa 1, com uma pasta de
  documentos de exemplo; o Claude preenche e o aluno aprova.
- **Pontos:** um serviço de entrada barato (consulta, análise prévia) com Pix; serviços
  maiores com faixa de valor e lista de documentos; ética (nomeado não vira assistente).
- **Entrega:** conhecimento sem nenhum `[COLCHETE]`.
- **Erro comum:** preço "a combinar". Sem valor ou faixa, o agente não fecha.

## Módulo 3. App da Meta (30 min)
- **Objetivo:** token de acesso e chave secreta do app em mãos.
- **Mostrar:** o `GUIA-META.md` tela por tela, com uma conta profissional de teste.
- **Entrega:** app criado e publicado (modo Ativo).
- **Erro comum:** conta pessoal em vez de profissional; app esquecido em desenvolvimento
  (só as contas de teste recebem resposta).

## Módulo 4. Instalação na VPS (30 min)
- **Objetivo:** agente no ar com HTTPS.
- **Mostrar:** VPS Ubuntu, `git clone`, `instalar.sh`, colar URL e token no painel da Meta,
  `agente-perito verificar` todo verde.
- **Entrega:** print do `verificar` verde.
- **Erro comum:** porta 80/443 fechada no firewall do provedor.

## Módulo 5. Testar como um advogado (30 min)
- **Objetivo:** aprovar o agente antes de abrir a todos.
- **Mostrar:** os 7 papéis da Etapa 4 da skill, com `SANDBOX` ligado.
- **Entrega:** as 7 conversas aprovadas; `SANDBOX` vazio.
- **Erro comum:** abrir a todos sem testar o caso "fui nomeado no processo".

## Módulo 6. Rotina e melhoria (15 min)
- **Objetivo:** o agente melhora toda semana.
- **Mostrar:** `agente-perito leads`, leitura de 5 conversas, ajuste em `faq.md`.
- **Entrega:** primeira rodada de ajuste feita.

---

**Mesmo conhecimento, dois canais.** O formato é o mesmo do `agente-whatsapp-perito`: o
aluno que já montou um copia a pasta `conhecimento/` e liga o outro.
