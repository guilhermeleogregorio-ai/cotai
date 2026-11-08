# Cota AI — Guerra das IAs / Hackathon Digitaly 03
Plataforma de compras e cotações com agentes de IA.

## Rodar
```bash
# Backend (FastAPI - porta 8000)
cd backend
# Se necessário, faça um ambiente virtual
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# ou python -m pip install -r requirements.txt
cp .env.example .env   # preencha as chaves
uvicorn app.main:app --reload
# ou python -m uvicorn app.main:app --reload

# Frontend (Next.js - porta 3000)
npm install
npm run dev
# ou: cd frontend && npm install && npm run dev
```
Abra http://localhost:3000 (Next.js) ou http://localhost:8000 (FastAPI). Crie o bot no @BotFather e ponha token/username no `.env`.

## Fluxo (cobre os 7 requisitos)
1. Entrada livre (mal escrita) → **Interpretador** estrutura o pedido.
2. **Pesquisador** (busca web real, só registra o que tem URL de fonte; preço ausente = null).
3. **Cotador**: envia pelo Telegram (fornecedor conhecido) ou gera link `t.me/bot?start=token` + link WhatsApp.
4. Fornecedor responde em texto livre → **Parser** vira dado estruturado (pede o que faltou).
5. **Logística**: frete/prazo ausentes estimados por distância (marcados "est.").
6. **Comparador**: custo total = preço×qtd + frete, prazo, viabilidade; justificativa visível.
7. **Kanban** (Solicitado → Cotando → Comparando → Decidido).
Extras: memória de fornecedores, negociação automática, economia gerada.
Fora do escopo: agente de voz full duplex.

## Custo zero
Gemini (free tier do AI Studio, com busca web via Google Search grounding), Telegram Bot API, OpenStreetMap/Nominatim e SQLite: nenhum exige pagamento. Respeite os limites diários do plano gratuito.
