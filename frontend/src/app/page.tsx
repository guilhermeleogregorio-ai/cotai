"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";

interface QuoteInvite {
  telegram?: string;
  whatsapp?: string;
  telegram_bot?: string;
  mensagem?: string;
  can_confirm?: boolean;
}

interface Quote {
  id: number;
  request_id: number;
  supplier: string;
  url: string;
  product?: string;
  city?: string;
  contact?: string;
  token?: string;
  chat_id?: string;
  status: string;
  unit_price: number | null;
  freight: number | null;
  freight_estimated?: number | boolean;
  lead_days: number | null;
  available_qty?: number | null;
  conditions?: string | null;
  raw_reply?: string | null;
  source?: string | null;
  invite?: QuoteInvite | null;
}

interface RankingItem {
  id: number;
  supplier?: string;
  total?: number;
  unit_price?: number;
  freight?: number;
  lead_days?: number;
  viavel?: boolean;
  motivo?: string;
}

interface RequestItemData {
  produto?: string;
  quantidade?: number | string;
  unidade?: string;
  destino?: string;
  cidade_destino?: string | null;
  uf_destino?: string | null;
  cep?: string | null;
  prazo_dias?: number;
  prazo_max_dias?: number | null;
  especificacoes?: string | null;
}

interface RequestModel {
  id: number;
  raw: string;
  item: RequestItemData | null;
  status: string;
  log: string[];
  reasoning: string | null;
  ranking: RankingItem[] | null;
  chosen_quote?: number | null;
  savings?: number | null;
  created?: string;
  delivered_at?: string | null;
  quotes: Quote[];
}

interface StatsData {
  decididas: number;
  economia_total: number;
  entregues?: number;
}

const S = ["solicitado", "cotando", "comparando", "decidido"] as const;
const N: Record<string, string> = {
  solicitado: "Solicitado",
  cotando: "Cotando",
  comparando: "Comparando",
  decidido: "Decidido",
};

