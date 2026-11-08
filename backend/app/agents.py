"""Agentes: Interpretador -> Pesquisador -> (Cotador via Telegram) -> Parser -> Logística -> Comparador."""
import os, json, math, secrets, asyncio, urllib.parse, httpx, re
from . import db, llm, telegram

BOT = os.getenv("TELEGRAM_BOT_USERNAME", "")
NUM = r"(?:\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[\.,]\d+)?)"

def normalize_unit(unit: str | None) -> str:
    """Padroniza unidades de medida para evitar inconsistências de interpretação."""
    if not unit:
        return "unidades"
    u = unit.strip().lower()
    if u in ("m", "metro", "metros", "mt", "mts"):
        return "metros"
    if u in ("kg", "quilo", "quilos", "kilo", "kilos", "quilograma", "quilogramas"):
        return "kg"
    if u in ("l", "lt", "lts", "litro", "litros"):
        return "litros"
    if u in ("un", "und", "unidade", "unidades", "peça", "peças", "peca", "pecas", "pc", "pcs", "item", "itens"):
        return "unidades"
    if u in ("rolo", "rolos", "bobina", "bobinas"):
        return "rolos"
    if u in ("cx", "cxs", "caixa", "caixas"):
        return "caixas"
    if u in ("pct", "pcts", "pacote", "pacotes"):
        return "pacotes"
    return u

def are_units_compatible(u1: str | None, u2: str | None) -> bool:
    """Verifica se duas unidades referem-se à mesma grandeza de medida."""
    if not u1 or not u2:
        return True
    return normalize_unit(u1) == normalize_unit(u2)

def parse_number_brl(s: str | None) -> float | None:
    """Converte representações numéricas comuns em pt-BR (ex: 1.500,50 / 1.500 / 1,875 / 1500) em float."""
    if s is None:
        return None
    try:
        s = str(s).strip().replace("R$", "").replace("reais", "").strip()
        if "." in s and "," in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        elif "." in s:
            parts = s.split(".")
            if len(parts) == 2 and len(parts[1]) == 3 and int(parts[0]) > 0:
                s = parts[0] + parts[1]
        return float(s)
    except Exception:
        return None

