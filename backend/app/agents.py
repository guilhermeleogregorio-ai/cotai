"""Agentes: Interpretador -> Pesquisador -> (Cotador via Telegram) -> Parser -> Logística -> Comparador."""
import os, json, math, secrets, asyncio, urllib.parse, httpx
from . import db, llm, telegram

BOT = os.getenv("TELEGRAM_BOT_USERNAME", "")

def interpret(rid, raw):
    item = llm.ask_json(
        "Você é o agente Interpretador de compras B2B. Extraia do pedido, mesmo mal escrito: "
        '{"produto","quantidade"(número),"unidade","especificacoes","cidade_destino","uf_destino","cep","prazo_max_dias"(número|null)}. '
        "Use null no que não foi informado; nunca invente.", raw)
    db.ex("UPDATE requests SET item=?, status='cotando' WHERE id=?", (json.dumps(item, ensure_ascii=False), rid))
    qtd_log = f"{item.get('quantidade')} {item.get('unidade')}" if item.get('quantidade') else "qtd não informada"
    db.log(rid, f"Interpretador: {qtd_log} de {item.get('produto')} para {item.get('cidade_destino')}")
    return item

def web_fallback(item):
    """Plano B 100% grátis (sem cota de IA para busca): DuckDuckGo + leitura das páginas. Só extrai o que está no texto."""
    import re, html as H
    UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    qy = f"{item.get('produto')} {item.get('especificacoes') or ''} comprar preço"
    page = None
    for _tentativa in range(3):
        try:
            page = httpx.post("https://html.duckduckgo.com/html/", data={"q": qy}, headers=UA, timeout=20, follow_redirects=True).text
            break
        except Exception as e:
            ultimo_erro = e
            if _tentativa < 2:
                import time; time.sleep(3)
    if page is None:
        raise RuntimeError(f"Busca alternativa (DuckDuckGo) falhou após 3 tentativas: {ultimo_erro}")
    urls, seen = [], set()
    for h in re.findall(r'class="result__a"[^>]*href="([^"]+)"', page):
        m = re.search(r"uddg=([^&]+)", h); u = urllib.parse.unquote(m.group(1)) if m else h
        d = urllib.parse.urlparse(u).netloc
        if u.startswith("http") and d not in seen: seen.add(d); urls.append(u)
    docs = []
    for u in urls[:6]:
        try:
            t = httpx.get(u, headers=UA, timeout=12, follow_redirects=True).text
            t = re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", " ", t)
            t = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", t)))
            docs.append({"url": u, "texto": t[:2000]})
        except Exception: pass
    if not docs: raise RuntimeError("Busca alternativa não retornou páginas")
    return llm.ask_json(
        "Você é o agente Pesquisador. Dos textos de páginas abaixo, extraia fornecedores que vendem o produto. Lista (até 5) de "
        '{"fornecedor","url"(a url da página dada),"produto","preco_unitario"(BRL, só se aparecer no texto, senão null),"cidade"(só se aparecer, senão null),"contato"(só se aparecer, senão null)}. '
        "NUNCA invente nada que não esteja no texto.", json.dumps({"pedido": item, "paginas": docs}, ensure_ascii=False))