const brl = (v: number | string | null | undefined) =>
  v == null
    ? "—"
    : "R$ " +
      Number(v).toLocaleString("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });

const api = async (u: string, m = "GET", b?: unknown) => {
  const res = await fetch(u, {
    method: m,
    headers: { "Content-Type": "application/json" },
    body: b ? JSON.stringify(b) : undefined,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Erro ${res.status}: ${txt.slice(0, 200)}`);
  }
  return res.json();
};

function getLocation(item: RequestItemData | null | undefined): string | null {
  if (!item) return null;
  const parts: string[] = [];
  if (item.cidade_destino) parts.push(item.cidade_destino);
  if (item.uf_destino) parts.push(item.uf_destino);
  if (parts.length > 0) return parts.join(" - ");
  if (item.destino) return item.destino;
  if (item.cep) return `CEP: ${item.cep}`;
  return null;
}

function getQuantity(item: RequestItemData | null | undefined): string {
  if (!item || item.quantidade == null) return "Qtd não especificada";
  return `${item.quantidade} ${item.unidade || ""}`.trim();
}

function formatDateHeader(dateStr?: string | null): string {
  if (!dateStr) return "Data não informada";
  const clean = dateStr.includes("T") ? dateStr : dateStr.replace(" ", "T") + "Z";
  const d = new Date(clean);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);

  const today = new Date();
  const isToday =
    d.getUTCDate() === today.getUTCDate() &&
    d.getUTCMonth() === today.getUTCMonth() &&
    d.getUTCFullYear() === today.getUTCFullYear();

  const formatted = d.toLocaleDateString("pt-BR", {
    timeZone: "UTC",
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });

  return isToday ? `Hoje · ${formatted}` : formatted;
}

function formatTime(dateStr?: string | null): string {
  if (!dateStr) return "";
  const clean = dateStr.includes("T") ? dateStr : dateStr.replace(" ", "T") + "Z";
  const d = new Date(clean);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export default function Home() {
  const [data, setData] = useState<RequestModel[]>([]);
  const [history, setHistory] = useState<RequestModel[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [newText, setNewText] = useState("");
  const [clarifyText, setClarifyText] = useState("");
  const [replyTexts, setReplyTexts] = useState<Record<number, string>>({});
  const dialogRef = useRef<HTMLDialogElement>(null);

  const loadData = useCallback(async () => {
    try {
      const [reqs, st, hist] = await Promise.all([
        api("/api/requests"),
        api("/api/stats"),
        api("/api/history"),
      ]);
      setData(Array.isArray(reqs) ? reqs : []);
      setStats(st);
      setHistory(Array.isArray(hist) ? hist : []);
    } catch (err) {
      console.error("Erro ao carregar dados:", err);
    }
  }, []);

  useEffect(() => {
    let ignore = false;

    async function initialFetch() {
      try {
        const [reqs, st, hist] = await Promise.all([
          api("/api/requests"),
          api("/api/stats"),
          api("/api/history"),
        ]);
        if (!ignore) {
          setData(Array.isArray(reqs) ? reqs : []);
          setStats(st);
          setHistory(Array.isArray(hist) ? hist : []);
        }
      } catch (err) {
        console.error("Erro ao carregar dados:", err);
      }
    }

    void initialFetch();

    const interval = setInterval(() => {
      void initialFetch();
    }, 3000);

    return () => {
      ignore = true;
      clearInterval(interval);
    };
  }, []);

  const show = (id: number) => {
    setOpenId(id);
  };

  useEffect(() => {
    if (openId !== null && dialogRef.current && !dialogRef.current.open) {
      dialogRef.current.showModal();
    }
  }, [openId]);

  const closeDialog = () => {
    if (dialogRef.current && dialogRef.current.open) {
      dialogRef.current.close();
    }
    setOpenId(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newText.trim();
    if (!trimmed) return;
    try {
      await api("/api/requests", "POST", { text: trimmed });
      setNewText("");
      await loadData();
    } catch (err) {
      console.error("Erro ao criar cotação:", err);
    }
  };

  const dec = async (rid: number, qid: number) => {
    try {
      await api(`/api/requests/${rid}/decide`, "POST", { quote_id: qid });
      await loadData();
    } catch (err) {
      console.error("Erro ao decidir:", err);
    }
  };

  const handleDeliver = async (rid: number) => {
    try {
      await api(`/api/requests/${rid}/deliver`, "POST");
      await loadData();
    } catch (err) {
      console.error("Erro ao marcar como entregue:", err);
      alert("Não foi possível marcar como entregue.");
    }
  };

  const handleUndeliver = async (rid: number) => {
    try {
      await api(`/api/requests/${rid}/undeliver`, "POST");
      await loadData();
    } catch (err) {
      console.error("Erro ao desfazer entrega:", err);
      alert("Não foi possível desfazer a entrega.");
    }
  };

  const cmp = async (rid: number) => {
    try {
      await api(`/api/requests/${rid}/compare`, "POST");
      await loadData();
    } catch (err) {
      console.error("Erro ao comparar:", err);
    }
  };

  const neg = async (rid: number) => {
    try {
      const x = await api(`/api/requests/${rid}/negotiate`, "POST");
      alert((x.enviadas ?? 0) + " fornecedores contatados");
    } catch (err) {
      console.error("Erro ao negociar:", err);
    }
  };

  const cfm = async (qid: number) => {
    try {
      const res = await api(`/api/quotes/${qid}/confirm`, "POST");
      if (res.ok) {
        alert("Cotação enviada com sucesso ao fornecedor!");
      } else {
        alert("Não foi possível enviar via bot (chat não conectado). Use o link de compartilhamento.");
      }
      await loadData();
    } catch (err) {
      console.error("Erro ao confirmar envio:", err);
    }
  };

  const rep = async (qid: number) => {
    try {
      const text = replyTexts[qid] || "";
      await api(`/api/quotes/${qid}/reply`, "POST", { text });
      setReplyTexts((prev) => ({ ...prev, [qid]: "" }));
      await loadData();
    } catch (err) {
      console.error("Erro ao enviar resposta:", err);
    }
  };

  const handleClarify = async (rid: number) => {
    const trimmed = clarifyText.trim();
    if (!trimmed) return;
    try {
      await api(`/api/requests/${rid}/clarify`, "POST", { text: trimmed });
      setClarifyText("");
      await loadData();
    } catch (err) {
      console.error("Erro ao enviar esclarecimento:", err);
    }
  };

  const openRequest =
    openId !== null
      ? data.find((x) => x.id === openId) || history.find((x) => x.id === openId)
      : null;
  const rk = openRequest?.ranking || [];

  // Assegurar exatamente até 5 cotações no histórico
  const last5History = history.slice(0, 5);

  // Agrupar itens do histórico por data (YYYY-MM-DD)
  const groupedHistory: { dateKey: string; items: RequestModel[] }[] = [];
  for (const item of last5History) {
    const dStr = item.delivered_at || item.created || "";
    const dateKey = dStr.slice(0, 10) || "outros";
    let grp = groupedHistory.find((g) => g.dateKey === dateKey);
    if (!grp) {
      grp = { dateKey, items: [] };
      groupedHistory.push(grp);
    }
    grp.items.push(item);
  }

  return (
    <>
      <header>
        <h1>Comprador IA</h1>
        <span className="stat" id="st">
          {stats ? (
            <>
              {stats.decididas} decididas
              {stats.entregues ? ` · ${stats.entregues} entregues` : ""} · economia{" "}
              <b>{brl(stats.economia_total)}</b>
            </>
          ) : null}
        </span>
      </header>

      <form id="f" onSubmit={handleSubmit}>
        <textarea
          id="t"
          rows={2}
          placeholder="Ex: preciso de 800m de cabo flexivel 2,5mm pra entregar em Ribeirão Preto ate dia 20"
          value={newText}
          onChange={(e) => setNewText(e.target.value)}
        />
        <button type="submit">Cotar</button>
      </form>

      {/* Kanban Board */}
      <div className="cols" id="cols">
        {S.map((c) => {
          const colData = data.filter((r) =>
            c === "solicitado"
              ? r.status === "solicitado" || r.status === "aguardando_esclarecimento"
              : r.status === c
          );
          return (
            <div className="col" key={c}>
              <h3>
                {N[c]} ({colData.length})
              </h3>
              {colData.map((r) => {
                const responded = (r.quotes || []).filter((q) =>
                  q.status.startsWith("respondida")
                ).length;
                const totalQuotes = (r.quotes || []).length;
                const lastLog =
                  r.log && r.log.length > 0 ? r.log[r.log.length - 1] : "na fila";

                return (
                  <div className="card" key={r.id} onClick={() => show(r.id)}>
                    <b>
                      {r.item
                        ? `${r.item.produto}${r.item.quantidade != null ? ` · ${r.item.quantidade}${r.item.unidade || ""}` : ""}`
                        : r.raw.slice(0, 50)}
                    </b>
                    {r.status === "aguardando_esclarecimento" ? (
                      <small style={{ color: "#f59e0b", fontWeight: "bold" }}>
                        ⚠️ Precisa de detalhes
                      </small>
                    ) : (
                      <small>
                        {responded}/{totalQuotes} cotações
                      </small>
                    )}
                    <small>{lastLog}</small>

                    {/* Botão "Entregue" para produtos na aba Decidido */}
                    {c === "decidido" ? (
                      <div
                        style={{
                          marginTop: "10px",
                          display: "flex",
                          justifyContent: "flex-end",
                        }}
                      >
                        <button
                          type="button"
                          className="btn-entregue"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeliver(r.id);
                          }}
                          title="Marcar como entregue e mover para o histórico de compras"
                        >
                          ✓ Entregue
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      {/* Seção de Histórico de Compras - Botão na parte inferior à esquerda abaixo do Kanban */}
      <div className="history-section" id="historico">
        <div className="history-toolbar">
          <button
            type="button"
            className={`history-toggle-btn ${showHistory ? "active" : ""}`}
            onClick={() => setShowHistory((prev) => !prev)}
            title="Exibir ou recolher o Histórico de Compras"
          >
            <span className="history-icon">📦</span>
            <span>Histórico de Compras</span>
            <span className="history-badge">{last5History.length} / 5</span>
            <span className="history-arrow">
              {showHistory ? "▲ Recolher" : "▼ Expandir"}
            </span>
          </button>
        </div>

        {showHistory ? (
          <div className="history-content">
            <div className="history-header">
              <div>
                <h2>📦 Histórico de Compras</h2>
                <p className="history-subtitle">
                  Exibindo as últimas 5 cotações entregues · Produtos comprados, quantidades, locais e cotações separadas por data
                </p>
              </div>
            </div>

            {last5History.length === 0 ? (
              <div className="history-empty">
                <span style={{ fontSize: "32px" }}>📦</span>
                <p>Nenhuma compra entregue registrada no histórico ainda.</p>
                <small style={{ color: "var(--m)" }}>
                  Finalize uma cotação e clique no botão <b>&quot;✓ Entregue&quot;</b> na coluna <b>Decidido</b> do Kanban acima para arquivá-la aqui (armazenando até as últimas 5 cotações).
                </small>
              </div>
            ) : (
              groupedHistory.map((grp) => (
                <div className="history-date-group" key={grp.dateKey}>
                  <div className="history-date-header">
                    <span className="history-date-icon">📅</span>
                    <span>
                      {formatDateHeader(
                        grp.items[0].delivered_at || grp.items[0].created
                      )}
                    </span>
                    <span className="history-date-count">
                      ({grp.items.length}{" "}
                      {grp.items.length === 1
                        ? "produto entregue"
                        : "produtos entregues"}
                      )
                    </span>
                  </div>

                  {grp.items.map((r) => {
                    const chosenQ = r.quotes?.find((q) => q.id === r.chosen_quote);
                    const chosenRk = r.ranking?.find((x) => x.id === r.chosen_quote);
                    const local = getLocation(r.item);
                    const qtd = getQuantity(r.item);
                    const totalPago =
                      chosenRk?.total ??
                      (chosenQ?.unit_price
                        ? chosenQ.unit_price * Number(r.item?.quantidade || 1) +
                          (chosenQ.freight || 0)
                        : null);

                    return (
                      <div className="history-card" key={r.id}>
                        <div className="history-card-top">
                          <div>
                            <h4 className="history-card-title">
                              {r.item?.produto || r.raw}
                            </h4>
                            <div className="history-badges">
                              <span className="history-tag">
                                📦 Qtd: <b>{qtd}</b>
                              </span>
                              {local ? (
                                <span className="history-tag tag-loc">
                                  📍 Local: <b>{local}</b>
                                </span>
                              ) : null}
                              <span className="history-tag tag-ok">
                                ✓ Entregue
                              </span>
                              {r.delivered_at ? (
                                <span className="history-tag">
                                  🕒 {formatTime(r.delivered_at)}
                                </span>
                              ) : null}
                            </div>
                          </div>
                        </div>

                        {/* Detalhe do Fornecedor Escolhido / Comprado */}
                        {chosenQ ? (
                          <div className="history-winner-box">
                            <div className="history-winner-info">
                              <div>
                                <div className="history-winner-title">
                                  Fornecedor Comprado:
                                </div>
                                <div className="history-winner-name">
                                  🏆 {chosenQ.supplier}
                                </div>
                              </div>
                              <div className="history-winner-totals">
                                <div>
                                  <small style={{ color: "var(--m)" }}>
                                    Unitário:{" "}
                                  </small>
                                  <b>{brl(chosenQ.unit_price)}</b>
                                </div>
                                <div>
                                  <small style={{ color: "var(--m)" }}>
                                    Frete:{" "}
                                  </small>
                                  <b>{brl(chosenQ.freight)}</b>
                                </div>
                                <div className="history-winner-price">
                                  <small style={{ color: "var(--m)" }}>
                                    Total:{" "}
                                  </small>
                                  <b style={{ color: "var(--ok)" }}>
                                    {brl(totalPago)}
                                  </b>
                                </div>
                              </div>
                            </div>
                            {r.savings != null && r.savings > 0 ? (
                              <div className="history-winner-savings">
                                Economia obtida: <b>{brl(r.savings)}</b>
                              </div>
                            ) : null}
                          </div>
                        ) : null}

                        {/* Produtos Cotados nesta cotação */}
                        {r.quotes && r.quotes.length > 0 ? (
                          <div className="history-quotes-list">
                            <div className="history-quotes-title">
                              Produtos Cotados ({r.quotes.length} cotações):
                            </div>
                            <table>
                              <thead>
                                <tr>
                                  <th>Fornecedor</th>
                                  <th>Unit.</th>
                                  <th>Frete</th>
                                  <th>Prazo</th>
                                  <th>Total</th>
                                  <th>Resultado</th>
                                </tr>
                              </thead>
                              <tbody>
                                {r.quotes.map((q) => {
                                  const k = r.ranking?.find((x) => x.id === q.id);
                                  const isWinner = q.id === r.chosen_quote;
                                  return (
                                    <tr
                                      key={q.id}
                                      className={isWinner ? "best" : ""}
                                    >
                                      <td>
                                        <a
                                          href={q.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                        >
                                          {q.supplier}
                                        </a>
                                      </td>
                                      <td>{brl(q.unit_price)}</td>
                                      <td>
                                        {brl(q.freight)}
                                        {q.freight_estimated ? (
                                          <span className="est"> est.</span>
                                        ) : null}
                                      </td>
                                      <td>
                                        {q.lead_days != null
                                          ? `${q.lead_days}d`
                                          : "—"}
                                      </td>
                                      <td>
                                        {k?.total != null ? brl(k.total) : "—"}
                                      </td>
                                      <td>
                                        {isWinner ? (
                                          <span className="badge-winner">
                                            ✓ Comprado
                                          </span>
                                        ) : (
                                          <span className="badge-other">
                                            Cotado
                                          </span>
                                        )}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        ) : null}

                        {/* Ações da cotação no histórico */}
                        <div className="history-card-actions">
                          <button
                            type="button"
                            className="g"
                            onClick={() => show(r.id)}
                            style={{ fontSize: "12px", padding: "4px 10px" }}
                          >
                            🔍 Ver Detalhes
                          </button>
                          <button
                            type="button"
                            className="g"
                            onClick={() => handleUndeliver(r.id)}
                            style={{
                              fontSize: "12px",
                              padding: "4px 10px",
                              color: "var(--w)",
                            }}
                            title="Mover de volta para a coluna Decidido no Kanban"
                          >
                            ↩ Desfazer Entrega
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        ) : null}
      </div>

      {/* Modal Dialog de Detalhes da Cotação */}
      <dialog
        id="d"
        ref={dialogRef}
        onClose={() => setOpenId(null)}
        onClick={(e) => {
          if (e.target === dialogRef.current) {
            closeDialog();
          }
        }}
      >
        {openRequest ? (
          <div>
            <button
              className="g"
              onClick={closeDialog}
              style={{ float: "right" }}
            >
              Fechar
            </button>
            <h2>{openRequest.item?.produto || "Interpretando…"}</h2>
            <small>{openRequest.raw}</small>

            {openRequest.status === "aguardando_esclarecimento" ? (
              <div
                style={{
                  marginTop: "12px",
                  marginBottom: "16px",
                  padding: "12px",
                  background: "rgba(245, 158, 11, 0.1)",
                  border: "1px solid #f59e0b",
                  borderRadius: "8px",
                }}
              >
                <p style={{ margin: 0, fontWeight: "bold", color: "#f59e0b" }}>
                  ⚠️ Especificação genérica identificada
                </p>
                <p style={{ fontSize: "13px", margin: "6px 0 10px 0" }}>
                  Informe mais detalhes técnicos para prosseguir com a pesquisa (ex: dimensões, material, bitola, norma):
                </p>
                <div style={{ display: "flex", gap: "8px" }}>
                  <input
                    type="text"
                    style={{
                      flex: 1,
                      padding: "8px",
                      borderRadius: "4px",
                      border: "1px solid #444",
                      background: "#1e1e2f",
                      color: "#fff",
                    }}
                    placeholder="Ex: flexível 2,5mm 750V para instalação residencial"
                    value={clarifyText}
                    onChange={(e) => setClarifyText(e.target.value)}
                  />
                  <button onClick={() => handleClarify(openRequest.id)}>
                    Enviar e Continuar
                  </button>
                </div>
              </div>
            ) : null}

            <h3>Cotações</h3>
            <table>
              <thead>
                <tr>
                  <th>Fornecedor</th>
                  <th>Unit.</th>
                  <th>Frete</th>
                  <th>Prazo</th>
                  <th>Total</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(openRequest.quotes || []).map((q) => {
                  const k = rk.find((x) => x.id === q.id);
                  const i = k ? rk.indexOf(k) : -1;
                  const rowClass =
                    i === 0 ? "best" : k && !k.viavel ? "bad" : "";

                  return (
                    <React.Fragment key={q.id}>
                      <tr className={rowClass}>
                        <td>
                          <a
                            href={q.url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {q.supplier}
                          </a>
                        </td>
                        <td>{brl(q.unit_price)}</td>
                        <td>
                          {brl(q.freight)}
                          {q.freight_estimated ? (
                            <span className="est"> est.</span>
                          ) : null}
                        </td>
                        <td>{q.lead_days != null ? `${q.lead_days}d` : "—d"}</td>
                        <td>{k ? brl(k.total) : "—"}</td>
                        <td>{q.status}</td>
                        <td>
                          {openRequest.status === "comparando" && k?.viavel ? (
                            <button onClick={() => dec(openRequest.id, q.id)}>
                              Decidir
                            </button>
                          ) : null}
                        </td>
                      </tr>
                      {q.invite ? (
                        <tr>
                          <td colSpan={7}>
                            Convidar:{" "}
                            {q.invite.telegram ? (
                              <a
                                href={q.invite.telegram}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                link Telegram
                              </a>
                            ) : null}
                            {q.invite.telegram && q.invite.whatsapp ? " · " : null}
                            {q.invite.whatsapp ? (
                              <a
                                href={q.invite.whatsapp}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                WhatsApp
                              </a>
                            ) : null}
                            {q.invite.can_confirm ? (
                              <>
                                {" · "}
                                <button
                                  className="g"
                                  onClick={() => cfm(q.id)}
                                  style={{ padding: "2px 8px", fontSize: "12px" }}
                                >
                                  Confirmar envio via Bot
                                </button>
                              </>
                            ) : null}
                          </td>
                        </tr>
                      ) : null}
                      {["enviada", "aguardando_contato", "respondida_parcial"].includes(
                        q.status
                      ) ? (
                        <tr>
                          <td colSpan={7}>
                            <textarea
                              className="s"
                              id={`rp${q.id}`}
                              placeholder="Colar resposta do fornecedor recebida por outro canal"
                              value={replyTexts[q.id] || ""}
                              onChange={(e) =>
                                setReplyTexts((prev) => ({
                                  ...prev,
                                  [q.id]: e.target.value,
                                }))
                              }
                            />
                            <button className="g" onClick={() => rep(q.id)}>
                              Enviar resposta
                            </button>
                          </td>
                        </tr>
                      ) : null}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>

            {openRequest.reasoning ? (
              <>
                <h3>Por quê</h3>
                <pre>{openRequest.reasoning}</pre>
              </>
            ) : null}

            {openRequest.status === "decidido" ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginTop: "16px",
                  padding: "12px",
                  background: "rgba(46, 204, 143, 0.1)",
                  borderRadius: "8px",
                  border: "1px solid var(--ok)",
                }}
              >
                <p style={{ margin: 0 }}>
                  Decidido · economia <b>{brl(openRequest.savings)}</b>
                </p>
                <button
                  type="button"
                  className="btn-entregue"
                  onClick={() => {
                    handleDeliver(openRequest.id);
                    closeDialog();
                  }}
                >
                  ✓ Marcar como Entregue
                </button>
              </div>
            ) : openRequest.status === "entregue" ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginTop: "16px",
                  padding: "12px",
                  background: "rgba(46, 204, 143, 0.1)",
                  borderRadius: "8px",
                  border: "1px solid var(--ok)",
                }}
              >
                <p style={{ margin: 0 }}>
                  ✅ Entregue · economia <b>{brl(openRequest.savings)}</b>
                </p>
                <button
                  type="button"
                  className="g"
                  onClick={() => {
                    handleUndeliver(openRequest.id);
                    closeDialog();
                  }}
                  style={{ color: "var(--w)" }}
                >
                  ↩ Desfazer entrega
                </button>
              </div>
            ) : (
              <div>
                <button className="g" onClick={() => cmp(openRequest.id)}>
                  Comparar agora
                </button>
                {rk.length > 1 && openRequest.status === "comparando" ? (
                  <>
                    {" "}
                    <button className="g" onClick={() => neg(openRequest.id)}>
                      Negociar
                    </button>
                  </>
                ) : null}
              </div>
            )}

            <h3>Log dos agentes</h3>
            <pre>{(openRequest.log || []).join("\n")}</pre>
          </div>
        ) : null}
      </dialog>
    </>
  );
}
