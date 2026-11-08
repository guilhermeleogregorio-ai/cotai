import asyncio, json
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import db, agents, telegram

app = FastAPI(title="Cota AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _s(): asyncio.create_task(telegram.poll(agents.on_telegram, agents.on_callback, agents.on_telegram_audio))

class New(BaseModel): text: str
class Reply(BaseModel): text: str
class Decide(BaseModel): quote_id: int

def full(r):
    r["item"] = json.loads(r["item"]) if r["item"] else None
    r["log"] = json.loads(r["log"]); r["ranking"] = json.loads(r["ranking"]) if r["ranking"] else None
    r["quotes"] = db.q("SELECT * FROM quotes WHERE request_id=?", (r["id"],))
    for qt in r["quotes"]:
        qt["invite"] = agents.invite_links(qt, r["item"]) if r["item"] and qt["status"] in ("aguardando_contato", "aguardando_confirmacao") else None
    return r

@app.post("/api/requests")
async def create(b: New):
    rid = db.ex("INSERT INTO requests(raw) VALUES(?)", (b.text,))
    asyncio.create_task(agents.run(rid, b.text)); return {"id": rid}
@app.get("/api/requests")
def lst(): return [full(r) for r in db.q("SELECT * FROM requests ORDER BY id DESC")]
@app.post("/api/requests/{rid}/clarify")
async def clarify(rid: int, b: Reply):
    r = db.q("SELECT * FROM requests WHERE id=?", (rid,))
    if not r: raise HTTPException(404, "Pedido não encontrado")
    req = r[0]
    novo_raw = f"{req['raw']} (especificação: {b.text.strip()})"
    db.ex("UPDATE requests SET raw=?, status='solicitado' WHERE id=?", (novo_raw, rid))
    db.log(rid, f"Comprador esclareceu via web: {b.text.strip()}")
    asyncio.create_task(agents.run(rid, novo_raw))
    return {"ok": True}

@app.post("/api/requests/{rid}/compare")
async def cmp(rid: int): await asyncio.to_thread(agents.compare, rid); return {"ok": True}
@app.post("/api/requests/{rid}/decide")
def dec(rid: int, b: Decide): agents.decide(rid, b.quote_id); return {"ok": True}
@app.post("/api/requests/{rid}/deliver")
def deliver(rid: int):
    r = db.q("SELECT * FROM requests WHERE id=?", (rid,))
    if not r: raise HTTPException(404, "Pedido não encontrado")
    db.ex("UPDATE requests SET status='entregue', delivered_at=CURRENT_TIMESTAMP WHERE id=?", (rid,))
    db.log(rid, "Entrega confirmada: produto marcado como entregue e arquivado no histórico de compras")
    return {"ok": True}
@app.post("/api/requests/{rid}/undeliver")
def undeliver(rid: int):
    r = db.q("SELECT * FROM requests WHERE id=?", (rid,))
    if not r: raise HTTPException(404, "Pedido não encontrado")
    db.ex("UPDATE requests SET status='decidido' WHERE id=?", (rid,))
    db.log(rid, "Entrega desfeita: produto retornado para a coluna Decidido do Kanban")
    return {"ok": True}
@app.get("/api/history")
def get_history():
    rows = db.q("SELECT * FROM requests WHERE status='entregue' ORDER BY COALESCE(delivered_at, created) DESC LIMIT 5")
    return [full(r) for r in rows]

@app.get("/api/suppliers/history")
def get_suppliers_history():
    # Critérios:
    # 1. Fornecedor utilizado em uma cotação.
    # 2. O item/processo avançou até a última etapa do Kanban (decidido ou entregue).
    # 3. Filtro: exibe apenas as cotações efetivamente aprovadas.
    reqs = db.q("SELECT * FROM requests WHERE status IN ('decidido', 'entregue') AND chosen_quote IS NOT NULL ORDER BY COALESCE(delivered_at, created) DESC")
    suppliers_dict = {}
    for r in reqs:
        r_full = full(r)
        chosen_qid = r["chosen_quote"]
        chosen_quote = next((q for q in r_full["quotes"] if q["id"] == chosen_qid), None)
        if not chosen_quote:
            continue
        supp_name = chosen_quote["supplier"]
        if supp_name not in suppliers_dict:
            supp_db = db.q("SELECT * FROM suppliers WHERE name=?", (supp_name,))
            city = supp_db[0]["city"] if supp_db and supp_db[0]["city"] else chosen_quote.get("city")
            suppliers_dict[supp_name] = {
                "name": supp_name,
                "city": city,
                "contact": chosen_quote.get("contact"),
                "url": chosen_quote.get("url"),
                "total_approved_quotes": 0,
                "total_spend": 0.0,
                "total_savings": 0.0,
                "approved_quotes": []
            }

        rk_item = next((k for k in (r_full["ranking"] or []) if k["id"] == chosen_qid), None)
        qtd = float((r_full["item"] or {}).get("quantidade") or 1)
        unit_p = chosen_quote.get("unit_price") or 0.0
        freight = chosen_quote.get("freight") or 0.0
        prod_total = chosen_quote.get("product_total")

        if rk_item and rk_item.get("total") is not None:
            total = rk_item["total"]
        elif prod_total is not None:
            total = prod_total + freight
        else:
            total = unit_p * qtd + freight

        savings = float(r_full.get("savings") or 0.0)

        suppliers_dict[supp_name]["total_approved_quotes"] += 1
        suppliers_dict[supp_name]["total_spend"] += round(total, 2)
        suppliers_dict[supp_name]["total_savings"] += round(savings, 2)
        suppliers_dict[supp_name]["approved_quotes"].append(r_full)

    return list(suppliers_dict.values())
@app.post("/api/requests/{rid}/negotiate")
async def neg(rid: int): return {"enviadas": await agents.negotiate(rid)}
@app.post("/api/quotes/{qid}/reply")  # fallback: colar a resposta do fornecedor recebida em outro canal
async def rep(qid: int, b: Reply): await agents.ingest_reply(qid, b.text); return {"ok": True}

@app.post("/api/quotes/{qid}/audio-reply")
async def audio_reply(qid: int, file: UploadFile = File(...)):
    """Recebe audio da proposta do fornecedor, transcreve com faster-whisper e alimenta o interpretador."""
    from . import audio_agent
    content = await file.read()
    if not content:
        raise HTTPException(400, "Arquivo de audio vazio")
    text = await asyncio.to_thread(audio_agent.transcribe_audio, content, file.filename or "audio.ogg")
    if not text:
        raise HTTPException(400, "Nao foi possivel transcrever conteudo do audio")
    
    qt = db.q("SELECT * FROM quotes WHERE id=?", (qid,))
    if not qt:
        raise HTTPException(404, "Cotacao nao encontrada")
    db.log(qt[0]["request_id"], f"Fornecedor {qt[0]['supplier']} enviou audio (transcricao: '{text}')")
    
    await agents.ingest_reply(qid, text)
    return {"ok": True, "transcription": text}

@app.post("/api/audio/transcribe")
async def transcribe_only(file: UploadFile = File(...)):
    """Endpoint utilitario para transcrever qualquer arquivo de audio usando faster-whisper."""
    from . import audio_agent
    content = await file.read()
    if not content:
        raise HTTPException(400, "Arquivo de audio vazio")
    text = await asyncio.to_thread(audio_agent.transcribe_audio, content, file.filename or "audio.ogg")
    return {"ok": True, "transcription": text}
@app.post("/api/quotes/{qid}/confirm")
async def confirm_q(qid: int): return {"ok": await agents.confirm_and_send(qid)}
@app.get("/api/stats")
def stats():
    d = db.q("SELECT COUNT(*) n, COALESCE(SUM(savings),0) s FROM requests WHERE status IN ('decidido', 'entregue')")[0]
    ent = db.q("SELECT COUNT(*) n FROM requests WHERE status='entregue'")[0]["n"]
    return {
        "decididas": d["n"],
        "economia_total": d["s"],
        "entregues": ent,
        "fornecedores": db.q("SELECT * FROM suppliers ORDER BY wins DESC LIMIT 10")
    }

@app.get("/")
def index():
    return {
        "app": "Cota AI API",
        "status": "online",
        "docs": "http://127.0.0.1:8000/docs",
        "frontend": "http://localhost:3000"
    }