def search(rid, item):
    known = [s["name"] for s in db.q("SELECT name FROM suppliers ORDER BY wins DESC, quotes DESC LIMIT 5")]
    try:
        res = llm.ask_json(
            "Você é o agente Pesquisador. Use a busca web para achar fornecedores REAIS que vendem o produto e entregam no Brasil. "
            "Retorne lista (até 5) de objetos: "
            '{"fornecedor","url"(página real onde viu o produto),"produto"(nome exato na página),"preco_unitario"(número em BRL só se estiver visível na página, senão null),'
            '"cidade"(da loja, se visível, senão null),"contato"(telefone/WhatsApp/e-mail/Telegram público, senão null)}. '
            f"NUNCA invente preço, URL ou contato. Fornecedores já conhecidos do histórico (prefira checar): {known}.",
            json.dumps(item, ensure_ascii=False), search=True)
    except llm.RateLimit:
        db.log(rid, "Pesquisador: busca do Gemini sem cota, usando busca alternativa (DuckDuckGo)")
        res = web_fallback(item)
    if isinstance(res, dict): res = next((v for v in res.values() if isinstance(v, list)), [res])
    res = [x for x in res if isinstance(x, dict)]
    for s in res:
        if not s.get("url"): continue
        tok = secrets.token_urlsafe(8)
        hist = db.q("SELECT chat_id FROM suppliers WHERE name=?", (s["fornecedor"],))
        db.ex("INSERT INTO quotes(request_id,supplier,url,product,city,contact,token,chat_id,unit_price,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (rid, s["fornecedor"], s["url"], s.get("produto"), s.get("cidade"), s.get("contato"), tok,
               hist[0]["chat_id"] if hist else None, s.get("preco_unitario"), s["url"]))
        db.ex("INSERT OR IGNORE INTO suppliers(name,city) VALUES(?,?)", (s["fornecedor"], s.get("cidade")))
    db.log(rid, f"Pesquisador: {len(res)} fornecedores encontrados na web (com fonte)")

def request_text(item):
    qtd = f"{item.get('quantidade')} {item.get('unidade') or 'un'}" if item.get('quantidade') else "quantidade a definir"
    return (f"Olá! Preciso de cotação: {qtd} de {item.get('produto')}. "
            f"Specs: {item.get('especificacoes') or '-'}. Entrega em {item.get('cidade_destino')}/{item.get('uf_destino')} "
            f"{item.get('cep') or ''}. Pode informar preço unitário, frete, prazo de entrega e quantidade disponível?")

def tg_prefill_link(contact, text):
    """Gera link do Telegram que deixa o texto digitado no campo de mensagem para confirmação manual."""
    encoded = urllib.parse.quote(text)
    c = (contact or "").strip()
    if c.startswith("@"):
        return f"https://t.me/{c.lstrip('@')}?text={encoded}"
    if "t.me/" in c:
        u = c.split("t.me/")[-1].split("?")[0].split("/")[0].strip()
        if u: return f"https://t.me/{u}?text={encoded}"
    return f"https://t.me/share/url?url=&text={encoded}"

def wa_link(contact, text):
    digits = "".join(ch for ch in (contact or "") if ch.isdigit())
    encoded = urllib.parse.quote(text)
    return f"https://wa.me/{digits}?text={encoded}" if len(digits) >= 10 else f"https://api.whatsapp.com/send?text={encoded}"

async def confirm_and_send(qid: int):
    """Envia a cotação diretamente ao fornecedor no Telegram após confirmação."""
    qt = db.q("SELECT * FROM quotes WHERE id=?", (qid,))
    if not qt: return False
    qt = qt[0]
    req = db.q("SELECT * FROM requests WHERE id=?", (qt["request_id"],))[0]
    item = json.loads(req["item"]) if req["item"] else {}
    txt = request_text(item) + f"\n(ref #{qt['id']})"
    if qt["chat_id"]:
        await telegram.send(qt["chat_id"], txt)
        db.ex("UPDATE quotes SET status='enviada' WHERE id=?", (qid,))
        db.log(qt["request_id"], f"Cotador: cotação #{qid} confirmada e enviada para {qt['supplier']}")
        if req["buyer_chat"]:
            await telegram.send(req["buyer_chat"], f"✅ Cotação #{qid} enviada para {qt['supplier']}.")
        return True
    return False

