"""LLM gratuito: Google Gemini (free tier) via REST. Troca de modelo automaticamente quando um estoura a cota."""
import os, re, json, time, httpx
BASE = "https://generativelanguage.googleapis.com/v1beta"
PREFERIDOS = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite",
              "gemini-3-flash-preview", "gemini-flash-latest", "gemini-flash-lite-latest"]
class RateLimit(Exception): pass
_models, _dead = None, {}   # lista de modelos utilizáveis; modelo -> timestamp até quando está sem cota

def _discover(key):
    r = httpx.get(f"{BASE}/models", params={"key": key, "pageSize": 200}, timeout=30); r.raise_for_status()
    ok = {m["name"].split("/")[-1] for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])}
    lst = [p for p in PREFERIDOS if p in ok]
    lst += sorted(m for m in ok if "flash" in m and not re.search(r"image|tts|live|audio|thinking|embedding", m) and m not in lst)
    if os.getenv("GEMINI_MODEL"): lst.insert(0, os.getenv("GEMINI_MODEL"))
    if not lst: raise RuntimeError(f"Nenhum modelo Gemini utilizável. Disponíveis: {sorted(ok)}")
    return lst

def ask(system, user, search=False, max_tokens=8192):
    global _models
    key = os.getenv("GEMINI_API_KEY")
    if not _models: _models = _discover(key)
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2}}
    if search: body["tools"] = [{"google_search": {}}]
    for rodada in range(2):
        for m in list(_models):
            if _dead.get((m, search), 0) > time.time(): continue
            for tent in range(2):
                r = httpx.post(f"{BASE}/models/{m}:generateContent", params={"key": key}, json=body, timeout=120)
                if r.status_code == 503 and tent == 0: time.sleep(4); continue
                break
            if r.status_code == 404:
                _models.remove(m); continue
            if r.status_code == 429:
                # "limit: 0" = esse modelo/ferramenta não tem cota grátis: descarta por 1 dia; senão, 70s
                _dead[(m, search)] = time.time() + (86400 if "limit: 0" in r.text else 70)
                print(f"[llm] {m} sem cota (search={search}); tentando outro modelo"); continue
            if r.status_code >= 400:
                print("[llm]", m, r.status_code, r.text[:200]); continue
            c = r.json().get("candidates") or []
            if c and c[0].get("content"): return "".join(p.get("text", "") for p in c[0]["content"]["parts"])
        if rodada == 0:  # todos sem cota: espera o mais próximo voltar (máx 60s) e tenta de novo
            pend = [t for (mm, s), t in _dead.items() if s == search and t > time.time() and t < time.time() + 120]
            if not pend: break
            time.sleep(min(60, max(1, min(pend) - time.time())))
    raise RateLimit("Cota gratuita do Gemini esgotada em todos os modelos disponíveis.")

def _extract(t):
    for b in re.findall(r"```(?:json)?\s*(.*?)```", t, re.S) + [t]:
        i = min([x for x in (b.find("{"), b.find("[")) if x >= 0], default=-1)
        if i < 0: continue
        try: return json.JSONDecoder().raw_decode(b[i:])[0]
        except Exception: pass
    return None

def ask_json(system, user, search=False):
    sys_ = system + "\nResponda SOMENTE com JSON válido dentro de ```json, sem texto antes ou depois."
    for tent in range(3):
        t = ask(sys_, user, search)
        r = _extract(t)
        if r is not None: return r
        print(f"[llm] resposta sem JSON (tentativa {tent+1}): {t[:150]!r}")
        if search and tent == 0: search = False  # grounding às vezes responde só em prosa: refaz sem ferramenta
    raise ValueError("O Gemini não devolveu JSON válido (veja o terminal do uvicorn).")