def deterministic_parse_reply(full_text: str, item: dict) -> dict:
    """Extrai informações estruturadas da resposta do fornecedor através de padrões textuais.
    Identifica de forma estrita se o preço é unitário, total ou ambíguo, impedindo
    que o sistema faça suposições indevidas sobre unidade monetária não qualificada."""
    text = full_text.strip()
    req_qty = float(item.get("quantidade") or 1)
    req_unit = normalize_unit(item.get("unidade"))

    # 1. Frete
    frete = None
    if re.search(r"\bfrete\s+(?:gr[áa]tis|zero|gratuito|incluso|sem\s+custo)\b", text, re.I):
        frete = 0.0
    else:
        # "100 de custo de transporte", "100 de frete", "100 de transporte"
        m_fr = re.search(f"({NUM})" + r"\s*(?:reais\s*)?(?:de\s+)(?:frete|custo\s+de\s+transporte|transporte)", text, re.I)
        if not m_fr:
            # "frete: 100", "frete de 100", "custo de transporte: 100", "transporte: 100"
            m_fr = re.search(r"(?:frete|custo\s+de\s+transporte|taxa\s+de\s+entrega|valor\s+do\s+transporte|transporte)\s*(?:de|:)?\s*(?:R?\$?\s*)?" + f"({NUM})", text, re.I)
        if m_fr:
            frete = parse_number_brl(m_fr.group(1))

    # 2. Prazo
    prazo = None
    m_pz = re.search(r"(?:prazo(?:\s+de\s+entrega)?|entrega(?:\s+em)?)\s*(?:de|:)?\s*(\d+)\s*dias?", text, re.I)
    if not m_pz:
        m_pz = re.search(r"(\d+)\s*dias?\b", text, re.I)
    if m_pz:
        try: prazo = int(m_pz.group(1))
        except Exception: pass

    # 3. Formato bare numbers sem palavras-chave: ex: "1500 100 5 dias" ou "1500\n100\n5 dias"
    bare_price = None
    m_bare = re.search(r"(?:^|[\r\n])\s*(?:R?\$?\s*)?(" + NUM + r")[\s,]+(?:R?\$?\s*)?(" + NUM + r")[\s,]+(\d+)\s*dias?", text, re.I)
    if m_bare:
        bare_price = parse_number_brl(m_bare.group(1))
        if frete is None:
            frete = parse_number_brl(m_bare.group(2))
        if prazo is None:
            try: prazo = int(m_bare.group(3))
            except Exception: pass

    # 4. Pacotes / unidades diferentes com conversão (ex: rolo de 100m, caixa com 50 unidades)
    conversao = None
    unidade_cotada = None
    m_pkg = re.search(r"(?:rolo|bobina)s?\s+de\s+(\d+(?:[\.,]\d+)?)\s*(m|metros?)", text, re.I)
    if m_pkg:
        unidade_cotada = "rolos"
        conversao = {"multiplicador": parse_number_brl(m_pkg.group(1)), "unidade_base": "metros"}
    else:
        m_cx = re.search(r"(?:caixa|pacote)s?\s+(?:com|de)\s+(\d+(?:[\.,]\d+)?)\s*([a-zA-Zá-úÁ-Ú]+)", text, re.I)
        if m_cx:
            unidade_cotada = "caixas"
            conversao = {"multiplicador": parse_number_brl(m_cx.group(1)), "unidade_base": normalize_unit(m_cx.group(2))}

    # 5. Preço e classificação (total vs unitario vs ambiguo)
    tipo_preco = None
    valor_produto = None
    precisa_esclarecer = False
    motivo_esclarecimento = None

    padroes_total = [
        r"(?:(?:preço|valor)\s+total|total\s*(?:de|do\s+cabo|do\s+pedido)?)\s*[:=]?\s*(?:R?\$?\s*)?(" + NUM + r")\b",
        r"(?:R?\$?\s*(" + NUM + r")\s*(?:pel[oa]s?\s+(?:\d+\s*(?:m|metros?|un|unidades?|peças?|kg)?\s*)?(?:cabo|produto|lote|tudo|pedido|mercad(?:oria)?)|no\s+total|total))\b",
        r"(?:faço|fecho|fica|deixo)\s+(?:em|por)?\s*(?:R?\$?\s*)?(" + NUM + r")\s*(?:pel[oa]s?\s+(?:\d+\s*(?:m|metros?|un|unidades?|peças?|kg)?\s*)?(?:cabo|produto|lote|tudo)|no\s+total|tudo)\b",
        r"R?\$?\s*(" + NUM + r")\s*pel[oa]s?\s+\d+\s*(?:m|metros?|un|unidades?|peças?|kg)\b"
    ]

    padroes_unitario = [
        r"(?:(?:preço|valor)\s+unit[áa]rio|unit[áa]rio)\s*[:=]?\s*(?:R?\$?\s*)?(" + NUM + r")\b",
        r"(?:R?\$?\s*)?(" + NUM + r")\s*(?:por|cada|/)\s*(metro|m\b|unidade|un\b|peça|pc\b|kg|quilo|litro|l\b|rolo|bobina|caixa|pacote)\b",
        r"(?:cada|por)\s*(metro|m\b|unidade|un\b|peça|pc\b|kg|quilo|litro|l\b|rolo|bobina|caixa|pacote)\s*(?:sai|custa|fica|por)?\s*[:=]?\s*(?:R?\$?\s*)?(" + NUM + r")\b",
        r"(?:R?\$?\s*)?(" + NUM + r")\s*(?:a\s+unidade|o\s+metro|o\s+quilo|o\s+litro|o\s+rolo)\b"
    ]

    for p in padroes_total:
        m = re.search(p, text, re.I)
        if m:
            tipo_preco = "total"
            valor_produto = parse_number_brl(m.group(1))
            break

    if not tipo_preco:
        for p in padroes_unitario:
            m = re.search(p, text, re.I)
            if m:
                tipo_preco = "unitario"
                if m.lastindex >= 2:
                    if p.startswith(r"(?:cada|por)"):
                        unidade_cotada = normalize_unit(m.group(1))
                        valor_produto = parse_number_brl(m.group(2))
                    else:
                        valor_produto = parse_number_brl(m.group(1))
                        unidade_cotada = normalize_unit(m.group(2))
                else:
                    valor_produto = parse_number_brl(m.group(1))
                break

    # Se ainda não detectou valor_produto, verificar bare_price ou candidatos
    if valor_produto is None and bare_price is not None:
        valor_produto = bare_price

    if valor_produto is None:
        candidatos = []
        for token in re.findall(r"R?\$?\s*(" + NUM + r")", text):
            val = parse_number_brl(token)
            if val is not None and val != frete and val != prazo:
                candidatos.append(val)
        if candidatos:
            valor_produto = candidatos[0]

    # Verificar se há confirmação de total vs unitário em mensagens subsequentes
    # Ex: "É o preço total pelos 800 metros" ou "É unitário"
    if valor_produto is not None:
        if re.search(r"\b(?:[eé]\s+(?:o\s+)?(?:preço\s+|valor\s+)?total|preço\s+total\s+pelos\s+\d+|[eé]\s+total\b|pelo\s+lote|pelos?\s+\d+\s*(?:m|metros?|un|unidades?|peças?|kg))\b", text, re.I):
            tipo_preco = "total"
            precisa_esclarecer = False
        elif re.search(r"\b(?:[eé]\s+(?:o\s+)?(?:preço\s+|valor\s+)?unit[áa]rio|[eé]\s+unit[áa]rio\b|por\s+(?:metro|m\b|unidade|un\b|peça|kg))\b", text, re.I):
            tipo_preco = "unitario"
            precisa_esclarecer = False

    # Se o tipo_preco ainda não foi definido, é AMBÍGUO!
    if valor_produto is not None and not tipo_preco:
        tipo_preco = "ambiguo"
        precisa_esclarecer = True
        motivo_esclarecimento = (
            f"Por favor, confirme se o valor de R$ {valor_produto:g} informado "
            f"refere-se ao preço total pelos {req_qty:g} {req_unit} ou ao preço unitário por {req_unit}."
        )

    # Menção de unidade diferente sem conversão (ex: caixa a R$ 350 cada caixa)
    if not unidade_cotada:
        m_u = re.search(r"\b(caixa|pacote|rolo|bobina)s?\b", text, re.I)
        if m_u:
            unidade_cotada = normalize_unit(m_u.group(1))

    if unidade_cotada and not are_units_compatible(req_unit, unidade_cotada) and not conversao:
        precisa_esclarecer = True
        motivo_esclarecimento = (
            f"A cotação foi informada em '{unidade_cotada}', mas o pedido é de {req_qty:g} {req_unit}. "
            f"Por favor, informe quantos {req_unit} estão contidos em cada {unidade_cotada} para calcularmos o valor total."
        )

    return {
        "valor_produto": valor_produto,
        "tipo_preco": tipo_preco,
        "unidade_cotada": unidade_cotada or req_unit,
        "quantidade_cotada": req_qty if tipo_preco == "total" else 1,
        "conversao_unidade": conversao,
        "frete": frete,
        "prazo_dias": prazo,
        "qtd_disponivel": None,
        "condicoes": None,
        "precisa_esclarecer": precisa_esclarecer,
        "motivo_esclarecimento": motivo_esclarecimento,
    }