async def dispatch(rid, item):
    txt = request_text(item)
    req = db.q("SELECT buyer_chat FROM requests WHERE id=?", (rid,))
    buyer_chat = req[0]["buyer_chat"] if req else None

    for qt in db.q("SELECT * FROM quotes WHERE request_id=?", (rid,)):
        msg_with_ref = txt + f"\n(ref #{qt['id']})"
        if qt["chat_id"] and buyer_chat:
            # Fornecedor conhecido: pede confirmação interativa com botões ao comprador
            db.ex("UPDATE quotes SET status='aguardando_confirmacao' WHERE id=?", (qt["id"],))
            confirm_msg = (
                f"📋 Pedido #{rid} — Confirmação de Cotação\n"
                f"🏢 Fornecedor: {qt['supplier']}\n\n"
                f"Mensagem pronta:\n\"{txt}\"\n\n"
                f"Deseja enviar para este fornecedor?"
            )
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Confirmar e Enviar", "callback_data": f"confirm_quote:{qt['id']}"},
                        {"text": "❌ Cancelar", "callback_data": f"cancel_quote:{qt['id']}"}
                    ]
                ]
            }
            await telegram.send(buyer_chat, confirm_msg, reply_markup=keyboard)
        elif qt["chat_id"]:
            # Conhecido mas sem buyer_chat (criado via web): aguarda confirmação no Kanban
            db.ex("UPDATE quotes SET status='aguardando_confirmacao' WHERE id=?", (qt["id"],))
        else:
            # Novo fornecedor: aguarda contato com pre-fill
            db.ex("UPDATE quotes SET status='aguardando_contato' WHERE id=?", (qt["id"],))
            if buyer_chat:
                tg_url = tg_prefill_link(qt.get("contact"), msg_with_ref)
                wa_url = wa_link(qt.get("contact"), msg_with_ref)
                buttons = [{"text": f"💬 Telegram ({qt['supplier']})", "url": tg_url}]
                if wa_url:
                    buttons.append({"text": "🟢 WhatsApp", "url": wa_url})
                notice = (
                    f"🔍 Pedido #{rid} — Fornecedor encontrado: {qt['supplier']}\n"
                    f"Clique para abrir a mensagem digitada no chat e enviar com confirmação:"
                )
                await telegram.send(buyer_chat, notice, reply_markup={"inline_keyboard": [buttons]})

    db.log(rid, "Cotador: cotações preparadas (aguardando confirmação ou contato pelo comprador)")

def invite_links(qt, item):
    bot_link = f"https://t.me/{BOT}?start={qt['token']}" if BOT else None
    msg = request_text(item) + (f"\n(ref #{qt['id']})" if qt.get("id") else "")
    share_link = f"https://t.me/share/url?url={urllib.parse.quote(bot_link or '')}&text={urllib.parse.quote(msg)}"
    return {
        "telegram": bot_link or share_link,
        "telegram_share": share_link,
        "whatsapp": wa_link(qt.get("contact"), msg),
        "mensagem": msg,
        "can_confirm": bool(qt.get("chat_id") and qt.get("status") in ("aguardando_confirmacao", "aguardando_contato")),
    }

HELP = ("👋 Sou o Comprador IA.\n/cotar <o que precisa> - abre uma cotação\n/status - seus pedidos\n"
        "/comparar - ranking com o que já respondeu\n/decidir [n] - fecha com a opção n do ranking (padrão: 1ª)")

def _last(chat_id, status=None):
    sql, a = "SELECT * FROM requests WHERE buyer_chat=?", [chat_id]
    if status: sql += " AND status=?"; a.append(status)
    r = db.q(sql + " ORDER BY id DESC LIMIT 1", a)
    return r[0] if r else None

