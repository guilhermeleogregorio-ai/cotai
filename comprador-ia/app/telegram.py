import os, asyncio, httpx
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"
async def send(chat_id, text):
    if not TOKEN: return
    async with httpx.AsyncClient(timeout=30) as c:
        await c.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text})
def send_sync(chat_id, text):
    if not TOKEN or not chat_id: return
    try: httpx.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text[:3900]}, timeout=30)
    except Exception as e: print("[telegram]", e)
async def poll(on_message):
    if not TOKEN:
        print("[telegram] TELEGRAM_BOT_TOKEN ausente: canal desativado"); return
    offset = 0
    async with httpx.AsyncClient(timeout=60) as c:
        while True:
            try:
                r = (await c.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 50})).json()
                for u in r.get("result", []):
                    offset = u["update_id"] + 1
                    m = u.get("message")
                    if m and m.get("text"):
                        await on_message(str(m["chat"]["id"]), m["text"])
            except Exception as e:
                print("[telegram]", e); await asyncio.sleep(3)