def process_quote_data(item: dict, parsed: dict) -> dict:
    """Processa de forma determinística os dados da cotação.
    Diferencia claramente preço unitário de total, preserva conexão entre
    quantidade, unidade, valor e frete, e impede suposições sobre unidades monetárias."""
    req_qty = float(item.get("quantidade") or 1)
    req_unit = normalize_unit(item.get("unidade"))

    valor = parsed.get("valor_produto")
    tipo = (parsed.get("tipo_preco") or "").strip().lower()
    frete = float(parsed["frete"]) if parsed.get("frete") is not None else None
    prazo = int(parsed["prazo_dias"]) if parsed.get("prazo_dias") is not None else None
    qtd_disp = float(parsed["qtd_disponivel"]) if parsed.get("qtd_disponivel") is not None else None
    condicoes = parsed.get("condicoes")
    precisa_esclarecer = bool(parsed.get("precisa_esclarecer"))
    motivo = parsed.get("motivo_esclarecimento")
    unidade_cotada = normalize_unit(parsed.get("unidade_cotada") or req_unit)
    conversao = parsed.get("conversao_unidade")

    # 1. Se preço não foi informado
    if valor is None:
        return {
            "status": "respondida_parcial",
            "unit_price": None,
            "product_total": None,
            "freight": frete,
            "lead_days": prazo,
            "available_qty": qtd_disp,
            "conditions": condicoes,
            "price_type": None,
            "clarification_needed": "Preço não informado.",
            "quoted_unit": unidade_cotada,
            "quoted_qty": None,
        }

    # 2. Ambiguidade: Não foi especificado se é unitário ou total
    if tipo == "ambiguo" or tipo not in ("unitario", "total") or precisa_esclarecer:
        if not motivo:
            motivo = (
                f"Por favor, confirme se o valor de R$ {valor:g} informado "
                f"refere-se ao preço total pelos {req_qty:g} {req_unit} ou ao preço unitário por {req_unit}."
            )
        return {
            "status": "aguardando_esclarecimento",
            "unit_price": None,
            "product_total": None,
            "freight": frete,
            "lead_days": prazo,
            "available_qty": qtd_disp,
            "conditions": condicoes,
            "price_type": "ambiguo",
            "clarification_needed": motivo,
            "quoted_unit": unidade_cotada,
            "quoted_qty": parsed.get("quantidade_cotada"),
        }

    # 3. Tratamento de Unidades Diferentes com ou sem conversão
    if not are_units_compatible(req_unit, unidade_cotada):
        if conversao and conversao.get("multiplicador"):
            mult = float(conversao["multiplicador"])
            if mult <= 0: mult = 1.0
            pacotes = math.ceil(req_qty / mult)
            if tipo == "unitario":
                product_total = round(pacotes * valor, 2)
                unit_price = round(product_total / req_qty, 4)
            else:
                product_total = round(valor, 2)
                unit_price = round(product_total / req_qty, 4)
        else:
            # Unidade diferente sem informação do tamanho da embalagem: requer esclarecimento
            motivo = (
                f"A cotação foi informada em '{parsed.get('unidade_cotada')}', mas o pedido é de {req_qty:g} {req_unit}. "
                f"Por favor, informe quantos {req_unit} vêm em cada {parsed.get('unidade_cotada')}."
            )
            return {
                "status": "aguardando_esclarecimento",
                "unit_price": None,
                "product_total": None,
                "freight": frete,
                "lead_days": prazo,
                "available_qty": qtd_disp,
                "conditions": condicoes,
                "price_type": "unidade_incompativel",
                "clarification_needed": motivo,
                "quoted_unit": unidade_cotada,
                "quoted_qty": parsed.get("quantidade_cotada"),
            }
    else:
        # Unidades compatíveis
        if tipo == "total":
            product_total = round(float(valor), 2)
            unit_price = round(product_total / req_qty, 4)
        else:  # unitario
            unit_price = round(float(valor), 4)
            product_total = round(unit_price * req_qty, 2)

    status = "respondida" if (frete is not None and prazo is not None) else "respondida_parcial"

    return {
        "status": status,
        "unit_price": unit_price,
        "product_total": product_total,
        "freight": frete,
        "lead_days": prazo,
        "available_qty": qtd_disp,
        "conditions": condicoes,
        "price_type": tipo,
        "clarification_needed": None,
        "quoted_unit": unidade_cotada,
        "quoted_qty": parsed.get("quantidade_cotada") or req_qty,
    }

