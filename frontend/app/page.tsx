"use client";
import { useState, useRef, useCallback, useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || (typeof window !== "undefined" && window.location.hostname !== "localhost" ? "" : "http://localhost:8000");
const DEMO_PATH = "/Users/manishtellisim/Desktop/Birchlogic/multi-agents/backend/data/agentic_ai_curriculum.pdf";

// ─── Types ──────────────────────────────────────────────────────────────────
interface AgentState {
  name: string; color: string; status: "idle" | "running" | "waiting" | "done" | "error";
  currentTask: string; decisions: number; messagesSent: number; messagesReceived: number;
  lastDecision?: string; lastDecisionConf?: number; description: string;
}
interface TimelineEvent {
  id: string; ts: number; agent: string; agentColor: string;
  kind: "status" | "log" | "decision" | "message";
  text: string; reasoning?: string; action?: string;
  confidence?: number; to?: string; priority?: string;
}
interface Doc {
  document_id: string; title: string; source_path: string;
  page_count: number; status: string; sha256_hash: string;
}

const ROSTER = [
  { name: "orchestrator", color: "#818cf8", description: "Routes all agents based on Gemini decisions" },
  { name: "ingestion", color: "#38bdf8", description: "SHA-256 chain-of-custody · PDF intake" },
  { name: "extraction", color: "#34d399", description: "PyMuPDF native text · Tesseract OCR fallback" },
  { name: "segmentation", color: "#fb923c", description: "XY-Cut recursive block splitting" },
  { name: "classification", color: "#f472b6", description: "Rule engine + Gemini ambiguity resolver" },
  { name: "assembly", color: "#facc15", description: "Heading-stack section hierarchy builder" },
  { name: "table", color: "#22d3ee", description: "pdfplumber grid-line table detector" },
  { name: "reference", color: "#f87171", description: "Regex scan + Gemini reference resolver" },
  { name: "quality", color: "#4ade80", description: "Risk aggregator · human-review gate" },
  { name: "persistence", color: "#c084fc", description: "SQLAlchemy merge · evidence anchors" },
];
const COLOR_MAP = Object.fromEntries(ROSTER.map(r => [r.name, r.color]));

function makeInitialAgents(): Record<string, AgentState> {
  return Object.fromEntries(ROSTER.map(a => [a.name, {
    name: a.name, color: a.color, description: a.description,
    status: "idle", currentTask: "", decisions: 0, messagesSent: 0, messagesReceived: 0,
  }]));
}

const STATUS_BG: Record<string, string> = { idle: "#0d1117", running: "#0d1f3c", done: "#0b2818", error: "#1f0a0a", waiting: "#1a1200" };
const STATUS_BORDER: Record<string, string> = { idle: "#1e2535", running: "#2563eb", done: "#15803d", error: "#b91c1c", waiting: "#b45309" };
const STATUS_TEXT: Record<string, string> = { idle: "#374151", running: "#60a5fa", done: "#4ade80", error: "#f87171", waiting: "#fbbf24" };

const KIND_CONFIG = {
  log: { label: "LOG", color: "#374151", bg: "#0f141e" },
  status: { label: "STAGE", color: "#3b82f6", bg: "#0a1525" },
  decision: { label: "DECISION", color: "#7c3aed", bg: "#0f0a1f" },
  message: { label: "MESSAGE", color: "#0369a1", bg: "#0a1520" },
} as const;

// Agent abbreviation badge
function AgentBadge({ name, color, size = 22 }: { name: string; color: string; size?: number }) {
  const abbr = name.slice(0, 2).toUpperCase();
  return (
    <div style={{
      width: size, height: size, borderRadius: Math.round(size * 0.35),
      background: `${color}18`, border: `1.5px solid ${color}50`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: Math.round(size * 0.38), fontWeight: 700, color, flexShrink: 0,
      letterSpacing: "-0.5px", fontFamily: "monospace",
    }}>{abbr}</div>
  );
}

// Confidence bar
function ConfBar({ v, height = 4 }: { v: number; height?: number }) {
  const pct = Math.round(v * 100);
  const c = pct >= 90 ? "#4ade80" : pct >= 70 ? "#fbbf24" : "#f87171";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height, background: "#1a2535", borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: c, borderRadius: 2, transition: "width .5s" }} />
      </div>
      <span style={{ fontSize: 10, color: c, fontWeight: 700, minWidth: 32, textAlign: "right" }}>{pct}%</span>
    </div>
  );
}

// Status dot
function StatusDot({ status }: { status: string }) {
  const c = STATUS_TEXT[status] || STATUS_TEXT.idle;
  return (
    <span style={{
      display: "inline-block", width: 7, height: 7, borderRadius: "50%",
      background: c, flexShrink: 0, verticalAlign: "middle",
      boxShadow: status === "running" ? `0 0 5px ${c}88` : "none",
      animation: status === "running" ? "pulse 1.4s ease-in-out infinite" : "none",
    }} />
  );
}

