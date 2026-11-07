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
  prazo_dias?: number;
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
  quotes: Quote[];
}

interface StatsData {
  decididas: number;
  economia_total: number;
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

export default function Home() {
  const [data, setData] = useState<RequestModel[]>([]);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [newText, setNewText] = useState("");
  const [replyTexts, setReplyTexts] = useState<Record<number, string>>({});
  const dialogRef = useRef<HTMLDialogElement>(null);

  const loadData = useCallback(async () => {
    try {
      const [reqs, st] = await Promise.all([
        api("/api/requests"),
        api("/api/stats"),
      ]);
      setData(Array.isArray(reqs) ? reqs : []);
      setStats(st);
    } catch (err) {
      console.error("Erro ao carregar dados:", err);
    }
  }, []);

  useEffect(() => {
    let ignore = false;

    async function initialFetch() {
      try {
        const [reqs, st] = await Promise.all([
          api("/api/requests"),
          api("/api/stats"),
        ]);
        if (!ignore) {
          setData(Array.isArray(reqs) ? reqs : []);
          setStats(st);
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
    if (dialogRef.current && !dialogRef.current.open) {
      dialogRef.current.showModal();
    }
  };

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

  const openRequest = openId !== null ? data.find((x) => x.id === openId) : null;
  const rk = openRequest?.ranking || [];

  return (
    <>
      <header>
        <h1>Comprador IA</h1>
        <span className="stat" id="st">
          {stats ? (
            <>
              {stats.decididas} decididas · economia <b>{brl(stats.economia_total)}</b>
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

      <div className="cols" id="cols">
        {S.map((c) => {
          const colData = data.filter((r) => r.status === c);
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
                        ? `${r.item.produto} · ${r.item.quantidade}${r.item.unidade || ""}`
                        : r.raw.slice(0, 50)}
                    </b>
                    <small>
                      {responded}/{totalQuotes} cotações
                    </small>
                    <small>{lastLog}</small>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

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
            <button className="g" onClick={closeDialog} style={{ float: "right" }}>
              Fechar
            </button>
            <h2>{openRequest.item?.produto || "Interpretando…"}</h2>
            <small>{openRequest.raw}</small>

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
              <p>
                Decidido · economia <b>{brl(openRequest.savings)}</b>
              </p>
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