def interpret(rid, raw):
    item = llm.ask_json(
        "Você é o agente Interpretador de compras B2B. Extraia do pedido, mesmo mal escrito: "
        '{"produto","quantidade"(número),"unidade","especificacoes","cidade_destino","uf_destino","cep","prazo_max_dias"(número|null)}. '
        "Regras: se houver medida (ex: '10metros', '800m', '50kg', '20un'), o número é 'quantidade' e a medida é 'unidade' "
        "(não coloque metragem em 'especificacoes' exceto se já houver outra quantidade explícita). "
        "Padronize a unidade de medida (ex: 'metros', 'kg', 'unidades', 'litros', 'rolos', 'caixas'). "
        "Use null no que não foi informado; nunca invente.", raw)
    if item and item.get("unidade"):
        item["unidade"] = normalize_unit(item["unidade"])
    if item and item.get("quantidade") is not None:
        try: item["quantidade"] = float(item["quantidade"])
        except (ValueError, TypeError): pass
    db.ex("UPDATE requests SET item=?, status='cotando' WHERE id=?", (json.dumps(item, ensure_ascii=False), rid))
    qtd_log = f"{item.get('quantidade')} {item.get('unidade')}" if item.get('quantidade') else "qtd não informada"
    db.log(rid, f"Interpretador: {qtd_log} de {item.get('produto')} para {item.get('cidade_destino')}")
    return item