async def buyer_cmd(chat_id, text):
    """Comandos do COMPRADOR no Telegram. Retorna True se tratou a mensagem."""
    pend = _last(chat_id, "aguardando_esclarecimento")
    if pend and not text.startswith("/"):
        novo_raw = f"{pend['raw']} (especificação: {text.strip()})"
        db.ex("UPDATE requests SET raw=?, status='solicitado' WHERE id=?", (novo_raw, pend["id"]))
        db.log(pend["id"], f"Comprador esclareceu: {text.strip()}")
        asyncio.create_task(run(pend["id"], novo_raw))
        await telegram.send(chat_id, f"👍 Especificação recebida! Atualizei o pedido #{pend['id']} e os agentes estão pesquisando.")
        return True

    cmd = text.split(" ", 1)[0].split("@")[0].lower()
    arg = text.split(" ", 1)[1].strip() if " " in text else ""
    if cmd in ("/ajuda", "/help") or (cmd == "/start" and not arg):
        await telegram.send(chat_id, HELP); return True
    if cmd == "/cotar":
        if not arg:
            await telegram.send(chat_id, "Diga o que precisa. Ex: /cotar 800m de cabo flexível 2,5mm para Ribeirão Preto até dia 20"); return True
        rid = db.ex("INSERT INTO requests(raw, buyer_chat) VALUES(?,?)", (arg, chat_id))
        asyncio.create_task(run(rid, arg))
        await telegram.send(chat_id, f"✅ Pedido #{rid} recebido. Os agentes estão pesquisando; aviso quando houver ranking."); return True
    if cmd == "/status":
        rs = db.q("SELECT id, raw, status FROM requests WHERE buyer_chat=? ORDER BY id DESC LIMIT 5", (chat_id,))
        await telegram.send(chat_id, "\n".join(f"#{r['id']} [{r['status']}] {r['raw'][:50]}" for r in rs) or "Nenhum pedido. Use /cotar."); return True
    if cmd == "/comparar":
        r = _last(chat_id)
        if not r: await telegram.send(chat_id, "Nenhum pedido. Use /cotar.")
        else:
            await asyncio.to_thread(compare, r["id"])
            if not db.q("SELECT ranking FROM requests WHERE id=?", (r["id"],))[0]["ranking"]:
                await telegram.send(chat_id, f"Pedido #{r['id']}: ainda sem cotações completas.")
        return True
    if cmd == "/decidir":
        r = _last(chat_id, "comparando")
        rk = json.loads(r["ranking"]) if r and r["ranking"] else []
        n = int(arg) if arg.isdigit() else 1
        if not rk or not 1 <= n <= len(rk): await telegram.send(chat_id, "Nada para decidir ainda. Use /comparar.")
        elif not rk[n-1]["viavel"]: await telegram.send(chat_id, "Essa opção está inviável (prazo/quantidade). Escolha outra.")
        else: decide(r["id"], rk[n-1]["id"])
        return True
    return False

def notify_buyer(rid, rows, why):
    chat = db.q("SELECT buyer_chat FROM requests WHERE id=?", (rid,))[0]["buyer_chat"]
    if not chat: return
    ls = "\n".join(f"{i}. {'✅' if r['viavel'] else '❌'} {r['supplier']}: R$ {r['total']:.2f} "
                    f"(unit. R$ {r['unit_price']:.2f}, frete R$ {r['freight']:.2f}{' est.' if r['freight_estimated'] else ''}, "
                    f"{r['lead_days'] if r['lead_days'] is not None else '—'}d)" for i, r in enumerate(rows, 1))
    telegram.send_sync(chat, f"📊 Pedido #{rid}\n{ls}\n\n💡 {why}\n\nResponda /decidir (1ª opção) ou /decidir 2.")

async def on_callback(cb):
    data = cb.get("data", "")
    cb_id = cb.get("id")
    msg = cb.get("message") or {}
    chat_id = str(msg.get("chat", {}).get("id"))
    msg_id = msg.get("message_id")

    if data.startswith("confirm_quote:"):
        try:
            qid = int(data.split(":", 1)[1])
            await telegram.answer_callback(cb_id, "Enviando cotação...")
            ok = await confirm_and_send(qid)
            if ok:
                qt = db.q("SELECT supplier FROM quotes WHERE id=?", (qid,))
                supp = qt[0]["supplier"] if qt else ""
                await telegram.edit_message(chat_id, msg_id, f"✅ Cotação enviada com sucesso para {supp}!")
            else:
                await telegram.edit_message(chat_id, msg_id, "ℹ️ Não foi possível enviar via bot (chat não conectado). Use o link de compartilhamento.")
        except Exception as e:
            print("[callback error]", e)
            await telegram.answer_callback(cb_id, "Erro ao processar.")

    elif data.startswith("cancel_quote:"):
        try:
            qid = int(data.split(":", 1)[1])
            await telegram.answer_callback(cb_id, "Envio cancelado.")
            qt = db.q("SELECT supplier, request_id FROM quotes WHERE id=?", (qid,))
            if qt:
                supp = qt[0]["supplier"]
                db.ex("UPDATE quotes SET status='aguardando_contato' WHERE id=?", (qid,))
                db.log(qt[0]["request_id"], f"Cotador: envio da cotação #{qid} ({supp}) cancelado pelo comprador")
                await telegram.edit_message(chat_id, msg_id, f"❌ Envio da cotação para {supp} cancelado.")
        except Exception as e:
            print("[callback error]", e)
            await telegram.answer_callback(cb_id, "Erro ao cancelar.")

