# Roteiro de Demonstracao — Comprador IA
> **Projeto desenvolvido para o Hackathon Digitaly 03 — "Guerra das IAs"**  
> **Tema:** Automacao Inteligente de Compras B2B com Agentes de IA

Este roteiro foi elaborado para apresentar todos os requisitos da solucao em menos de 3 minutos, garantindo pontuacao maxima na avaliacao tecnica e de produto.

---

## 1. Inicializacao Rapida

1. De um duplo clique no arquivo **`start.bat`** na raiz do projeto.
2. Dois terminais abrirao automaticamente:
   * **Backend:** `http://127.0.0.1:8000/docs` (FastAPI + SQLite + Agentes)
   * **Frontend:** `http://localhost:3000` (Kanban em Next.js)
3. Abra **`http://localhost:3000`** no seu navegador.

---

## 2. Como Validar os Requisitos da Missao

### Requisito 01 · Entrada da Necessidade (Texto Livre & Mal Escrito)
* **No Frontend:** No campo de texto superior, cole uma solicitacao informal como:
  ```text
  cabo de rede 10metros, Sao Carlos SP, em ate 7 dias de entrega
  ```
* **O que observar:** O agente **Interpretador** processa linguagem natural, separa medidas coladas (`10metros` -> quantidade: `10`, unidade: `"metros"`) e local de entrega sem exigir formularios rigidos.
* **Teste de Esclarecimento:** Se voce digitar algo vago como apenas `/cotar cabo para Sao Carlos`, o sistema identifica a ambiguidade e solicita mais especificacoes tecnicas antes de cotar.

---

### Requisito 02 · Orquestracao Multi-Agente & Agente de Audio Open-Source
* Clique no card recem-criado no Kanban para abrir o modal de detalhes e veja a secao **"Log dos agentes"**:
  1. **Interpretador:** Extrai produto, quantidades, prazo e localizacao.
  2. **Pesquisador:** Varre fornecedores reais e alternativas de mercado.
  3. **Cotador:** Prepara e despacha mensagens via canais de mensageria.
  4. **Audio Transcriber (faster-whisper):** Recebe notas de voz ou arquivos de audio dos fornecedores e transcreve em texto em tempo real (open-source CTranslate2 em CPU).
  5. **Parser:** Transforma respostas informais (texto ou audio transcrito) em dados estruturados.
  6. **Logistica:** Calcula distancias geodesicas reais e projeta prazos e fretes.
  7. **Comparador:** Realiza ranking ponderado de custo total e gera justificativa.

---

### Requisito 03 · Busca de Fornecedores (Web Real + Simulacao B2B)
* Na tabela de cotacoes do pedido, observe as tags visuais ao lado de cada fornecedor:
  * `[WEB REAL]`: Fornecedor real localizado na web com link de fonte e reputacao.
  * `[SIMULADO]`: Fornecedor plausivel e coerente gerado via fallback quando ha limites de cota da web, cumprindo rigorosamente a permissao do edital de apresentar simulacoes coerentes de mercado.

---

### Requisito 04 · Comparacao por Custo Total (Centro de Gravidade)
* O sistema nao escolhe apenas pelo menor preco unitario:
  * **Calculo:** Custo Total = (Preco Unitario x Quantidade) + Frete
  * **Destino:** A distancia entre a cidade do fornecedor e a cidade de entrega entra no calculo logistico (API OpenStreetMap / Haversine).
  * **Viabilidade:** Se o fornecedor exigir prazo maior que o limite solicitado (ex: 9 dias quando o limite era 7), a proposta e marcada como inviavel.

---

### Requisito 05 · Recomendacao com Criterios Visiveis
* No modal de cotacao, veja a caixa **"Por que"**:
  * O agente **Comparador** expoem em texto claro os motivos da escolha, citando os valores exatos, o custo total, os criterios de prazo e eventuais desclassificacoes de fornecedores inviaveis.

---

### Requisito 06 · Kanban de Compras
* O fluxo operacional e compreendido em menos de 3 segundos atraves das 4 colunas visuais:
  * **Solicitado** -> Pedidos recem-abertos ou aguardando detalhes adicionais.
  * **Cotando** -> Agentes pesquisando e contatando fornecedores.
  * **Comparando** -> Propostas coletadas, ranqueadas por custo total.
  * **Decidido** -> Compra finalizada e economia registrada.
* Polling em tempo real atualiza os cards automaticamente.

---

### Requisito 07 · Ligacao com o Mundo Exterior (Voz, Audio & Telegram)
* **Via Audio no Telegram ou Web:**
  * O fornecedor pode enviar um **audio de voz** (Telegram voice note `.ogg` ou upload de arquivo).
  * O agente **Audio Transcriber** (`faster-whisper`) intercepta o audio, transcreve em texto portugues e despacha imediatamente para o **Parser**.
* **Via Bot do Telegram:**
  * O fornecedor recebe a cotacao no Telegram com a referencia do pedido.
  * O fornecedor responde do jeito dele por texto ou voz (ex: *"preco 5 reais, frete 15 reais e entrego em 4 dias"*).
  * O **Parser** extrai preco, frete e prazo, cobrando automaticamente qualquer informacao pendente.

---

## 3. Conclusao da Demonstracao

1. No modal de um pedido em **Comparando**, clique no botao **"Decidir"** na melhor opcao recomendada.
2. O pedido transita para a coluna **Decidido** e o contador de economia no topo do painel e atualizado instantaneamente.
3. Clique em **"Concluir Entrega"** para registrar o pedido no **Historico de Compras**.