def web_fallback(item):
    """Plano B 100% grátis (sem cota de IA para busca): DuckDuckGo + leitura das páginas. Só extrai o que está no texto."""
    UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    qy = f"{item.get('produto')} {item.get('especificacoes') or ''} comprar preço"
    page = None
    ultimo_erro = None
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
    import html as H
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

def simulated_fallback(item):
    """Fallback quando busca web e alternativa falham: gera 3 fornecedores simulados e coerentes (conforme Requisito 03)."""
    try:
        res = llm.ask_json(
            "Você é o agente Pesquisador. A busca web não retornou resultados. Conforme o edital B2B, gere lista de 3 fornecedores SIMULADOS e realistas no Brasil para este produto. "
            'Retorne lista: [{"fornecedor","url","produto","preco_unitario"(número BRL realista),"cidade","contato"}]. '
            "Seja coerente com os preços de mercado para B2B.",
            json.dumps(item, ensure_ascii=False))
        if isinstance(res, dict): res = next((v for v in res.values() if isinstance(v, list)), [res])
        valid = [x for x in res if isinstance(x, dict) and x.get("fornecedor")]
        if valid: return valid
    except Exception:
        pass
    prod = item.get("produto") or "Produto"
    cid = item.get("cidade_destino") or "São Paulo"
    uf = item.get("uf_destino") or "SP"
    return [
        {"fornecedor": f"Distribuidora Regional {uf}", "url": f"https://simulacao.com.br/distribuidora-{uf.lower()}", "produto": prod, "preco_unitario": 28.50, "cidade": cid, "contato": f"@vendas_{uf.lower()}_bot"},
        {"fornecedor": "Mega Suprimentos B2B", "url": "https://simulacao.com.br/mega-suprimentos", "produto": prod, "preco_unitario": 26.90, "cidade": "Campinas", "contato": "+55 19 99999-1001"},
        {"fornecedor": "Lojas do Brasil Atacado", "url": "https://simulacao.com.br/lojas-brasil", "produto": prod, "preco_unitario": 31.00, "cidade": "São Paulo", "contato": "+55 11 98888-2002"},
    ]

def search(rid, item):
    known = [s["name"] for s in db.q("SELECT name FROM suppliers ORDER BY wins DESC, quotes DESC LIMIT 5")]
    res = []
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
        try:
            res = web_fallback(item)
        except Exception as e:
            db.log(rid, f"Pesquisador: busca alternativa falhou ({e})")
            res = []
    except Exception as e:
        db.log(rid, f"Pesquisador: busca web falhou ({e}), tentando alternativa")
        try:
            res = web_fallback(item)
        except Exception:
            res = []

    if isinstance(res, dict): res = next((v for v in res.values() if isinstance(v, list)), [res])
    res = [x for x in res if isinstance(x, dict) and x.get("fornecedor")]

    is_simulado = False
    if not res:
        db.log(rid, "Pesquisador: nenhum fornecedor na web; ativando fornecedores simulados (Requisito 03)")
        res = simulated_fallback(item)
        is_simulado = True

    for s in res:
        url = s.get("url") or f"https://simulacao.com.br/{urllib.parse.quote(s['fornecedor'])}"
        tok = secrets.token_urlsafe(8)
        hist = db.q("SELECT chat_id FROM suppliers WHERE name=?", (s["fornecedor"],))
        source_label = f"[Simulado] {url}" if is_simulado else url
        db.ex("INSERT INTO quotes(request_id,supplier,url,product,city,contact,token,chat_id,unit_price,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (rid, s["fornecedor"], url, s.get("produto"), s.get("cidade"), s.get("contato"), tok,
               hist[0]["chat_id"] if hist else None, s.get("preco_unitario"), source_label))
        db.ex("INSERT OR IGNORE INTO suppliers(name,city) VALUES(?,?)", (s["fornecedor"], s.get("cidade")))
    
    tipo_log = "simulados (Requisito 03)" if is_simulado else "na web (com fonte)"
    db.log(rid, f"Pesquisador: {len(res)} fornecedores registrados ({tipo_log})")