async def on_telegram(chat_id, text):
    if await buyer_cmd(chat_id, text): return
    if text.startswith("/start"):
        tok = text.split(" ", 1)[1].strip() if " " in text else ""
        qt = db.q("SELECT * FROM quotes WHERE token=?", (tok,))
        if not qt: return await telegram.send(chat_id, "Link inválido ou expirado.")
        qt = qt[0]
        db.ex("UPDATE quotes SET chat_id=?, status='enviada' WHERE id=?", (chat_id, qt["id"]))
        db.ex("UPDATE suppliers SET chat_id=? WHERE name=?", (chat_id, qt["supplier"]))
        item = json.loads(db.q("SELECT item FROM requests WHERE id=?", (qt["request_id"],))[0]["item"])
        prompt_reply = (
            f"📦 Cotação para *{qt['supplier']}*:\n"
            f"{request_text(item)}\n\n"
            f"💬 *Responda aqui com sua proposta* (informe preço unitário, frete e prazo de entrega)."
        )
        return await telegram.send(chat_id, prompt_reply)
    qs = db.q("SELECT * FROM quotes WHERE chat_id=? AND status IN ('enviada','respondida_parcial') ORDER BY id DESC", (chat_id,))
    if qs: await ingest_reply(qs[0]["id"], text)
    else: await telegram.send(chat_id, "Use /cotar para abrir uma cotação (/ajuda).")

async def ingest_reply(qid, text):
    qt = db.q("SELECT * FROM quotes WHERE id=?", (qid,))[0]
    req = db.q("SELECT * FROM requests WHERE id=?", (qt["request_id"],))[0]
    # Acumula histórico completo para o LLM ter contexto de todas as mensagens anteriores
    prev = qt["raw_reply"] or ""
    full_text = (prev + "\n" + text).strip()
    d = await asyncio.to_thread(llm.ask_json,
        "Você é o agente Parser. Converta a resposta livre do fornecedor em "
        '{"preco_unitario"(BRL número|null),"frete"(BRL número|null; 0 se disse frete grátis),"prazo_dias"(número|null),"qtd_disponivel"(número|null),"condicoes"(texto curto|null),"falta":[campos ausentes]}. Nunca invente.',
        f"Pedido: {req['item']}\nResposta completa do fornecedor até agora: {full_text}")
    db.ex("""UPDATE quotes SET unit_price=COALESCE(?,unit_price), freight=COALESCE(?,freight), lead_days=COALESCE(?,lead_days),
             available_qty=COALESCE(?,available_qty), conditions=COALESCE(?,conditions), raw_reply=? WHERE id=?""",
          (d.get("preco_unitario"), d.get("frete"), d.get("prazo_dias"), d.get("qtd_disponivel"), d.get("condicoes"),
           full_text, qid))
    # Verifica o que está REALMENTE faltando no banco (após COALESCE), não só na última mensagem
    qt_atual = db.q("SELECT * FROM quotes WHERE id=?", (qid,))[0]
    faltando = []
    if qt_atual["unit_price"] is None: faltando.append("preco unitario")
    if qt_atual["lead_days"]  is None: faltando.append("prazo dias")
    if qt_atual["freight"]    is None: faltando.append("frete")
    if faltando and qt["chat_id"]:
        db.ex("UPDATE quotes SET status='respondida_parcial' WHERE id=?", (qid,))
        await telegram.send(qt["chat_id"], "Obrigado! Ainda preciso de: " + ", ".join(faltando) + ".")
    else:
        db.ex("UPDATE quotes SET status='respondida' WHERE id=?", (qid,))
        if qt["chat_id"]: await telegram.send(qt["chat_id"], "Cotação registrada. Obrigado!")
        db.log(qt["request_id"], f"Parser: resposta de {qt['supplier']} convertida em cotação")
    open_ = db.q("SELECT 1 FROM quotes WHERE request_id=? AND status IN ('enviada','respondida_parcial')", (qt["request_id"],))
    if not open_: await asyncio.to_thread(compare, qt["request_id"])

