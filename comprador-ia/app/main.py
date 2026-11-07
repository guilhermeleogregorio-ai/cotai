import asyncio, json
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import db, agents, telegram

app = FastAPI(title="Comprador IA")

@app.on_event("startup")
async def _s(): asyncio.create_task(telegram.poll(agents.on_telegram))

class New(BaseModel): text: str
class Reply(BaseModel): text: str
class Decide(BaseModel): quote_id: int

def full(r):
    r["item"] = json.loads(r["item"]) if r["item"] else None
    r["log"] = json.loads(r["log"]); r["ranking"] = json.loads(r["ranking"]) if r["ranking"] else None
    r["quotes"] = db.q("SELECT * FROM quotes WHERE request_id=?", (r["id"],))
    for qt in r["quotes"]:
        qt["invite"] = agents.invite_links(qt, r["item"]) if r["item"] and qt["status"] == "aguardando_contato" else None
    return r

@app.post("/api/requests")
async def create(b: New):
    rid = db.ex("INSERT INTO requests(raw) VALUES(?)", (b.text,))
    asyncio.create_task(agents.run(rid, b.text)); return {"id": rid}
@app.get("/api/requests")
def lst(): return [full(r) for r in db.q("SELECT * FROM requests ORDER BY id DESC")]
@app.post("/api/requests/{rid}/compare")
async def cmp(rid: int): await asyncio.to_thread(agents.compare, rid); return {"ok": True}
@app.post("/api/requests/{rid}/decide")
def dec(rid: int, b: Decide): agents.decide(rid, b.quote_id); return {"ok": True}
@app.post("/api/requests/{rid}/negotiate")
async def neg(rid: int): return {"enviadas": await agents.negotiate(rid)}
@app.post("/api/quotes/{qid}/reply")  # fallback: colar a resposta do fornecedor recebida em outro canal
async def rep(qid: int, b: Reply): await agents.ingest_reply(qid, b.text); return {"ok": True}
@app.get("/api/stats")
def stats():
    d = db.q("SELECT COUNT(*) n, COALESCE(SUM(savings),0) s FROM requests WHERE status='decidido'")[0]
    return {"decididas": d["n"], "economia_total": d["s"], "fornecedores": db.q("SELECT * FROM suppliers ORDER BY wins DESC LIMIT 10")}

app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/")
def index(): return FileResponse("static/index.html")