// ─── Agent Card ─────────────────────────────────────────────────────────────
function AgentCard({ a }: { a: AgentState }) {
  const bg = STATUS_BG[a.status] || STATUS_BG.idle;
  const border = STATUS_BORDER[a.status] || STATUS_BORDER.idle;
  const glow = a.status === "running";

  return (
    <div style={{
      background: bg, border: `1.5px solid ${border}`,
      borderRadius: 10, padding: "11px 13px", minHeight: 108,
      transition: "all 0.3s ease",
      boxShadow: glow ? `0 0 14px ${border}44` : "none",
      display: "flex", flexDirection: "column", gap: 6, position: "relative", overflow: "hidden",
    }}>
      {/* Top accent */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 2,
        background: a.color, opacity: a.status === "idle" ? 0.2 : 0.7
      }} />

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <AgentBadge name={a.name} color={a.color} size={24} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 11.5, color: "#cbd5e1", textTransform: "capitalize" }}>{a.name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 2 }}>
            <StatusDot status={a.status} />
            <span style={{
              fontSize: 9, color: STATUS_TEXT[a.status] || STATUS_TEXT.idle,
              textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.7px"
            }}>
              {a.status}
            </span>
          </div>
        </div>
        <div style={{ textAlign: "right", fontSize: 9, color: "#1e2d3d", lineHeight: 1.9 }}>
          <div>{a.messagesSent} sent</div>
          <div>{a.messagesReceived} rcvd</div>
        </div>
      </div>

      {/* Description or task */}
      {a.status === "idle" ? (
        <div style={{ fontSize: 9.5, color: "#1e2d3d", lineHeight: 1.5 }}>{a.description}</div>
      ) : a.currentTask ? (
        <div style={{
          fontSize: 10, color: "#64748b", lineHeight: 1.4, fontStyle: "italic",
          borderLeft: `2px solid ${a.color}40`, paddingLeft: 6,
          overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        }}>{a.currentTask}</div>
      ) : null}

      {/* Last decision */}
      {a.lastDecision && (
        <div style={{
          fontSize: 10, color: "#7c3aed", overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: 1, WebkitBoxOrient: "vertical", marginTop: "auto"
        }}>
          {a.lastDecision}
        </div>
      )}
      {a.lastDecisionConf !== undefined && <ConfBar v={a.lastDecisionConf} />}

      {a.decisions > 0 && (
        <div style={{ fontSize: 9, color: "#1e2d3d" }}>
          {a.decisions} decision{a.decisions !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}

// ─── Timeline Row ────────────────────────────────────────────────────────────
function TimelineRow({
  ev, index, startTs, onClick,
}: { ev: TimelineEvent; index: number; startTs: number; onClick?: () => void }) {
  const cfg = KIND_CONFIG[ev.kind];
  const relSec = ((ev.ts - startTs) / 1000).toFixed(1);
  const clickable = ev.kind === "decision" || ev.kind === "message";

  return (
    <div
      onClick={clickable ? onClick : undefined}
      style={{
        display: "flex", gap: 10, padding: "7px 0",
        borderBottom: "1px solid #0d1117",
        cursor: clickable ? "pointer" : "default",
        animation: "fadeSlide .22s ease",
        transition: "background .15s",
      }}
      onMouseEnter={e => clickable && (e.currentTarget.style.background = "#0d1525")}
      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
    >
      {/* Index + time */}
      <div style={{ width: 34, flexShrink: 0, textAlign: "right", paddingTop: 2 }}>
        <div style={{ fontSize: 9, color: "#1e2d3d", fontFamily: "monospace", lineHeight: 1.5 }}>{index}</div>
        <div style={{ fontSize: 9, color: "#111827", fontFamily: "monospace" }}>{relSec}s</div>
      </div>

      {/* Agent badge + connector */}
      <div style={{ width: 22, flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <AgentBadge name={ev.agent} color={ev.agentColor} size={21} />
        <div style={{ flex: 1, width: 1, background: "#0d1117", margin: "2px 0" }} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: ev.agentColor, textTransform: "capitalize" }}>
            {ev.agent}
          </span>
          <span style={{
            fontSize: 8, padding: "1px 7px", borderRadius: 3, fontWeight: 800,
            background: `${cfg.color}18`, color: cfg.color,
            textTransform: "uppercase", letterSpacing: "0.6px", flexShrink: 0,
          }}>{cfg.label}</span>

          {ev.kind === "message" && ev.to && (
            <span style={{ fontSize: 10, color: "#374151" }}>
              to <span style={{ color: COLOR_MAP[ev.to] || "#64748b", fontWeight: 600 }}>{ev.to}</span>
            </span>
          )}

          {ev.confidence !== undefined && (
            <span style={{
              marginLeft: "auto", fontSize: 9.5, fontWeight: 700, flexShrink: 0,
              color: ev.confidence >= 0.9 ? "#4ade80" : ev.confidence >= 0.7 ? "#fbbf24" : "#f87171",
            }}>
              {Math.round(ev.confidence * 100)}%
            </span>
          )}

          {clickable && (
            <span style={{ fontSize: 9, color: "#1e2d3d", flexShrink: 0, marginLeft: ev.confidence ? 0 : "auto" }}>
              View details
            </span>
          )}
        </div>

        <div style={{
          fontSize: 11, color: ev.kind === "log" ? "#374151"
            : ev.kind === "decision" ? "#a5b4fc"
              : ev.kind === "message" ? "#7dd3fc"
                : "#60a5fa",
          marginTop: 3, lineHeight: 1.5,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: ev.kind === "log" ? 1 : 2,
          WebkitBoxOrient: "vertical",
        }}>{ev.text}</div>
      </div>
    </div>
  );
}

// ─── Detail Drawer ───────────────────────────────────────────────────────────
function DetailDrawer({
  ev, onClose,
}: { ev: TimelineEvent | null; onClose: () => void }) {
  const visible = ev !== null;

  return (
    <>
      {/* Overlay */}
      <div
        onClick={onClose}
        style={{
          position: "fixed", inset: 0, zIndex: 100,
          background: "rgba(0,0,0,0.55)", backdropFilter: "blur(2px)",
          opacity: visible ? 1 : 0,
          pointerEvents: visible ? "auto" : "none",
          transition: "opacity .25s ease",
        }}
      />

      {/* Drawer panel */}
      <div style={{
        position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 101,
        width: 440, background: "#080e1a",
        borderLeft: "1px solid #1e2d3d",
        boxShadow: "-12px 0 40px #000000aa",
        transform: visible ? "translateX(0)" : "translateX(100%)",
        transition: "transform .28s cubic-bezier(.4,0,.2,1)",
        display: "flex", flexDirection: "column",
        overflowY: "auto",
      }}>
        {!ev ? null : (
          <>
            {/* Drawer header */}
            <div style={{
              padding: "18px 22px", borderBottom: "1px solid #1e2d3d", flexShrink: 0,
              background: "#060c18", position: "sticky", top: 0, zIndex: 10,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <AgentBadge name={ev.agent} color={ev.agentColor} size={32} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#e2e8f0", textTransform: "capitalize" }}>
                    {ev.agent}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 3, alignItems: "center" }}>
                    <span style={{
                      fontSize: 9, padding: "2px 8px", borderRadius: 4, fontWeight: 800,
                      background: `${KIND_CONFIG[ev.kind].color}18`,
                      color: KIND_CONFIG[ev.kind].color,
                      textTransform: "uppercase", letterSpacing: "0.6px",
                    }}>{KIND_CONFIG[ev.kind].label}</span>
                    <span style={{ fontSize: 9, color: "#374151", fontFamily: "monospace" }}>
                      {new Date(ev.ts).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  style={{
                    width: 30, height: 30, borderRadius: 7, border: "1px solid #1e2d3d",
                    background: "transparent", color: "#475569", fontSize: 14,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    cursor: "pointer", transition: "all .15s", flexShrink: 0,
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = "#1e2d3d")}
                  onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                >✕</button>
              </div>
            </div>

            {/* Drawer body */}
            <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 20 }}>

              {/* Summary */}
              <div>
                <div style={{
                  fontSize: 10, fontWeight: 700, color: "#374151", textTransform: "uppercase",
                  letterSpacing: "0.8px", marginBottom: 8
                }}>Summary</div>
                <div style={{
                  fontSize: 13, color: "#e2e8f0", lineHeight: 1.7,
                  padding: "12px 14px", background: "#0d1225",
                  border: "1px solid #1e2d3d", borderRadius: 8,
                }}>{ev.text}</div>
              </div>

              {/* Confidence */}
              {ev.confidence !== undefined && (
                <div>
                  <div style={{
                    fontSize: 10, fontWeight: 700, color: "#374151", textTransform: "uppercase",
                    letterSpacing: "0.8px", marginBottom: 8
                  }}>Confidence</div>
                  <div style={{
                    padding: "12px 14px", background: "#0d1225",
                    border: "1px solid #1e2d3d", borderRadius: 8
                  }}>
                    <ConfBar v={ev.confidence} height={6} />
                    <div style={{ fontSize: 11, color: "#475569", marginTop: 8 }}>
                      {ev.confidence >= 0.9 ? "High confidence — auto-approved"
                        : ev.confidence >= 0.7 ? "Medium confidence — acceptable threshold"
                          : "Low confidence — quality flag raised"}
                    </div>
                  </div>
                </div>
              )}

              {/* Message details */}
              {ev.kind === "message" && (
                <div>
                  <div style={{
                    fontSize: 10, fontWeight: 700, color: "#374151", textTransform: "uppercase",
                    letterSpacing: "0.8px", marginBottom: 8
                  }}>Message Details</div>
                  <div style={{ padding: "14px", background: "#0d1225", border: "1px solid #1e2d3d", borderRadius: 8 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <tbody>
                        <tr style={{ borderBottom: "1px solid #1a2535" }}>
                          <td style={{ padding: "7px 0", color: "#475569", width: 90 }}>Subject</td>
                          <td style={{ padding: "7px 0", color: "#e2e8f0", fontWeight: 600 }}>{ev.text}</td>
                        </tr>
                        <tr style={{ borderBottom: "1px solid #1a2535" }}>
                          <td style={{ padding: "7px 0", color: "#475569" }}>Sender</td>
                          <td style={{ padding: "7px 0" }}>
                            <span style={{ color: ev.agentColor, fontWeight: 600 }}>{ev.agent}</span>
                          </td>
                        </tr>
                        {ev.to && (
                          <tr style={{ borderBottom: "1px solid #1a2535" }}>
                            <td style={{ padding: "7px 0", color: "#475569" }}>Recipient</td>
                            <td style={{ padding: "7px 0" }}>
                              <span style={{ color: COLOR_MAP[ev.to] || "#64748b", fontWeight: 600 }}>{ev.to}</span>
                            </td>
                          </tr>
                        )}
                        <tr>
                          <td style={{ padding: "7px 0", color: "#475569" }}>Priority</td>
                          <td style={{ padding: "7px 0" }}>
                            <span style={{
                              fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                              background: ev.priority === "critical" ? "rgba(239,68,68,.15)"
                                : ev.priority === "high" ? "rgba(245,158,11,.15)"
                                  : "rgba(55,65,81,.2)",
                              color: ev.priority === "critical" ? "#f87171"
                                : ev.priority === "high" ? "#fbbf24"
                                  : "#64748b",
                            }}>{(ev.priority || "normal").toUpperCase()}</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Gemini reasoning — the main event for decisions */}
              {ev.reasoning && (
                <div>
                  <div style={{
                    fontSize: 10, fontWeight: 700, color: "#374151", textTransform: "uppercase",
                    letterSpacing: "0.8px", marginBottom: 8
                  }}>Gemini Reasoning</div>
                  <div style={{
                    padding: "14px 16px", background: "#0a0618",
                    border: "1px solid #2d1f5e", borderRadius: 8,
                    borderLeft: "3px solid #7c3aed",
                  }}>
                    <div style={{
                      fontSize: 9, color: "#5b21b6", fontWeight: 700, textTransform: "uppercase",
                      letterSpacing: "0.6px", marginBottom: 10
                    }}>
                      Gemini 2.0 Flash Analysis
                    </div>
                    <div style={{
                      fontSize: 12.5, color: "#c4b5fd", lineHeight: 1.8,
                      whiteSpace: "pre-wrap", fontStyle: "normal",
                    }}>{ev.reasoning}</div>
                  </div>
                </div>
              )}

              {/* Action taken */}
              {ev.action && (
                <div>
                  <div style={{
                    fontSize: 10, fontWeight: 700, color: "#374151", textTransform: "uppercase",
                    letterSpacing: "0.8px", marginBottom: 8
                  }}>Action Taken</div>
                  <div style={{
                    padding: "12px 14px", background: "#071220",
                    border: "1px solid #1e3a5f", borderRadius: 8,
                    borderLeft: "3px solid #2563eb",
                  }}>
                    <div style={{ fontSize: 12, color: "#93c5fd", lineHeight: 1.7 }}>{ev.action}</div>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ─── Flow Step (left sidebar) ────────────────────────────────────────────────
function FlowStep({ a, isLast }: { a: AgentState; isLast: boolean }) {
  const active = a.status !== "idle";
  return (
    <div style={{ display: "flex", gap: 0, alignItems: "stretch" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginRight: 10 }}>
        <AgentBadge name={a.name} color={a.color} size={22} />
        {!isLast && <div style={{ flex: 1, width: 1, background: "#0d1117", minHeight: 8, margin: "2px 0" }} />}
      </div>
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : 10, paddingTop: 2, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontSize: 11, fontWeight: active ? 600 : 400, textTransform: "capitalize",
            color: a.status === "done" ? "#4ade80" : a.status === "running" ? a.color : "#374151",
          }}>{a.name}</span>
          {a.status === "done" && <span style={{ fontSize: 9, color: "#4ade80", fontWeight: 700 }}>Done</span>}
          {a.status === "running" && <span style={{ fontSize: 9, color: a.color, fontWeight: 700 }}>Running</span>}
          {a.status === "error" && <span style={{ fontSize: 9, color: "#f87171", fontWeight: 700 }}>Error</span>}
        </div>
        {a.currentTask && a.status !== "idle" && (
          <div style={{
            fontSize: 9, color: "#1e2d3d", overflow: "hidden", textOverflow: "ellipsis",
            whiteSpace: "nowrap", maxWidth: 158, lineHeight: 1.4
          }}>
            {a.currentTask}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Chat Panel ───────────────────────────────────────────────────────────────
interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  sources?: { block_id?: string; section_title?: string; page_number?: number; text_snippet: string; source_type: string }[];
  ts: number;
}

const SUGGESTED = [
  "What are the main topics covered in this document?",
  "Summarise the key sections and their content",
  "What tables are in this document and what do they contain?",
  "List all the learning objectives or outcomes mentioned",
  "What assessment methods are described?",
];

function ChatPanel({ docId }: { docId: string | null }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const msgIdRef = useRef(0);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  const sendMessage = async (question: string) => {
    if (!docId || !question.trim() || loading) return;
    const q = question.trim();
    setInput("");
    const userMsg: ChatMessage = { id: String(++msgIdRef.current), role: "user", text: q, ts: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/documents/${docId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, max_context_blocks: 20 }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setMessages(prev => [...prev, {
        id: String(++msgIdRef.current),
        role: "assistant",
        text: data.answer,
        sources: data.sources || [],
        ts: Date.now(),
      }]);
    } catch (e) {
      setMessages(prev => [...prev, {
        id: String(++msgIdRef.current), role: "assistant",
        text: `Error: Could not get a response. ${String(e)}`, ts: Date.now(),
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
  };

  if (!docId) return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 12, padding: 24 }}>
      <div style={{ width: 42, height: 42, borderRadius: 12, background: "linear-gradient(135deg,#7c3aed22,#2563eb22)", border: "1px solid #1e2d3d", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontSize: 18 }}>💬</span>
      </div>
      <div style={{ fontSize: 12, color: "#1e2d3d", textAlign: "center", lineHeight: 2 }}>
        Process a document to<br />start asking questions
      </div>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Messages area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 14 }}>

        {/* Welcome + suggestions */}
        {messages.length === 0 && (
          <div style={{ animation: "fadeSlide .3s ease" }}>
            <div style={{ background: "linear-gradient(135deg,#0a0e1a,#0d1525)", border: "1px solid #1e2d3d", borderRadius: 12, padding: "16px 18px", marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#818cf8", marginBottom: 6 }}>Ask anything about this document</div>
              <div style={{ fontSize: 11, color: "#374151", lineHeight: 1.7 }}>
                I have access to all extracted text, sections, tables, and references. Ask about specific topics, request summaries, or explore linked data.
              </div>
            </div>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#1e2d3d", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>
              Suggested questions
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {SUGGESTED.map((q, i) => (
                <button key={i} onClick={() => sendMessage(q)} style={{
                  textAlign: "left", padding: "8px 12px", borderRadius: 8,
                  background: "transparent", border: "1px solid #0d1825",
                  color: "#4b5870", fontSize: 11, cursor: "pointer", lineHeight: 1.5,
                  transition: "all .15s",
                }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#0a1020"; e.currentTarget.style.color = "#94a3b8"; e.currentTarget.style.borderColor = "#1e2d3d"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "#4b5470"; e.currentTarget.style.borderColor = "#0d1825"; }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Conversation */}
        {messages.map(msg => (
          <div key={msg.id} style={{ animation: "fadeSlide .22s ease" }}>
            {msg.role === "user" ? (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{
                  maxWidth: "85%", padding: "9px 14px", borderRadius: "12px 12px 3px 12px",
                  background: "linear-gradient(135deg,#1d4ed8,#4338ca)",
                  color: "#e2e8f0", fontSize: 12, lineHeight: 1.6,
                  boxShadow: "0 2px 12px #1d4ed830",
                }}>{msg.text}</div>
              </div>
            ) : (
              <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                {/* AI Avatar */}
                <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#7c3aed,#2563eb)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, marginTop: 1 }}>
                  <div style={{ width: 10, height: 10, borderRadius: 2, background: "rgba(255,255,255,0.85)" }} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {/* Answer text */}
                  <div style={{
                    background: "#060c18", border: "1px solid #0d1825", borderRadius: "3px 12px 12px 12px",
                    padding: "12px 15px", fontSize: 12, color: "#cbd5e1", lineHeight: 1.8,
                    whiteSpace: "pre-wrap",
                  }}>
                    {msg.text}
                  </div>

                  {/* Sources */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ fontSize: 9, fontWeight: 700, color: "#1e2d3d", textTransform: "uppercase", letterSpacing: "0.7px", marginBottom: 5 }}>
                        Sources
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {msg.sources.slice(0, 5).map((s, i) => (
                          <div key={i} style={{
                            display: "flex", gap: 8, alignItems: "flex-start",
                            background: "#04090f", border: "1px solid #0d1825",
                            borderRadius: 7, padding: "6px 10px",
                            borderLeft: `2px solid ${s.source_type === "section" ? "#818cf8" : s.source_type === "table" ? "#4ade80" : "#38bdf8"}`,
                          }}>
                            <span style={{
                              fontSize: 8, fontWeight: 800, padding: "1px 5px", borderRadius: 3, flexShrink: 0, marginTop: 1,
                              background: s.source_type === "section" ? "#818cf820" : s.source_type === "table" ? "#4ade8020" : "#38bdf820",
                              color: s.source_type === "section" ? "#818cf8" : s.source_type === "table" ? "#4ade80" : "#38bdf8",
                              textTransform: "uppercase",
                            }}>
                              {s.source_type}
                            </span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontSize: 10, color: "#4b5870", lineHeight: 1.5, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                                {s.text_snippet}
                              </div>
                              {s.page_number && (
                                <span style={{ fontSize: 9, color: "#1e2d3d" }}>Page {s.page_number}</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div style={{ fontSize: 9, color: "#0d1825", marginTop: 4 }}>
                    {new Date(msg.ts).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Thinking indicator */}
        {loading && (
          <div style={{ display: "flex", gap: 9, alignItems: "flex-start", animation: "fadeSlide .2s ease" }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "linear-gradient(135deg,#7c3aed,#2563eb)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: "rgba(255,255,255,0.85)" }} />
            </div>
            <div style={{ background: "#060c18", border: "1px solid #0d1825", borderRadius: "3px 12px 12px 12px", padding: "12px 16px", display: "flex", gap: 5, alignItems: "center" }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  width: 6, height: 6, borderRadius: "50%", background: "#818cf8",
                  animation: "pulse 1.4s ease-in-out infinite",
                  animationDelay: `${i * 0.2}s`,
                }} />
              ))}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Clear button + input */}
      {messages.length > 0 && (
        <div style={{ padding: "0 14px 4px", display: "flex", justifyContent: "flex-end" }}>
          <button onClick={() => setMessages([])} style={{
            fontSize: 10, color: "#1e2d3d", background: "transparent", border: "none", cursor: "pointer",
            padding: "2px 6px", borderRadius: 4, transition: "color .15s",
          }}
            onMouseEnter={e => (e.currentTarget.style.color = "#475569")}
            onMouseLeave={e => (e.currentTarget.style.color = "#1e2d3d")}
          >
            Clear chat
          </button>
        </div>
      )}

      {/* Input box */}
      <div style={{ padding: "8px 14px 12px", borderTop: "1px solid #0d1117", flexShrink: 0 }}>
        <div style={{ position: "relative", background: "#060c18", border: "1px solid #1e2d3d", borderRadius: 10, transition: "border-color .2s" }}
          onFocusCapture={e => (e.currentTarget.style.borderColor = "#2563eb")}
          onBlurCapture={e => (e.currentTarget.style.borderColor = "#1e2d3d")}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask about the document… (Enter to send, Shift+Enter for newline)"
            rows={3}
            style={{
              width: "100%", background: "transparent", border: "none", outline: "none",
              color: "#e2e8f0", fontSize: 12, lineHeight: 1.6, resize: "none",
              padding: "10px 44px 10px 12px", fontFamily: "inherit",
            }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading}
            style={{
              position: "absolute", right: 8, bottom: 8, width: 30, height: 30,
              borderRadius: 8, border: "none", cursor: input.trim() && !loading ? "pointer" : "default",
              background: input.trim() && !loading ? "linear-gradient(135deg,#1d4ed8,#7c3aed)" : "#0d1825",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all .2s", boxShadow: input.trim() && !loading ? "0 0 10px #3b82f650" : "none",
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={input.trim() && !loading ? "white" : "#1e2d3d"} strokeWidth="2.5">
              <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <div style={{ fontSize: 9, color: "#0d1825", marginTop: 5, textAlign: "center" }}>
          Answers grounded in document text · Sources cited above each response
        </div>
      </div>
    </div>
  );
}

// ─── Output Panel ────────────────────────────────────────────────────────────
function OutputPanel({ docId }: { docId: string | null }) {
  const [tab, setTab] = useState<"chat" | "sections" | "tables" | "refs" | "quality">("chat");
  const [sections, setSections] = useState<any[]>([]);
  const [tables, setTables] = useState<any[]>([]);
  const [refs, setRefs] = useState<any[]>([]);
  const [quality, setQuality] = useState<any>(null);

  useEffect(() => {
    if (!docId) { setSections([]); setTables([]); setRefs([]); setQuality(null); return; }
    fetch(`${API}/api/documents/${docId}/sections`).then(r => r.ok ? r.json() : []).then(setSections);
    fetch(`${API}/api/documents/${docId}/tables`).then(r => r.ok ? r.json() : []).then(setTables);
    fetch(`${API}/api/documents/${docId}/references`).then(r => r.ok ? r.json() : []).then(setRefs);
    fetch(`${API}/api/documents/${docId}/uncertainty`).then(r => r.ok ? r.json() : null).then(setQuality);
  }, [docId]);

  if (!docId) return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      height: "100%", gap: 10, padding: 24
    }}>
      <div style={{ fontSize: 12, color: "#1e2d3d", textAlign: "center", lineHeight: 2 }}>
        Structured output<br />appears here after<br />pipeline completes
      </div>
    </div>
  );

  const tabs = [
    { k: "chat" as const, l: "Chat" },
    { k: "sections" as const, l: `Sections (${sections.length})` },
    { k: "tables" as const, l: `Tables (${tables.length})` },
    { k: "refs" as const, l: `Refs (${refs.length})` },
    { k: "quality" as const, l: "Quality" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ display: "flex", padding: "8px 12px", gap: 3, borderBottom: "1px solid #0d1117", flexShrink: 0, flexWrap: "wrap" }}>
        {tabs.map(t => (
          <button key={t.k} onClick={() => setTab(t.k)} style={{
            padding: "4px 10px", borderRadius: 5, fontSize: 10, fontWeight: 600,
            border: "1px solid", cursor: "pointer", transition: "all .2s",
            background: tab === t.k ? (t.k === "chat" ? "rgba(37,99,235,.12)" : "rgba(99,102,241,.12)") : "transparent",
            borderColor: tab === t.k ? (t.k === "chat" ? "rgba(37,99,235,.35)" : "rgba(99,102,241,.35)") : "#1e2535",
            color: tab === t.k ? (t.k === "chat" ? "#60a5fa" : "#818cf8") : "#374151",
          }}>{t.l}</button>
        ))}
      </div>

      {/* Chat tab — full height */}
      {tab === "chat" && <ChatPanel docId={docId} />}

      {tab !== "chat" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "10px 14px" }}>
          {tab === "sections" && (sections.length === 0
            ? <p style={{ color: "#374151", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No sections</p>
            : sections.map(s => (
              <div key={s.section_id} style={{
                padding: `6px 0 6px ${Math.max((s.level - 1) * 12, 0)}px`,
                borderBottom: "1px solid #0d1117"
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {s.heading_number && (
                    <span style={{
                      fontFamily: "monospace", fontSize: 9, color: "#374151",
                      background: "#060c18", padding: "1px 5px", borderRadius: 3, flexShrink: 0
                    }}>
                      {s.heading_number}
                    </span>
                  )}
                  <span style={{
                    fontSize: s.level === 1 ? 12.5 : 11, fontWeight: s.level <= 2 ? 600 : 400,
                    color: s.level === 1 ? "#e2e8f0" : s.level === 2 ? "#94a3b8" : "#4b5870", flex: 1
                  }}>
                    {s.title}
                  </span>
                  <span style={{ fontSize: 9, color: "#1e2d3d", flexShrink: 0 }}>p{s.start_page}–{s.end_page}</span>
                </div>
              </div>
            ))
          )}

          {tab === "tables" && (tables.length === 0
            ? <p style={{ color: "#374151", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No tables</p>
            : <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {tables.map(t => (
                <div key={t.table_id} style={{ background: "#060c18", border: "1px solid #0d2218", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontWeight: 700, fontSize: 12, color: "#4ade80", marginBottom: 3 }}>
                    {t.caption || `Table ${t.table_number || t.table_id.slice(0, 8)}`}
                  </div>
                  <div style={{ fontSize: 10, color: "#374151" }}>{t.row_count}×{t.column_count} · Page {t.start_page}</div>
                  <div style={{ marginTop: 6 }}><ConfBar v={t.confidence_score || 1} height={3} /></div>
                </div>
              ))}
            </div>
          )}

          {tab === "refs" && (refs.length === 0
            ? <p style={{ color: "#374151", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No references</p>
            : refs.map(r => (
              <div key={r.ref_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid #0d1117" }}>
                <span style={{ fontSize: 10, color: r.is_resolved ? "#4ade80" : "#f87171", fontWeight: 700, flexShrink: 0 }}>
                  {r.is_resolved ? "Resolved" : "Unresolved"}
                </span>
                <span style={{ fontSize: 11, color: "#e2e8f0", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.ref_text}
                </span>
                <span style={{ fontSize: 9, color: "#374151", flexShrink: 0 }}>{r.ref_type}</span>
              </div>
            ))
          )}

          {tab === "quality" && !quality && (
            <p style={{ color: "#374151", fontSize: 12, textAlign: "center", paddingTop: 24 }}>Quality report not available</p>
          )}
          {tab === "quality" && quality && (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 12 }}>
                {[["Critical", quality.critical, "#ef4444"], ["High", quality.high, "#f59e0b"], ["Total", quality.total_flags, "#60a5fa"]].map(([l, v, c]) => (
                  <div key={String(l)} style={{ background: "#060c18", border: `1px solid ${String(c)}25`, borderRadius: 8, padding: "10px 6px", textAlign: "center" }}>
                    <div style={{ fontSize: 22, fontWeight: 800, color: String(c) }}>{String(v)}</div>
                    <div style={{ fontSize: 9, color: "#374151", marginTop: 1 }}>{String(l)}</div>
                  </div>
                ))}
              </div>
              {quality.gemini_assessment && (
                <div style={{ background: "#0a0618", border: "1px solid #2d1f5e", borderRadius: 8, padding: "12px 14px", borderLeft: "3px solid #7c3aed" }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#5b21b6", textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 8 }}>
                    Gemini Risk Assessment
                  </div>
                  <div style={{ fontSize: 11.5, color: "#c4b5fd", lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                    {quality.gemini_assessment}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}



// ─── Main ────────────────────────────────────────────────────────────────────
export default function HomePage() {
  const [agents, setAgents] = useState<Record<string, AgentState>>(makeInitialAgents);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [jobStatus, setJobStatus] = useState<"idle" | "running" | "complete" | "error">("idle");
  const [completedId, setCompletedId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [docs, setDocs] = useState<Doc[]>([]);
  const [isDrag, setIsDrag] = useState(false);
  const [startTs, setStartTs] = useState(Date.now());
  const [filterAgent, setFilterAgent] = useState("all");
  const [drawerEv, setDrawerEv] = useState<TimelineEvent | null>(null);

  const tlRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const evIdRef = useRef(0);

  useEffect(() => { tlRef.current?.scrollTo({ top: 999999, behavior: "smooth" }); }, [timeline]);

  const fetchDocs = async () => {
    const r = await fetch(`${API}/api/documents`).catch(() => null);
    if (r?.ok) setDocs(await r.json());
  };
  useEffect(() => { fetchDocs(); }, []);

  const addEvent = useCallback((ev: Omit<TimelineEvent, "id" | "ts" | "agentColor">) => {
    setTimeline(prev => [...prev, {
      ...ev, id: String(++evIdRef.current), ts: Date.now(),
      agentColor: COLOR_MAP[ev.agent] || "#64748b",
    }]);
  }, []);

  const handleEvent = useCallback((data: any) => {
    const { type, agent } = data;

    if (type === "agent_status") {
      setAgents(prev => ({ ...prev, [agent]: { ...prev[agent], status: data.status, currentTask: data.task || "" } }));
      if (data.task) addEvent({ agent, kind: "status", text: `${data.task}` });
    }
    if (type === "agent_log") {
      addEvent({ agent, kind: "log", text: data.message });
    }
    if (type === "agent_decision") {
      setAgents(prev => ({
        ...prev, [agent]: {
          ...prev[agent],
          decisions: (prev[agent]?.decisions || 0) + 1,
          lastDecision: data.decision,
          lastDecisionConf: data.confidence,
        },
      }));
      addEvent({
        agent, kind: "decision", text: data.decision,
        reasoning: data.reasoning, action: data.action, confidence: data.confidence
      });
    }
    if (type === "agent_message") {
      setAgents(prev => ({
        ...prev,
        [agent]: { ...prev[agent], messagesSent: (prev[agent]?.messagesSent || 0) + 1 },
        [data.to]: { ...(prev[data.to] || {}), messagesReceived: (prev[data.to]?.messagesReceived || 0) + 1 },
      }));
      addEvent({ agent, kind: "message", text: data.subject, to: data.to, priority: data.priority });
    }
    if (type === "pipeline_complete") {
      setJobStatus("complete"); setCompletedId(data.document_id); setStats(data.counts || {});
      fetchDocs();
    }
    if (type === "pipeline_error") {
      setJobStatus("error");
      addEvent({ agent: "orchestrator", kind: "log", text: `Pipeline error: ${data.message}` });
    }
    if (type === "stream_end") esRef.current?.close();
  }, [addEvent]);

  const startPipeline = async (path?: string, file?: File) => {
    esRef.current?.close();
    setAgents(makeInitialAgents()); setTimeline([]); setCompletedId(null);
    setStats({}); setJobStatus("running"); setDrawerEv(null);
    const ts = Date.now(); setStartTs(ts); evIdRef.current = 0;

    let jobId: string;
    if (path) {
      const r = await fetch(`${API}/api/agent/process-path`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path })
      });
      jobId = (await r.json()).job_id;
    } else if (file) {
      const form = new FormData(); form.append("file", file);
      const r = await fetch(`${API}/api/agent/upload`, { method: "POST", body: form });
      jobId = (await r.json()).job_id;
    } else return;

    const es = new EventSource(`${API}/api/agent/stream/${jobId}`);
    esRef.current = es;
    es.onmessage = e => { try { handleEvent(JSON.parse(e.data)); } catch { } };
    es.onerror = () => { setJobStatus("error"); es.close(); };
  };

  const displayDocId = completedId || selectedId;
  const filteredTimeline = filterAgent === "all" ? timeline : timeline.filter(e => e.agent === filterAgent);
  const totalDecisions = timeline.filter(e => e.kind === "decision").length;
  const totalMessages = timeline.filter(e => e.kind === "message").length;

  return (
    <div style={{
      display: "flex", flexDirection: "column", height: "100vh",
      background: "#05080f", color: "#e2e8f0",
      fontFamily: "'Inter',system-ui,sans-serif", overflow: "hidden",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
        @keyframes fadeSlide { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.45} }
        *{box-sizing:border-box;margin:0;padding:0}
        ::-webkit-scrollbar{width:4px;height:4px}
        ::-webkit-scrollbar-track{background:#03060e}
        ::-webkit-scrollbar-thumb{background:#1a2d45;border-radius:2px}
        button{font-family:inherit;outline:none}
      `}</style>

      {/* ═ HEADER ═══════════════════════════════════════════════════════════ */}
      <header style={{
        display: "flex", alignItems: "center", padding: "0 22px", height: 54, flexShrink: 0,
        background: "#060c18", borderBottom: "1px solid #0d1825",
        boxShadow: "0 1px 16px #000000bb",
      }}>
        {/* Brand */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 8, background: "linear-gradient(135deg,#1d4ed8,#7c3aed)",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 0 14px #3b82f640",
          }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(255,255,255,0.9)" }} />
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 14, letterSpacing: "-0.3px", color: "#e2e8f0", lineHeight: 1 }}>
              DIS Multi-Agent
            </div>
            <div style={{ fontSize: 9, color: "#1e2d3d", textTransform: "uppercase", letterSpacing: "1px", marginTop: 2 }}>
              Document Intelligence System · 10 Agents · Gemini 2.0
            </div>
          </div>
        </div>

        {/* Stats */}
        <div style={{ display: "flex", gap: 8, marginLeft: 28, alignItems: "center" }}>
          {[
            ["Events", String(timeline.length)],
            ["Decisions", String(totalDecisions)],
            ["Messages", String(totalMessages)],
            ...(jobStatus === "complete" ? [
              ["Pages", String(stats.pages || 0)],
              ["Sections", String(stats.sections || 0)],
              ["Tables", String(stats.tables || 0)],
            ] : []),
          ].map(([k, v]) => (
            <div key={k} style={{
              background: "#0a1020", border: "1px solid #0d1825",
              borderRadius: 7, padding: "4px 13px", textAlign: "center", minWidth: 56,
            }}>
              <div style={{ fontSize: 15, fontWeight: 800, color: "#60a5fa", lineHeight: 1 }}>{v}</div>
              <div style={{ fontSize: 8, color: "#374151", textTransform: "capitalize", marginTop: 1, letterSpacing: "0.3px" }}>{k}</div>
            </div>
          ))}
        </div>

        {/* Right: status + button */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            padding: "5px 14px", borderRadius: 18, fontSize: 11, fontWeight: 700, border: "1.5px solid",
            background: jobStatus === "complete" ? "rgba(34,197,94,.08)" : jobStatus === "running" ? "rgba(37,99,235,.08)" : jobStatus === "error" ? "rgba(185,28,28,.08)" : "transparent",
            borderColor: jobStatus === "complete" ? "rgba(34,197,94,.3)" : jobStatus === "running" ? "rgba(37,99,235,.3)" : jobStatus === "error" ? "rgba(185,28,28,.3)" : "#1e2535",
            color: jobStatus === "complete" ? "#4ade80" : jobStatus === "running" ? "#60a5fa" : jobStatus === "error" ? "#f87171" : "#374151",
          }}>
            {jobStatus === "running" ? "Processing" : jobStatus === "complete" ? "Complete" : jobStatus === "error" ? "Error" : "Idle"}
          </div>

          <button
            onClick={() => startPipeline(DEMO_PATH)}
            disabled={jobStatus === "running"}
            style={{
              padding: "7px 20px", borderRadius: 8, fontWeight: 700, fontSize: 12, border: "none",
              background: jobStatus === "running" ? "#1e2535" : "linear-gradient(135deg,#1d4ed8,#7c3aed)",
              color: jobStatus === "running" ? "#374151" : "white",
              boxShadow: jobStatus === "running" ? "none" : "0 0 20px #3b82f630",
              cursor: jobStatus === "running" ? "not-allowed" : "pointer", transition: "all .2s",
            }}>
            {jobStatus === "running" ? "Processing…" : "Run DIS Pipeline"}
          </button>
        </div>
      </header>

      {/* ═ BODY ══════════════════════════════════════════════════════════════ */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "196px 1fr 272px", overflow: "hidden" }}>

        {/* LEFT SIDEBAR */}
        <aside style={{
          background: "#060c18", borderRight: "1px solid #0d1825",
          overflowY: "auto", display: "flex", flexDirection: "column"
        }}>
          {/* Upload */}
          <div style={{ padding: "13px 14px", borderBottom: "1px solid #0d1825" }}>
            <div style={{
              fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.9px",
              color: "#1e2d3d", marginBottom: 7
            }}>Upload PDF</div>
            <div
              onDragOver={e => { e.preventDefault(); setIsDrag(true) }}
              onDragLeave={() => setIsDrag(false)}
              onDrop={e => { e.preventDefault(); setIsDrag(false); const f = e.dataTransfer.files[0]; if (f) startPipeline(undefined, f) }}
              onClick={() => fileRef.current?.click()}
              style={{
                border: `2px dashed ${isDrag ? "#2563eb" : "#1e2535"}`,
                borderRadius: 8, padding: "12px 8px", textAlign: "center",
                cursor: "pointer", color: "#374151", fontSize: 10,
                background: isDrag ? "rgba(37,99,235,.04)" : "transparent", transition: "all .2s",
              }}>Drop PDF or click to select
            </div>
            <input ref={fileRef} type="file" accept=".pdf" style={{ display: "none" }}
              onChange={e => { const f = e.target.files?.[0]; if (f) startPipeline(undefined, f) }} />
          </div>

          {/* Flow */}
          <div style={{ padding: "13px 14px", borderBottom: "1px solid #0d1825" }}>
            <div style={{
              fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.9px",
              color: "#1e2d3d", marginBottom: 12
            }}>Pipeline Flow</div>
            {ROSTER.filter(a => a.name !== "orchestrator").map((a, i, arr) => {
              const st = agents[a.name] || { ...a, status: "idle" as const, currentTask: "", decisions: 0, messagesSent: 0, messagesReceived: 0 };
              return <FlowStep key={a.name} a={st} isLast={i === arr.length - 1} />;
            })}
          </div>

          {/* Documents */}
          {docs.length > 0 && (
            <div style={{ padding: "13px 14px" }}>
              <div style={{
                fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.9px",
                color: "#1e2d3d", marginBottom: 8
              }}>Documents</div>
              {docs.map(d => (
                <div key={d.document_id} onClick={() => setSelectedId(d.document_id)} style={{
                  padding: "8px 10px", borderRadius: 7, cursor: "pointer", marginBottom: 5,
                  background: selectedId === d.document_id ? "rgba(37,99,235,.07)" : "transparent",
                  border: `1px solid ${selectedId === d.document_id ? "rgba(37,99,235,.2)" : "#0d1825"}`,
                  transition: "all .2s",
                }}>
                  <div style={{ fontSize: 11, color: "#94a3b8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {d.title || d.source_path}
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                    <span style={{ fontSize: 9, color: "#1e2d3d" }}>{d.page_count}pp</span>
                    <span style={{
                      marginLeft: "auto", fontSize: 8, fontWeight: 700, padding: "1px 7px", borderRadius: 3,
                      background: d.status === "complete" ? "rgba(34,197,94,.1)" : "rgba(37,99,235,.1)",
                      color: d.status === "complete" ? "#4ade80" : "#60a5fa"
                    }}>
                      {d.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </aside>

        {/* CENTER: AGENT GRID + TIMELINE */}
        <main style={{ display: "flex", flexDirection: "column", overflow: "hidden", background: "#05080f" }}>

          {/* Agent cards — 5×2 */}
          <div style={{ flexShrink: 0, borderBottom: "1px solid #0d1825" }}>
            <div style={{ padding: "9px 16px 6px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px", color: "#1e2d3d" }}>
                Agent Nerve Center — 10 Specialized Agents
              </span>
              <div style={{ display: "flex", gap: 10, fontSize: 9 }}>
                {(["idle", "running", "done", "error"] as const).map(s => (
                  <span key={s} style={{ display: "flex", alignItems: "center", gap: 4, color: STATUS_TEXT[s] }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: STATUS_TEXT[s], display: "inline-block" }} />
                    {s}
                  </span>
                ))}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 8, padding: "0 14px 12px" }}>
              {ROSTER.map(ar => (
                <AgentCard key={ar.name}
                  a={agents[ar.name] || { ...ar, status: "idle", currentTask: "", decisions: 0, messagesSent: 0, messagesReceived: 0 }} />
              ))}
            </div>
          </div>

          {/* Timeline */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {/* Timeline toolbar */}
            <div style={{
              padding: "8px 14px", borderBottom: "1px solid #0d1825", flexShrink: 0,
              display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap"
            }}>
              <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px", color: "#1e2d3d" }}>
                Pipeline Timeline
              </span>
              <span style={{
                fontSize: 9, color: "#1e2d3d", background: "#0a1020",
                padding: "2px 8px", borderRadius: 6
              }}>
                {filteredTimeline.length} events
              </span>
              <span style={{ fontSize: 9, color: "#1e2535" }}>· Click a DECISION or MESSAGE row to open detail drawer</span>

              {/* Filter */}
              <div style={{ display: "flex", gap: 3, marginLeft: "auto", flexWrap: "wrap" }}>
                <button onClick={() => setFilterAgent("all")} style={{
                  padding: "3px 9px", borderRadius: 4, fontSize: 8.5, fontWeight: 700, cursor: "pointer",
                  background: filterAgent === "all" ? "#1a2d45" : "transparent",
                  color: filterAgent === "all" ? "#60a5fa" : "#374151",
                  border: `1px solid ${filterAgent === "all" ? "#1a3a5c" : "#0d1825"}`,
                }}>All</button>
                {ROSTER.filter(r => timeline.some(e => e.agent === r.name)).map(r => (
                  <button key={r.name} onClick={() => setFilterAgent(r.name)} style={{
                    padding: "3px 9px", borderRadius: 4, fontSize: 8.5, fontWeight: 700, cursor: "pointer",
                    background: filterAgent === r.name ? `${r.color}15` : "transparent",
                    color: filterAgent === r.name ? r.color : "#374151",
                    border: `1px solid ${filterAgent === r.name ? r.color + "35" : "#0d1825"}`,
                  }}>{r.name}</button>
                ))}
              </div>
            </div>

            {/* Scrollable timeline */}
            <div ref={tlRef} style={{ flex: 1, overflowY: "auto", padding: "4px 14px 8px" }}>
              {filteredTimeline.length === 0 ? (
                <div style={{ paddingTop: 48, textAlign: "center", color: "#1e2535", lineHeight: 2.5 }}>
                  <div style={{ fontSize: 11, color: "#374151", marginBottom: 6 }}>No activity yet</div>
                  <div style={{ fontSize: 10, color: "#1e2535" }}>
                    Click <strong style={{ color: "#60a5fa", fontWeight: 700 }}>Run DIS Pipeline</strong> — every agent step appears here in real time.<br />
                    Click any <strong style={{ color: "#7c3aed" }}>DECISION</strong> or <strong style={{ color: "#0369a1" }}>MESSAGE</strong> row to open the detail drawer.
                  </div>
                </div>
              ) : (
                filteredTimeline.map((ev, i) => (
                  <TimelineRow
                    key={ev.id} ev={ev} index={i + 1} startTs={startTs}
                    onClick={() => setDrawerEv(ev)}
                  />
                ))
              )}
            </div>

            {/* Legend strip */}
            <div style={{
              display: "flex", gap: 14, padding: "5px 14px",
              borderTop: "1px solid #0d1825", flexShrink: 0, flexWrap: "wrap",
            }}>
              {Object.entries(KIND_CONFIG).map(([k, c]) => (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{
                    fontSize: 8, padding: "1px 6px", borderRadius: 3, fontWeight: 800,
                    background: `${c.color}15`, color: c.color, letterSpacing: "0.5px"
                  }}>
                    {c.label}
                  </span>
                  <span style={{ fontSize: 9, color: "#1e2d3d" }}>
                    {k === "log" ? "sub-step" : k === "status" ? "stage" : k === "decision" ? "Gemini decision" : "inter-agent msg"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </main>

        {/* RIGHT: STRUCTURED OUTPUT */}
        <aside style={{
          background: "#060c18", borderLeft: "1px solid #0d1825",
          display: "flex", flexDirection: "column", overflow: "hidden"
        }}>
          <div style={{ padding: "12px 14px", borderBottom: "1px solid #0d1825", flexShrink: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 12, color: "#e2e8f0" }}>Structured Output</div>
            {displayDocId
              ? <div style={{ fontSize: 9, color: "#1e2d3d", marginTop: 3, fontFamily: "monospace" }}>{displayDocId.slice(0, 16)}…</div>
              : <div style={{ fontSize: 9, color: "#1e2d3d", marginTop: 3 }}>Awaiting pipeline completion</div>
            }
          </div>
          <div style={{ flex: 1, overflow: "hidden" }}>
            <OutputPanel docId={displayDocId} />
          </div>
        </aside>
      </div>

      {/* DETAIL DRAWER + OVERLAY */}
      <DetailDrawer ev={drawerEv} onClose={() => setDrawerEv(null)} />
    </div>
  );
}
