import os, asyncio, httpx

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"

async def send(chat_id, text, reply_markup=None):
    if not TOKEN or not chat_id: return
    async with httpx.AsyncClient(timeout=30) as c:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        await c.post(f"{API}/sendMessage", json=payload)

def send_sync(chat_id, text, reply_markup=None):
    if not TOKEN or not chat_id: return
    try:
        payload = {"chat_id": chat_id, "text": text[:3900]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        httpx.post(f"{API}/sendMessage", json=payload, timeout=30)
    except Exception as e:
        print("[telegram]", e)

async def answer_callback(callback_query_id, text=None):
    if not TOKEN or not callback_query_id: return
    async with httpx.AsyncClient(timeout=30) as c:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        await c.post(f"{API}/answerCallbackQuery", json=payload)

async def edit_message(chat_id, message_id, text):
    if not TOKEN or not chat_id or not message_id: return
    async with httpx.AsyncClient(timeout=30) as c:
        await c.post(f"{API}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": text})

async def poll(on_message, on_callback=None):
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
                    cb = u.get("callback_query")
                    if cb and on_callback:
                        await on_callback(cb)
            except Exception as e:
                print("[telegram]", e); await asyncio.sleep(3)
