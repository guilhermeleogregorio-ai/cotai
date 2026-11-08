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
  const [showTechModal, setShowTechModal] = useState(false);

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
        <div className="header-brand">
          <div className="header-logo-badge">IA</div>
          <div>
            <h1>Comprador IA</h1>
            <span className="header-sub">Automação de Compras B2B com Agentes Inteligentes</span>
          </div>
          <span className="header-edition-pill">
            Guerra das IAs · Digitaly 03
          </span>
        </div>
        <div className="header-stats-hud">
          <div className="hud-metric">
            <span className="hud-label">Decididas</span>
            <span className="hud-value">{stats ? stats.decididas : 0}</span>
          </div>
          <div className="hud-divider" />
          <div className="hud-metric">
            <span className="hud-label">Economia Total</span>
            <span className="hud-value hud-money">{stats ? brl(stats.economia_total) : "R$ 0,00"}</span>
          </div>
        </div>
      </header>

      <form id="f" onSubmit={handleSubmit}>
        <div className="prompt-container">
          <div className="prompt-header">
            <span className="prompt-label">— CONSOLE DE OPERAÇÕES B2B · AGENTES DE IA</span>
            <span className="prompt-hint">Digite o pedido em linguagem natural</span>
          </div>
          <div className="prompt-input-row">
            <textarea
              id="t"
              rows={2}
              placeholder="Ex: preciso de 800m de cabo flexivel 2,5mm pra entregar em Ribeirão Preto ate dia 20"
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
            />
            <button type="submit">
              <span>Cotar</span>
              <span className="btn-arrow">→</span>
            </button>
          </div>
          <div className="prompt-suggestions">
            <span className="sug-title">Exemplos rápidos:</span>
            <button
              type="button"
              className="sug-pill"
              onClick={() => setNewText("800m de cabo flexível 2,5mm para Ribeirão Preto SP até dia 20")}
            >
              800m cabo flexível
            </button>
            <button
              type="button"
              className="sug-pill"
              onClick={() => setNewText("cabo de rede 10metros, São Carlos SP, em até 7 dias")}
            >
              Cabo de rede 10m
            </button>
            <button
              type="button"
              className="sug-pill"
              onClick={() => setNewText("35 tijolos para São Carlos SP")}
            >
              35 tijolos
            </button>
            <button
              type="button"
              className="sug-pill"
              onClick={() => setNewText("1 cadeira gamer ergonômica para São Carlos SP em até 7 dias")}
            >
              Cadeira gamer
            </button>
          </div>
        </div>
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
            <div className={`col col-${c}`} key={c}>
              <div className="col-header">
                <span className="col-header-title">
                  {N[c]}
                </span>
                <span className="col-badge-count">{colData.length}</span>
              </div>
              {colData.length === 0 ? (
                <div className="col-empty">
                  
                  <span className="col-empty-text">Nenhum pedido nesta etapa</span>
                </div>
              ) : null}
              {colData.map((r) => {
                const responded = (r.quotes || []).filter((q) =>
                  q.status.startsWith("respondida")
                ).length;
                const totalQuotes = (r.quotes || []).length;
                const lastLog =
                  r.log && r.log.length > 0 ? r.log[r.log.length - 1] : "na fila";
                const locationStr = getLocation(r.item);

                return (
                  <div className="card" key={r.id} onClick={() => show(r.id)}>
                    <div className="card-top-bar">
                      <span className={`card-status-pill status-${r.status}`}>
                        {r.status === "aguardando_esclarecimento"
                          ? "● ESPECIFICAÇÃO"
                          : r.status === "solicitado"
                          ? "● NA FILA"
                          : r.status === "cotando"
                          ? "● COTANDO"
                          : r.status === "comparando"
                          ? "● COMPARANDO"
                          : "● DECIDIDO"}
                      </span>
                      <span className="card-id">#{r.id}</span>
                    </div>

                    <h4 className="card-title">
                      {r.item?.produto || r.raw.slice(0, 50)}
                    </h4>

                    <div className="card-meta-chips">
                      {r.item?.quantidade != null ? (
                        <span className="card-chip">
                          QTD: {r.item.quantidade} {r.item.unidade || "un"}
                        </span>
                      ) : null}
                      {locationStr ? (
                        <span className="card-chip chip-location">
                          DESTINO: {locationStr}
                        </span>
                      ) : null}
                      {r.item?.prazo_max_dias ? (
                        <span className="card-chip chip-time">
                          PRAZO: {r.item.prazo_max_dias}d
                        </span>
                      ) : null}
                    </div>

                    {totalQuotes > 0 ? (
                      <div className="card-progress-wrapper">
                        <div className="card-progress-bar">
                          <div
                            className="card-progress-fill"
                            style={{
                              width: `${Math.round((responded / totalQuotes) * 100)}%`,
                            }}
                          />
                        </div>
                        <span className="card-progress-text">
                          {responded} de {totalQuotes} cotações ({Math.round((responded / totalQuotes) * 100)}%)
                        </span>
                      </div>
                    ) : null}

                    <div className="card-terminal-log">
                      <span className="card-log-prompt">&gt;</span>
                      <span className="card-log-text">{lastLog}</span>
                    </div>

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
                          Concluir Entrega
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
                <h2>Histórico de Compras</h2>
                <p className="history-subtitle">
                  Exibindo as últimas 5 cotações entregues · Produtos comprados, quantidades, locais e cotações separadas por data
                </p>
              </div>
            </div>

            {last5History.length === 0 ? (
              <div className="history-empty">
                
                <p>Nenhuma compra entregue registrada no histórico ainda.</p>
                <small style={{ color: "var(--m)" }}>
                  Finalize uma cotação e clique no botão <b>&quot;Entregue&quot;</b> na coluna <b>Decidido</b> do Kanban acima para arquivá-la aqui (armazenando até as últimas 5 cotações).
                </small>
              </div>
            ) : (
              groupedHistory.map((grp) => (
                <div className="history-date-group" key={grp.dateKey}>
                  <div className="history-date-header">
                    
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
                                Qtd: <b>{qtd}</b>
                              </span>
                              {local ? (
                                <span className="history-tag tag-loc">
                                  Destino: <b>{local}</b>
                                </span>
                              ) : null}
                              <span className="history-tag tag-ok">
                                Entregue
                              </span>
                              {r.delivered_at ? (
                                <span className="history-tag">
                                  {formatTime(r.delivered_at)}
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
                                  {chosenQ.supplier}
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
                                        {Boolean(q.source?.includes('[Simulado]') || q.url?.includes('simulacao')) ? (
                                          <span className="badge-simulado" title="Cotação simulada">
                                            <span className="badge-simulado-dot" />
                                            Simulado
                                          </span>
                                        ) : (
                                          <span className="badge-real" title="Fornecedor real">
                                            <span className="badge-real-dot" />
                                            Web
                                          </span>
                                        )}
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
                                            Comprado
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
                            Ver Detalhes
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
                            Desfazer Entrega
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
                  ESPECIFICAÇÃO TÉCNICA NECESSÁRIA
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
                          {Boolean(q.source?.includes('[Simulado]') || q.url?.includes('simulacao')) ? (
                            <span className="badge-simulado" title="Cotação simulada coerente conforme Requisito 03 do Edital">
                              <span className="badge-simulado-dot" />
                              Simulado
                            </span>
                          ) : (
                            <span className="badge-real" title="Fornecedor real validado na web">
                              <span className="badge-real-dot" />
                              Web Real
                            </span>
                          )}
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
                  Marcar como Entregue
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
                  Entregue · economia <b>{brl(openRequest.savings)}</b>
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
      {/* Rodape Institucional */}
      <footer className="site-footer">
        <div className="footer-main">
          <div className="footer-brand-col">
            <div className="footer-brand-row">
              <div className="footer-logo">IA</div>
              <div>
                <div className="footer-title">Comprador IA</div>
                <div className="footer-subtitle">Automacao de Compras B2B com Agentes Inteligentes</div>
              </div>
            </div>
            <p className="footer-desc">
              Plataforma de cotacao automatizada que utiliza agentes de inteligencia artificial
              para buscar, comparar e negociar as melhores ofertas do mercado B2B em tempo real.
            </p>
            <div className="footer-edition">
              Guerra das IAs · Hackathon Digitaly 03 · Sao Carlos - SP
            </div>
          </div>

          <div className="footer-stack-col">
            <h4 className="footer-col-title">Stack Tecnologico</h4>
            <div className="footer-tech-tags">
              <span className="footer-tag">Next.js 14</span>
              <span className="footer-tag">React 18</span>
              <span className="footer-tag">TypeScript</span>
              <span className="footer-tag">FastAPI</span>
              <span className="footer-tag">Python 3.12</span>
              <span className="footer-tag">Gemini 2.0 Flash</span>
              <span className="footer-tag">SQLite</span>
              <span className="footer-tag">Telegram Bot API</span>
            </div>
            <div className="footer-certs">
              <span className="footer-cert footer-cert-w3c">W3C Semantic HTML5</span>
              <span className="footer-cert footer-cert-arch">Clean Architecture</span>
            </div>
            <button
              type="button"
              className="footer-specs-btn"
              onClick={() => setShowTechModal(true)}
            >
              Ver Especificacoes de Engenharia
            </button>
          </div>

          <div className="footer-team-col">
            <h4 className="footer-col-title">Squad de Desenvolvimento</h4>
            <ul className="footer-team-list">
              <li><b>Guilherme Gregorio</b><span>Full-Stack / AI Agents</span></li>
              <li><b>Gabriel Ribeiro</b><span>Full-Stack / UI-UX</span></li>
              <li><b>Caua Habermann</b><span>Full-Stack / Integration</span></li>
              <li><b>Juliana Nishimura</b><span>Data Engineer / QA</span></li>
            </ul>
          </div>
        </div>

        <div className="footer-bottom">
          <span>Comprador IA · Hackathon Guerra das IAs · Digitaly 03 · {new Date().getFullYear()}</span>
          <span className="footer-bottom-right">Desenvolvido com Next.js, FastAPI e Google Gemini AI</span>
        </div>
      </footer>

      {/* Modal de Especificacoes de Engenharia */}
      {showTechModal ? (
        <div
          className="tech-modal-overlay"
          onClick={() => setShowTechModal(false)}
        >
          <div
            className="tech-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="tech-modal-header">
              <div>
                <h2 style={{ margin: 0, fontFamily: "'Space Grotesk', sans-serif", color: "#fff" }}>
                  Especificacoes de Engenharia
                </h2>
                <span className="tech-modal-sub">
                  COMPRADOR IA // HACKATHON GUERRA DAS IAs // DIGITALY 03
                </span>
              </div>
              <button
                type="button"
                className="top-bar-btn"
                onClick={() => setShowTechModal(false)}
              >
                Fechar
              </button>
            </div>

            <div className="tech-modal-grid">
              <div className="tech-box">
                <h3>Squad de Desenvolvimento</h3>
                <ul className="tech-list">
                  <li><b>Guilherme Gregorio</b> — Backend Engineer / AI Agent Architecture</li>
                  <li><b>Gabriel Ribeiro</b> — Frontend Engineer / UI-UX</li>
                  <li><b>Caua Habermann</b> — Full-Stack Engineer / Integration</li>
                  <li><b>Juliana Nishimura</b> — Data Engineer / QA</li>
                </ul>
              </div>

              <div className="tech-box">
                <h3>Stack Tecnologico</h3>
                <ul className="tech-list">
                  <li><b>Frontend:</b> <code>Next.js 14</code> + <code>React 18</code> + <code>TypeScript</code></li>
                  <li><b>Backend:</b> <code>FastAPI</code> + <code>Python 3.12</code> + <code>Uvicorn</code></li>
                  <li><b>IA / LLM:</b> <code>Google Gemini 2.0 Flash</code> + Google Search Grounding</li>
                  <li><b>Banco:</b> <code>SQLite 3</code> com WAL mode</li>
                  <li><b>Comunicacao:</b> <code>Telegram Bot API</code> (python-telegram-bot)</li>
                  <li><b>Scraping Fallback:</b> <code>DuckDuckGo</code> + <code>BeautifulSoup4</code></li>
                </ul>
              </div>

              <div className="tech-box">
                <h3>Conformidade W3C</h3>
                <ul className="tech-list">
                  <li><b>HTML5 Semantico:</b> header, main, section, article, dialog, nav</li>
                  <li><b>ARIA:</b> roles, aria-label, aria-live para acessibilidade</li>
                  <li><b>CSS Custom Properties:</b> design tokens em variaveis CSS nativas</li>
                  <li><b>Responsividade:</b> CSS Grid + Flexbox + media queries</li>
                  <li><b>Web Standards:</b> Fetch API, ES2022+, sem dependencias de runtime externas</li>
                </ul>
              </div>

              <div className="tech-box">
                <h3>Clean Architecture</h3>
                <ul className="tech-list">
                  <li><b>Camada de Dominio:</b> entidades Request, Quote, Ranking independentes</li>
                  <li><b>Camada de Aplicacao:</b> agentes orquestradores (interpret, search, compare, decide, negotiate)</li>
                  <li><b>Camada de Infra:</b> SQLite repository, Gemini adapter, Telegram adapter</li>
                  <li><b>Separacao de Concerns:</b> frontend SPA desacoplado do backend via REST API</li>
                  <li><b>Inversao de Dependencia:</b> fallback hierarchy (Gemini → DuckDuckGo → Simulacao)</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      ) : null}

    </>
  );
}