# ---------- logística ----------
def _geo(place):
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/search", params={"q": place + ", Brasil", "format": "json", "limit": 1},
                      headers={"User-Agent": "comprador-ia/1.0"}, timeout=15).json()
        return float(r[0]["lat"]), float(r[0]["lon"])
    except Exception: return None
def _km(a, b):
    R = 6371; p = math.pi / 180
    x = math.sin((b[0]-a[0])*p/2)**2 + math.cos(a[0]*p)*math.cos(b[0]*p)*math.sin((b[1]-a[1])*p/2)**2
    return 2 * R * math.asin(math.sqrt(x))

def logistics(item, qt):
    """Preenche frete/prazo ausentes com estimativa por distância (marcada como estimada)."""
    if qt["freight"] is not None and qt["lead_days"] is not None: return qt
    o, d = qt["city"] and _geo(qt["city"]), _geo(f"{item.get('cidade_destino')}, {item.get('uf_destino') or ''}")
    if o and d:
        km = _km(o, d)
        if qt["freight"] is None:
            qt["freight"] = round(40 + 1.1 * km, 2); db.ex("UPDATE quotes SET freight=?, freight_estimated=1 WHERE id=?", (qt["freight"], qt["id"]))
        if qt["lead_days"] is None:
            qt["lead_days"] = 2 + int(km // 400); db.ex("UPDATE quotes SET lead_days=? WHERE id=?", (qt["lead_days"], qt["id"]))
    return qt

# ---------- comparação ----------
def compare(rid):
    req = db.q("SELECT * FROM requests WHERE id=?", (rid,))[0]; item = json.loads(req["item"])
    qty = float(item.get("quantidade") or 1)
    rows = []
    for qt in db.q("SELECT * FROM quotes WHERE request_id=? AND unit_price IS NOT NULL", (rid,)):
        qt = logistics(item, qt)
        if qt["freight"] is None: continue
        qt["total"] = round(qt["unit_price"] * qty + qt["freight"], 2)
        qt["viavel"] = (qt["available_qty"] is None or qt["available_qty"] >= qty) and \
                       (not item.get("prazo_max_dias") or qt["lead_days"] is None or qt["lead_days"] <= item["prazo_max_dias"])
        rows.append(qt)
    rows.sort(key=lambda r: (not r["viavel"], r["total"]))
    if not rows:
        db.log(rid, "Comparador: nenhuma cotação completa ainda"); return
    slim = [{k: r[k] for k in ("id","supplier","unit_price","freight","freight_estimated","lead_days","available_qty","conditions","total","viavel","url")} for r in rows]
    why = llm.ask("Você é o agente Comparador. Explique em português, em até 8 linhas, qual fornecedor tem a melhor condição pelo CUSTO TOTAL "
                  "(preço×qtd + frete) e prazo, citando números, critérios usados, descartes (inviáveis) e o que é estimativa. Não invente dados.",
                  f"Pedido: {json.dumps(item, ensure_ascii=False)}\nCotações (ordenadas): {json.dumps(slim, ensure_ascii=False)}")
    db.ex("UPDATE requests SET status='comparando', reasoning=?, ranking=? WHERE id=?", (why, json.dumps(slim, ensure_ascii=False), rid))
    db.log(rid, f"Comparador: {len(rows)} propostas ranqueadas por custo total")
    notify_buyer(rid, rows, why)

def decide(rid, qid):
    r = json.loads(db.q("SELECT ranking FROM requests WHERE id=?", (rid,))[0]["ranking"])
    ch = next(x for x in r if x["id"] == qid); worst = max((x["total"] for x in r if x["viavel"]), default=ch["total"])
    db.ex("UPDATE requests SET status='decidido', chosen_quote=?, savings=? WHERE id=?", (qid, round(worst - ch["total"], 2), rid))
    db.ex("UPDATE suppliers SET wins=wins+1 WHERE name=?", (ch["supplier"],))
    for x in r: db.ex("UPDATE suppliers SET quotes=quotes+1 WHERE name=?", (x["supplier"],))
    db.log(rid, f"Decisão: {ch['supplier']} · economia R$ {worst - ch['total']:.2f}")
    chat = db.q("SELECT buyer_chat FROM requests WHERE id=?", (rid,))[0]["buyer_chat"]
    if chat:
        qt = db.q("SELECT contact, url FROM quotes WHERE id=?", (qid,))[0]
        telegram.send_sync(chat, f"🏁 Pedido #{rid} fechado com {ch['supplier']}: R$ {ch['total']:.2f} "
                                 f"(economia R$ {worst - ch['total']:.2f}).\nContato: {qt['contact'] or qt['url']}")

async def negotiate(rid):
    """Volta aos fornecedores melhores que o 2º colocado com o melhor preço como contraproposta."""
    r = json.loads(db.q("SELECT ranking FROM requests WHERE id=?", (rid,))[0]["ranking"]); best = r[0]
    n = 0
    for x in r[1:]:
        qt = db.q("SELECT * FROM quotes WHERE id=?", (x["id"],))[0]
        if qt["chat_id"]:
            await telegram.send(qt["chat_id"], f"Temos uma proposta de R$ {best['total']:.2f} no total (preço+frete). Consegue melhorar sua condição?")
            db.ex("UPDATE quotes SET status='enviada' WHERE id=?", (qt["id"],)); n += 1
    db.log(rid, f"Negociação: contraproposta enviada a {n} fornecedores"); return n

# Produtos que exigem especificação técnica para cotação útil
_GENERICOS = {
    "cabo", "fio", "parafuso", "tubo", "cano", "chapa", "perfil", "barra",
    "tinta", "verniz", "cimento", "areia", "prego", "rebite", "bucha",
    "conector", "terminal", "fusivel", "disjuntor", "relé", "sensor",
    "bomba", "motor", "válvula", "filtro", "mangueira", "correia",
}

def _is_ambiguo(item: dict) -> bool:
    """Retorna True se produto for genérico demais e sem especificações."""
    produto = (item.get("produto") or "").lower().strip()
    sem_spec = not item.get("especificacoes")
    return sem_spec and any(g == produto or produto.startswith(g + " ") for g in _GENERICOS)

async def run(rid, raw):
    try:
        item = await asyncio.to_thread(interpret, rid, raw)
        if _is_ambiguo(item):
            db.ex("UPDATE requests SET status='aguardando_esclarecimento' WHERE id=?", (rid,))
            db.log(rid, f"Interpretador: pedido ambíguo para '{item.get('produto')}' — aguardando esclarecimento do comprador")
            chat = db.q("SELECT buyer_chat FROM requests WHERE id=?", (rid,))[0]["buyer_chat"]
            if chat:
                await telegram.send(chat,
                    f"🤔 Seu pedido de *{item.get('produto')}* está genérico demais para eu buscar fornecedores úteis.\n\n"
                    f"Por favor, complemente com mais detalhes (ex: bitola, amperagem, material, norma técnica).\n"
                    f"Responda aqui com as especificações que vou continuar!")
            return
        await asyncio.to_thread(search, rid, item)
        await dispatch(rid, item)
    except Exception as e:
        db.log(rid, f"Erro: {e}")