def request_text(item):
    qtd = f"{item.get('quantidade')} {item.get('unidade') or 'un'}" if item.get('quantidade') else "quantidade a definir"
    return (f"Olá! Preciso de cotação: {qtd} de {item.get('produto')}. "
            f"Specs: {item.get('especificacoes') or '-'}. Entrega em {item.get('cidade_destino')}/{item.get('uf_destino')} "
            f"{item.get('cep') or ''}. Pode informar preço (especificando claramente se o valor é unitário ou total para {qtd}), frete, prazo de entrega e quantidade disponível?")

def tg_prefill_link(contact, text):
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
            db.ex("UPDATE quotes SET status='aguardando_confirmacao' WHERE id=?", (qt["id"],))
        else:
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

HELP = ("👋 Sou o Cota AI.\n/cotar <o que precisa> - abre uma cotação\n/status - seus pedidos\n"
        "/comparar - ranking com o que já respondeu\n/decidir [n] - fecha com a opção n do ranking (padrão: 1ª)")

def _last(chat_id, status=None):
    sql, a = "SELECT * FROM requests WHERE buyer_chat=?", [chat_id]
    if status: sql += " AND status=?"; a.append(status)
    r = db.q(sql + " ORDER BY id DESC LIMIT 1", a)
    return r[0] if r else None

async def buyer_cmd(chat_id, text):
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
                    f"(prod. R$ {r.get('product_total', r['unit_price']):.2f}, unit. R$ {r['unit_price']:.2f}, frete R$ {r['freight']:.2f}{' est.' if r['freight_estimated'] else ''}, "
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
            f"💬 *Responda aqui com sua proposta* (informe se o preço é unitário ou total pelos produtos, frete e prazo de entrega)."
        )
        return await telegram.send(chat_id, prompt_reply)
    qs = db.q("SELECT * FROM quotes WHERE chat_id=? AND status IN ('enviada','respondida_parcial','aguardando_esclarecimento') ORDER BY id DESC", (chat_id,))
    if qs: await ingest_reply(qs[0]["id"], text)
    else: await telegram.send(chat_id, "Use /cotar para abrir uma cotação (/ajuda).")

async def on_telegram_audio(chat_id, file_id, filename="voice.ogg"):
    """
    Recebe mensagem de audio do Telegram (voz ou arquivo).
    Baixa os bytes, transcreve silenciosamente com o faster-whisper e
    repassa diretamente para a logica de negocio.
    """
    try:
        audio_bytes, fname = await telegram.download_file_bytes(file_id)
        if not audio_bytes:
            return

        from . import audio_agent
        text = await asyncio.to_thread(audio_agent.transcribe_audio, audio_bytes, fname or filename)
        if not text or not text.strip():
            return

        # Verifica se e resposta de fornecedor em cotacao ativa
        qs = db.q("SELECT * FROM quotes WHERE chat_id=? AND status IN ('enviada','respondida_parcial','aguardando_esclarecimento') ORDER BY id DESC", (chat_id,))
        if qs:
            qid = qs[0]["id"]
            db.log(qs[0]["request_id"], f"Fornecedor {qs[0]['supplier']} enviou audio: '{text}'")
            await ingest_reply(qid, text)
        else:
            # Comprador enviou audio com novo pedido de cotacao
            rid = db.ex("INSERT INTO requests(raw, buyer_chat) VALUES(?, ?)", (text, chat_id))
            db.log(rid, f"Pedido criado via audio no Telegram: '{text}'")
            asyncio.create_task(run(rid, text))
    except Exception as e:
        print("[telegram audio error]", e)

