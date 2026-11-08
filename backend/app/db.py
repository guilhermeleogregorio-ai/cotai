import sqlite3, json, threading, os
_lock = threading.Lock()
_c = sqlite3.connect(os.getenv("DB_PATH", "compras.db"), check_same_thread=False)
_c.row_factory = sqlite3.Row
_c.executescript("""
CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, raw TEXT, item TEXT, status TEXT DEFAULT 'solicitado',
  log TEXT DEFAULT '[]', reasoning TEXT, ranking TEXT, chosen_quote INTEGER, savings REAL, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY, request_id INTEGER, supplier TEXT, url TEXT, product TEXT, city TEXT,
  contact TEXT, token TEXT, chat_id TEXT, status TEXT DEFAULT 'pendente', unit_price REAL, freight REAL, freight_estimated INTEGER DEFAULT 0,
  lead_days INTEGER, available_qty REAL, conditions TEXT, raw_reply TEXT, source TEXT,
  product_total REAL, price_type TEXT, quoted_unit TEXT, quoted_qty REAL, clarification_needed TEXT);
CREATE TABLE IF NOT EXISTS suppliers(name TEXT PRIMARY KEY, chat_id TEXT, city TEXT, quotes INTEGER DEFAULT 0, wins INTEGER DEFAULT 0);
""")
try: _c.execute("ALTER TABLE requests ADD COLUMN buyer_chat TEXT"); _c.commit()
except sqlite3.OperationalError: pass
try: _c.execute("ALTER TABLE requests ADD COLUMN delivered_at TEXT"); _c.commit()
except sqlite3.OperationalError: pass
try: _c.execute("ALTER TABLE quotes ADD COLUMN product_total REAL"); _c.commit()
except sqlite3.OperationalError: pass
try: _c.execute("ALTER TABLE quotes ADD COLUMN price_type TEXT"); _c.commit()
except sqlite3.OperationalError: pass
try: _c.execute("ALTER TABLE quotes ADD COLUMN quoted_unit TEXT"); _c.commit()
except sqlite3.OperationalError: pass
try: _c.execute("ALTER TABLE quotes ADD COLUMN quoted_qty REAL"); _c.commit()
except sqlite3.OperationalError: pass
try: _c.execute("ALTER TABLE quotes ADD COLUMN clarification_needed TEXT"); _c.commit()
except sqlite3.OperationalError: pass
def q(sql, a=()):
    with _lock: return [dict(r) for r in _c.execute(sql, a).fetchall()]
def ex(sql, a=()):
    with _lock:
        cur = _c.execute(sql, a); _c.commit(); return cur.lastrowid
def log(rid, msg):
    r = q("SELECT log FROM requests WHERE id=?", (rid,))[0]
    l = json.loads(r["log"]); l.append(msg)
    ex("UPDATE requests SET log=? WHERE id=?", (json.dumps(l, ensure_ascii=False), rid))