async def ingest_reply(qid, text):
    qt = db.q("SELECT * FROM quotes WHERE id=?", (qid,))[0]
    req = db.q("SELECT * FROM requests WHERE id=?", (qt["request_id"],))[0]
    item = json.loads(req["item"]) if req["item"] else {}
    prev = qt["raw_reply"] or ""
    full_text = (prev + "\n" + text).strip()

    d = None
    try:
        sys_prompt = (
            "Você é o agente Parser de cotações B2B. Sua função é analisar a mensagem do fornecedor e extrair os dados comerciais com extrema precisão.\n"
            f"Pedido original: Produto: {item.get('produto')}, Quantidade: {item.get('quantidade')}, Unidade: {item.get('unidade')}.\n\n"
            "REGRAS OBRIGATÓRIAS:\n"
            "1. TIPO DE PREÇO: identifique se o valor é 'unitario', 'total' ou 'ambiguo':\n"
            "   - 'unitario': somente se o fornecedor explicitou que é por unidade/metro (ex: 'R$ 2/m', 'preço unitário: 2', 'por metro', 'cada').\n"
            "   - 'total': somente se o fornecedor explicitou que é pelo total/lote/pedido (ex: 'R$ 1.500 pelo cabo', '1500 pelos 800m', 'total: 1500', '1500 no lote', 'fica 1500 tudo').\n"
            "   - 'ambiguo': se informou valor numérico sem qualificar se é total ou unitário (ex: '1500', 'preço: 1500', '1500 100 5 dias'). NUNCA suponha!\n"
            "2. PROIBIÇÃO DE SUPOSIÇÃO: NUNCA invente ou deduza uma unidade monetária ou de medida não especificada. Se não estiver claro, marque 'tipo_preco': 'ambiguo' e 'precisa_esclarecer': true.\n"
            "3. UNIDADE E CONVERSÃO: se cotou em unidade diferente (ex: rolo de 100m para pedido em metros), informe 'unidade_cotada' e 'conversao_unidade': {'multiplicador': 100, 'unidade_base': 'metros'}. Se não informou o tamanho do pacote, marque 'precisa_esclarecer': true.\n"
            "4. FRETE: número em BRL (0 se frete grátis, null se não informado).\n"
            "5. PRAZO: dias úteis/corridos como número inteiro (null se não informado).\n"
            "Retorne JSON no formato:\n"
            "{\"valor_produto\": número|null, \"tipo_preco\": \"unitario\"|\"total\"|\"ambiguo\"|null, "
            "\"unidade_cotada\": string|null, \"quantidade_cotada\": número|null, "
            "\"conversao_unidade\": {\"multiplicador\": número, \"unidade_base\": string}|null, "
            "\"frete\": número|null, \"prazo_dias\": número|null, \"qtd_disponivel\": número|null, "
            "\"condicoes\": string|null, \"precisa_esclarecer\": boolean, \"motivo_esclarecimento\": string|null}"
        )
        d = await asyncio.to_thread(llm.ask_json, sys_prompt, f"Histórico da resposta do fornecedor:\n{full_text}")
    except Exception as e:
        print(f"[ingest_reply] LLM parser exception: {e}")

    # Fallback determinístico caso o LLM falhe ou não qualifique campos essenciais
    if not d or not isinstance(d, dict) or (d.get("valor_produto") is None and d.get("frete") is None):
        det = deterministic_parse_reply(full_text, item)
        if not d or not isinstance(d, dict):
            d = det
        else:
            for k, v in det.items():
                if d.get(k) is None and v is not None:
                    d[k] = v

    calc = process_quote_data(item, d)

    db.ex("""UPDATE quotes SET unit_price=?, product_total=?, freight=COALESCE(?,freight), lead_days=COALESCE(?,lead_days),
             available_qty=COALESCE(?,available_qty), conditions=COALESCE(?,conditions), raw_reply=?,
             price_type=?, quoted_unit=?, quoted_qty=?, clarification_needed=?, status=? WHERE id=?""",
          (calc["unit_price"], calc["product_total"], calc["freight"], calc["lead_days"],
           calc["available_qty"], calc["conditions"], full_text,
           calc["price_type"], calc["quoted_unit"], calc["quoted_qty"], calc["clarification_needed"],
           calc["status"], qid))

    if calc["status"] == "aguardando_esclarecimento":
        db.log(qt["request_id"], f"Parser: cotação #{qid} ({qt['supplier']}) requer esclarecimento: {calc['clarification_needed']}")
        if qt["chat_id"]:
            await telegram.send(qt["chat_id"], f"Obrigado pelo retorno! Para registrarmos sua proposta corretamente:\n👉 {calc['clarification_needed']}")
        if req.get("buyer_chat"):
            await telegram.send(req["buyer_chat"], f"⚠️ Cotação de {qt['supplier']} precisa de esclarecimento ({calc['clarification_needed']}). Já solicitei ao fornecedor!")
    elif calc["status"] == "respondida_parcial":
        qt_atual = db.q("SELECT * FROM quotes WHERE id=?", (qid,))[0]
        faltando = []
        if qt_atual["unit_price"] is None and qt_atual["product_total"] is None: faltando.append("preço")
        if qt_atual["lead_days"] is None: faltando.append("prazo de entrega")
        if qt_atual["freight"] is None: faltando.append("frete")
        db.log(qt["request_id"], f"Parser: cotação #{qid} ({qt['supplier']}) respondida parcialmente (falta: {', '.join(faltando)})")
        if faltando and qt["chat_id"]:
            await telegram.send(qt["chat_id"], "Obrigado! Para completar sua cotação, ainda preciso de: " + ", ".join(faltando) + ".")
    else:
        db.ex("UPDATE quotes SET status='respondida' WHERE id=?", (qid,))
        db.log(qt["request_id"], f"Parser: proposta de {qt['supplier']} validada com sucesso ({calc['price_type']}: R$ {calc['product_total']:.2f} + frete R$ {calc['freight']:.2f})")
        if qt["chat_id"]:
            await telegram.send(qt["chat_id"], f"✅ Cotação registrada com sucesso (R$ {calc['product_total']:.2f} produtos + R$ {calc['freight']:.2f} frete, prazo {calc['lead_days']} dias). Obrigado!")

    open_ = db.q("SELECT 1 FROM quotes WHERE request_id=? AND status IN ('enviada','respondida_parcial','aguardando_esclarecimento')", (qt["request_id"],))
    if not open_:
        await asyncio.to_thread(compare, qt["request_id"])

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
    for qt in db.q("SELECT * FROM quotes WHERE request_id=? AND (unit_price IS NOT NULL OR product_total IS NOT NULL) AND status IN ('respondida', 'respondida_parcial')", (rid,)):
        qt = logistics(item, qt)
        if qt["freight"] is None: continue
        prod_total = qt["product_total"] if qt.get("product_total") is not None else round(qt["unit_price"] * qty, 2)
        if qt.get("unit_price") is None:
            qt["unit_price"] = round(prod_total / qty, 4)
        qt["product_total"] = prod_total
        qt["total"] = round(prod_total + qt["freight"], 2)
        qt["viavel"] = (qt["available_qty"] is None or qt["available_qty"] >= qty) and \
                       (not item.get("prazo_max_dias") or qt["lead_days"] is None or qt["lead_days"] <= item["prazo_max_dias"])
        rows.append(qt)
    rows.sort(key=lambda r: (not r["viavel"], r["total"]))
    if not rows:
        db.log(rid, "Comparador: nenhuma cotação completa ainda"); return
    slim = [{k: r[k] for k in ("id","supplier","unit_price","product_total","price_type","freight","freight_estimated","lead_days","available_qty","conditions","total","viavel","url") if k in r} for r in rows]
    why = llm.ask("Você é o agente Comparador. Explique em português, em até 8 linhas, qual fornecedor tem a melhor condição pelo CUSTO TOTAL "
                  "(preço total dos produtos + frete) e prazo, citando números, critérios usados, descartes (inviáveis) e o que é estimativa. Não invente dados.",
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
    if not sem_spec:
        return False
    palavras = produto.split()
    if produto in _GENERICOS:
        return True
    if len(palavras) <= 2 and palavras[0] in ("cabo", "fio") and palavras[-1] in ("eletrico", "elétrico", "flexivel", "flexível"):
        return True
    return False

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
