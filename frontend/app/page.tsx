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

const STATUS_BG: Record<string, string> = { idle: "#ffffff", running: "#eff6ff", done: "#f0fdf4", error: "#fef2f2", waiting: "#fffbeb" };
const STATUS_BORDER: Record<string, string> = { idle: "#e2e8f0", running: "#3b82f6", done: "#22c55e", error: "#ef4444", waiting: "#f59e0b" };
const STATUS_TEXT: Record<string, string> = { idle: "#94a3b8", running: "#3b82f6", done: "#22c55e", error: "#ef4444", waiting: "#f59e0b" };

const KIND_CONFIG = {
  log: { label: "LOG", color: "#64748b", bg: "#f8fafc" },
  status: { label: "STAGE", color: "#3b82f6", bg: "#eff6ff" },
  decision: { label: "DECISION", color: "#7c3aed", bg: "#f5f3ff" },
  message: { label: "MESSAGE", color: "#0369a1", bg: "#f0f9ff" },
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
  const c = pct >= 90 ? "#22c55e" : pct >= 70 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height, background: "#e2e8f0", borderRadius: 2 }}>
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
      display: "inline-block", width: 6, height: 6, borderRadius: "50%",
      background: c, flexShrink: 0, verticalAlign: "middle",
      animation: status === "running" ? "pulse 1.4s ease-in-out infinite" : "none",
    }} />
  );
}

// ─── Agent Card ─────────────────────────────────────────────────────────────
function AgentCard({ a }: { a: AgentState }) {
  const bg = STATUS_BG[a.status] || STATUS_BG.idle;
  const border = STATUS_BORDER[a.status] || STATUS_BORDER.idle;

  return (
    <div style={{
      background: bg, border: `1.5px solid ${border}`,
      borderRadius: 10, padding: "11px 13px", minHeight: 104,
      transition: "all 0.25s ease",
      boxShadow: a.status === "running" ? `0 2px 12px ${border}30` : "0 1px 3px rgba(0,0,0,0.06)",
      display: "flex", flexDirection: "column", gap: 5, position: "relative", overflow: "hidden",
    }}>
      {/* Top accent bar */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 2,
        background: a.color, opacity: a.status === "idle" ? 0.25 : 1,
      }} />

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <AgentBadge name={a.name} color={a.color} size={24} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 11.5, color: "#0f172a", textTransform: "capitalize" }}>{a.name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 2 }}>
            <StatusDot status={a.status} />
            <span style={{ fontSize: 9, color: STATUS_TEXT[a.status] || STATUS_TEXT.idle, textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.6px" }}>
              {a.status}
            </span>
          </div>
        </div>
        <div style={{ textAlign: "right", fontSize: 9, color: "#cbd5e1", lineHeight: 1.9 }}>
          <div>{a.messagesSent}↑</div>
          <div>{a.messagesReceived}↓</div>
        </div>
      </div>

      {/* Description or task */}
      {a.status === "idle" ? (
        <div style={{ fontSize: 9.5, color: "#94a3b8", lineHeight: 1.5 }}>{a.description}</div>
      ) : a.currentTask ? (
        <div style={{
          fontSize: 10, color: "#475569", lineHeight: 1.4, fontStyle: "italic",
          borderLeft: `2px solid ${a.color}60`, paddingLeft: 6,
          overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        }}>{a.currentTask}</div>
      ) : null}

      {a.lastDecision && (
        <div style={{ fontSize: 10, color: "#7c3aed", overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 1, WebkitBoxOrient: "vertical", marginTop: "auto" }}>
          {a.lastDecision}
        </div>
      )}
      {a.lastDecisionConf !== undefined && <ConfBar v={a.lastDecisionConf} />}
      {a.decisions > 0 && (
        <div style={{ fontSize: 9, color: "#94a3b8" }}>{a.decisions} decision{a.decisions !== 1 ? "s" : ""}</div>
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
        borderBottom: "1px solid #f1f5f9",
        cursor: clickable ? "pointer" : "default",
        animation: "fadeSlide .22s ease",
        transition: "background .12s",
      }}
      onMouseEnter={e => clickable && (e.currentTarget.style.background = "#f8fafc")}
      onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
    >
      {/* Index + time */}
      <div style={{ width: 34, flexShrink: 0, textAlign: "right", paddingTop: 2 }}>
        <div style={{ fontSize: 9, color: "#cbd5e1", fontFamily: "monospace", lineHeight: 1.5 }}>{index}</div>
        <div style={{ fontSize: 9, color: "#e2e8f0", fontFamily: "monospace" }}>{relSec}s</div>
      </div>

      {/* Agent badge + connector */}
      <div style={{ width: 22, flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <AgentBadge name={ev.agent} color={ev.agentColor} size={21} />
        <div style={{ flex: 1, width: 1, background: "#e2e8f0", margin: "2px 0" }} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: ev.agentColor, textTransform: "capitalize" }}>
            {ev.agent}
          </span>
          <span style={{
            fontSize: 8, padding: "1px 7px", borderRadius: 3, fontWeight: 800,
            background: `${cfg.color}15`, color: cfg.color,
            textTransform: "uppercase", letterSpacing: "0.6px", flexShrink: 0,
          }}>{cfg.label}</span>

          {ev.kind === "message" && ev.to && (
            <span style={{ fontSize: 10, color: "#94a3b8" }}>
              to <span style={{ color: COLOR_MAP[ev.to] || "#64748b", fontWeight: 600 }}>{ev.to}</span>
            </span>
          )}

          {ev.confidence !== undefined && (
            <span style={{
              marginLeft: "auto", fontSize: 9.5, fontWeight: 700, flexShrink: 0,
              color: ev.confidence >= 0.9 ? "#22c55e" : ev.confidence >= 0.7 ? "#f59e0b" : "#ef4444",
            }}>
              {Math.round(ev.confidence * 100)}%
            </span>
          )}

          {clickable && (
            <span style={{ fontSize: 9, color: "#cbd5e1", flexShrink: 0, marginLeft: ev.confidence ? 0 : "auto" }}>
              View details
            </span>
          )}
        </div>

        <div style={{
          fontSize: 11, color: ev.kind === "log" ? "#64748b"
            : ev.kind === "decision" ? "#7c3aed"
              : ev.kind === "message" ? "#0369a1"
                : "#3b82f6",
          marginTop: 3, lineHeight: 1.5,
          overflow: "hidden", display: "-webkit-box",
          WebkitLineClamp: ev.kind === "log" ? 1 : 2,
          WebkitBoxOrient: "vertical",
        }}>{ev.text}</div>
      </div>
    </div>
  );
}

// ─── Detail Drawer ──────────────────────────────────────────────────────────
function DetailDrawer({ ev, onClose }: { ev: TimelineEvent | null; onClose: () => void }) {
  const visible = ev !== null;
  return (
    <>
      <div onClick={onClose} style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(15,23,42,0.4)", backdropFilter: "blur(2px)",
        opacity: visible ? 1 : 0, pointerEvents: visible ? "auto" : "none",
        transition: "opacity .2s ease",
      }} />
      <div style={{
        position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 101,
        width: 440, background: "#ffffff",
        borderLeft: "1px solid #e2e8f0",
        boxShadow: "-8px 0 32px rgba(0,0,0,0.1)",
        transform: visible ? "translateX(0)" : "translateX(100%)",
        transition: "transform .28s cubic-bezier(.4,0,.2,1)",
        display: "flex", flexDirection: "column", overflowY: "auto",
      }}>
        {!ev ? null : (
          <>
            {/* Drawer header */}
            <div style={{
              padding: "18px 22px", borderBottom: "1px solid #e2e8f0", flexShrink: 0,
              background: "#f8fafc", position: "sticky", top: 0, zIndex: 10,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <AgentBadge name={ev.agent} color={ev.agentColor} size={32} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", textTransform: "capitalize" }}>{ev.agent}</div>
                  <div style={{ display: "flex", gap: 8, marginTop: 3, alignItems: "center" }}>
                    <span style={{
                      fontSize: 9, padding: "2px 8px", borderRadius: 4, fontWeight: 800,
                      background: `${KIND_CONFIG[ev.kind].color}15`, color: KIND_CONFIG[ev.kind].color,
                      textTransform: "uppercase", letterSpacing: "0.6px",
                    }}>{KIND_CONFIG[ev.kind].label}</span>
                    <span style={{ fontSize: 9, color: "#94a3b8", fontFamily: "monospace" }}>{new Date(ev.ts).toLocaleTimeString()}</span>
                  </div>
                </div>
                <button onClick={onClose} style={{
                  width: 30, height: 30, borderRadius: 7, border: "1px solid #e2e8f0",
                  background: "transparent", color: "#64748b", fontSize: 14,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: "pointer", transition: "all .15s", flexShrink: 0,
                }}
                  onMouseEnter={e => (e.currentTarget.style.background = "#f1f5f9")}
                  onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                >✕</button>
              </div>
            </div>

            {/* Drawer body */}
            <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 18 }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>Summary</div>
                <div style={{ fontSize: 13, color: "#1e293b", lineHeight: 1.7, padding: "12px 14px", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8 }}>{ev.text}</div>
              </div>

              {ev.confidence !== undefined && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>Confidence</div>
                  <div style={{ padding: "12px 14px", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8 }}>
                    <ConfBar v={ev.confidence} height={6} />
                    <div style={{ fontSize: 11, color: "#64748b", marginTop: 8 }}>
                      {ev.confidence >= 0.9 ? "High confidence — auto-approved" : ev.confidence >= 0.7 ? "Medium confidence — acceptable threshold" : "Low confidence — quality flag raised"}
                    </div>
                  </div>
                </div>
              )}

              {ev.kind === "message" && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>Message Details</div>
                  <div style={{ padding: "14px", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <tbody>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "7px 0", color: "#94a3b8", width: 90 }}>Subject</td>
                          <td style={{ padding: "7px 0", color: "#0f172a", fontWeight: 600 }}>{ev.text}</td>
                        </tr>
                        <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "7px 0", color: "#94a3b8" }}>Sender</td>
                          <td style={{ padding: "7px 0" }}><span style={{ color: ev.agentColor, fontWeight: 600 }}>{ev.agent}</span></td>
                        </tr>
                        {ev.to && (
                          <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                            <td style={{ padding: "7px 0", color: "#94a3b8" }}>Recipient</td>
                            <td style={{ padding: "7px 0" }}><span style={{ color: COLOR_MAP[ev.to] || "#64748b", fontWeight: 600 }}>{ev.to}</span></td>
                          </tr>
                        )}
                        <tr>
                          <td style={{ padding: "7px 0", color: "#94a3b8" }}>Priority</td>
                          <td style={{ padding: "7px 0" }}>
                            <span style={{
                              fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                              background: ev.priority === "critical" ? "#fef2f2" : ev.priority === "high" ? "#fffbeb" : "#f8fafc",
                              color: ev.priority === "critical" ? "#ef4444" : ev.priority === "high" ? "#f59e0b" : "#64748b",
                            }}>{(ev.priority || "normal").toUpperCase()}</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {ev.reasoning && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>LLM Reasoning</div>
                  <div style={{ padding: "14px 16px", background: "#faf5ff", border: "1px solid #e9d5ff", borderRadius: 8, borderLeft: "3px solid #7c3aed" }}>
                    <div style={{ fontSize: 9, color: "#7c3aed", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 10 }}>Analysis</div>
                    <div style={{ fontSize: 12.5, color: "#4c1d95", lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{ev.reasoning}</div>
                  </div>
                </div>
              )}

              {ev.action && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: 8 }}>Action Taken</div>
                  <div style={{ padding: "12px 14px", background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 8, borderLeft: "3px solid #3b82f6" }}>
                    <div style={{ fontSize: 12, color: "#1e40af", lineHeight: 1.7 }}>{ev.action}</div>
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
        {!isLast && <div style={{ flex: 1, width: 1, background: "#e2e8f0", minHeight: 8, margin: "2px 0" }} />}
      </div>
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : 10, paddingTop: 2, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontSize: 11, fontWeight: active ? 600 : 400, textTransform: "capitalize",
            color: a.status === "done" ? "#22c55e" : a.status === "running" ? a.color : "#94a3b8",
          }}>{a.name}</span>
          {a.status === "done" && <span style={{ fontSize: 9, color: "#22c55e", fontWeight: 700 }}>Done</span>}
          {a.status === "running" && <span style={{ fontSize: 9, color: a.color, fontWeight: 700 }}>Running</span>}
          {a.status === "error" && <span style={{ fontSize: 9, color: "#ef4444", fontWeight: 700 }}>Error</span>}
        </div>
        {a.currentTask && a.status !== "idle" && (
          <div style={{ fontSize: 9, color: "#94a3b8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 158, lineHeight: 1.4 }}>
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

  // Reset conversation whenever a different document is selected
  useEffect(() => { setMessages([]); setInput(""); }, [docId]);

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
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 10, padding: 24 }}>
      <div style={{ width: 36, height: 36, borderRadius: 8, background: "#f1f5f9", border: "1px solid #e2e8f0", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="1.8"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
      </div>
      <div style={{ fontSize: 12, color: "#94a3b8", textAlign: "center", lineHeight: 1.9 }}>
        Process a document to<br />start asking questions
      </div>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#ffffff" }}>
      {/* Messages area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: 12 }}>

        {/* Welcome + suggestions */}
        {messages.length === 0 && (
          <div style={{ animation: "fadeSlide .25s ease" }}>
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "14px 16px", marginBottom: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", marginBottom: 5 }}>Ask questions about this document</div>
              <div style={{ fontSize: 11, color: "#64748b", lineHeight: 1.7 }}>
                I have access to all extracted text, sections, tables, and references from this document.
              </div>
            </div>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 8 }}>
              Suggested
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {SUGGESTED.map((q, i) => (
                <button key={i} onClick={() => sendMessage(q)} style={{
                  textAlign: "left", padding: "8px 12px", borderRadius: 6,
                  background: "#ffffff", border: "1px solid #e2e8f0",
                  color: "#475569", fontSize: 11.5, cursor: "pointer", lineHeight: 1.5,
                  transition: "all .12s",
                }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#f8fafc"; e.currentTarget.style.borderColor = "#cbd5e1"; e.currentTarget.style.color = "#1e293b"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#ffffff"; e.currentTarget.style.borderColor = "#e2e8f0"; e.currentTarget.style.color = "#475569"; }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Conversation */}
        {messages.map(msg => (
          <div key={msg.id} style={{ animation: "fadeSlide .2s ease" }}>
            {msg.role === "user" ? (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{
                  maxWidth: "82%", padding: "9px 13px", borderRadius: "10px 10px 2px 10px",
                  background: "#1e293b", color: "#f1f5f9", fontSize: 12.5, lineHeight: 1.6,
                }}>{msg.text}</div>
              </div>
            ) : (
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                {/* Simple initials badge — no gradients */}
                <div style={{
                  width: 24, height: 24, borderRadius: 6, background: "#f1f5f9",
                  border: "1px solid #e2e8f0", display: "flex", alignItems: "center",
                  justifyContent: "center", flexShrink: 0, marginTop: 1,
                  fontSize: 9, fontWeight: 700, color: "#64748b", letterSpacing: "-0.3px",
                }}>DIS</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {/* Answer text */}
                  <div style={{
                    background: "#f8fafc", border: "1px solid #e2e8f0",
                    borderRadius: "2px 10px 10px 10px",
                    padding: "11px 14px", fontSize: 12.5, color: "#1e293b", lineHeight: 1.8,
                    whiteSpace: "pre-wrap",
                  }}>
                    {msg.text}
                  </div>

                  {/* Sources */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ fontSize: 9.5, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 5 }}>
                        Sources
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {msg.sources.slice(0, 5).map((s, i) => (
                          <div key={i} style={{
                            display: "flex", gap: 8, alignItems: "flex-start",
                            background: "#f8fafc", border: "1px solid #e2e8f0",
                            borderRadius: 6, padding: "6px 10px",
                            borderLeft: `2px solid ${s.source_type === "section" ? "#6366f1" : s.source_type === "table" ? "#10b981" : "#0ea5e9"}`,
                          }}>
                            <span style={{
                              fontSize: 8.5, fontWeight: 700, padding: "1px 6px", borderRadius: 3, flexShrink: 0, marginTop: 1,
                              background: s.source_type === "section" ? "#ede9fe" : s.source_type === "table" ? "#d1fae5" : "#e0f2fe",
                              color: s.source_type === "section" ? "#6366f1" : s.source_type === "table" ? "#10b981" : "#0ea5e9",
                              textTransform: "uppercase",
                            }}>
                              {s.source_type}
                            </span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontSize: 11, color: "#475569", lineHeight: 1.5, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                                {s.text_snippet}
                              </div>
                              {s.page_number && (
                                <span style={{ fontSize: 10, color: "#94a3b8" }}>Page {s.page_number}</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: "#cbd5e1", marginTop: 4 }}>
                    {new Date(msg.ts).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Thinking indicator — plain dots, no glow */}
        {loading && (
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start", animation: "fadeSlide .2s ease" }}>
            <div style={{ width: 24, height: 24, borderRadius: 6, background: "#f1f5f9", border: "1px solid #e2e8f0", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontSize: 9, fontWeight: 700, color: "#64748b" }}>DIS</div>
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "2px 10px 10px 10px", padding: "11px 16px", display: "flex", gap: 5, alignItems: "center" }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  width: 5, height: 5, borderRadius: "50%", background: "#94a3b8",
                  animation: "pulse 1.3s ease-in-out infinite",
                  animationDelay: `${i * 0.18}s`,
                }} />
              ))}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Clear button */}
      {messages.length > 0 && (
        <div style={{ padding: "0 16px 4px", display: "flex", justifyContent: "flex-end", background: "#ffffff" }}>
          <button onClick={() => setMessages([])} style={{
            fontSize: 11, color: "#94a3b8", background: "transparent", border: "none", cursor: "pointer",
            padding: "2px 0", transition: "color .12s",
          }}
            onMouseEnter={e => (e.currentTarget.style.color = "#475569")}
            onMouseLeave={e => (e.currentTarget.style.color = "#94a3b8")}
          >
            Clear conversation
          </button>
        </div>
      )}

      {/* Input box — light themed */}
      <div style={{ padding: "10px 16px 14px", borderTop: "1px solid #e2e8f0", flexShrink: 0, background: "#ffffff" }}>
        <div style={{ position: "relative", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, transition: "border-color .15s" }}
          onFocusCapture={e => (e.currentTarget.style.borderColor = "#94a3b8")}
          onBlurCapture={e => (e.currentTarget.style.borderColor = "#e2e8f0")}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask about the document… (Enter to send)"
            rows={3}
            style={{
              width: "100%", background: "transparent", border: "none", outline: "none",
              color: "#1e293b", fontSize: 12.5, lineHeight: 1.6, resize: "none",
              padding: "10px 44px 10px 12px", fontFamily: "inherit",
            }}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading}
            style={{
              position: "absolute", right: 8, bottom: 8, width: 28, height: 28,
              borderRadius: 6, border: "1px solid",
              borderColor: input.trim() && !loading ? "#1e293b" : "#e2e8f0",
              cursor: input.trim() && !loading ? "pointer" : "default",
              background: input.trim() && !loading ? "#1e293b" : "#f1f5f9",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all .15s",
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={input.trim() && !loading ? "#ffffff" : "#cbd5e1"} strokeWidth="2.5">
              <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <div style={{ fontSize: 10, color: "#cbd5e1", marginTop: 6, textAlign: "center" }}>
          Answers grounded in document · Enter to send
        </div>
      </div>
    </div>
  );
}

// ─── Output Panel ────────────────────────────────────────────────────────────
function OutputPanel({ docId, chatExpanded, onToggleChat }: { docId: string | null; chatExpanded: boolean; onToggleChat: () => void }) {
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
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 10, padding: 24 }}>
      <div style={{ fontSize: 12, color: "#94a3b8", textAlign: "center", lineHeight: 2 }}>
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
      {/* Tab bar + collapse toggle */}
      <div style={{ display: "flex", alignItems: "center", padding: "8px 10px", gap: 3, borderBottom: "1px solid #e2e8f0", flexShrink: 0, background: "#ffffff" }}>
        {tabs.map(t => (
          <button key={t.k} onClick={() => setTab(t.k)} style={{
            padding: "4px 10px", borderRadius: 5, fontSize: 10, fontWeight: 600,
            border: "1px solid", cursor: "pointer", transition: "all .15s",
            background: tab === t.k ? "#1e293b" : "transparent",
            borderColor: tab === t.k ? "#1e293b" : "transparent",
            color: tab === t.k ? "#ffffff" : "#64748b",
          }}>{t.l}</button>
        ))}
        {/* Collapse / expand button */}
        <button
          onClick={onToggleChat}
          title={chatExpanded ? "Collapse panel" : "Expand panel"}
          style={{
            marginLeft: "auto", padding: "4px 8px", borderRadius: 5, cursor: "pointer",
            background: "transparent", border: "1px solid #e2e8f0",
            color: "#64748b", fontSize: 12, lineHeight: 1,
            transition: "all .15s", display: "flex", alignItems: "center", gap: 4,
          }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = "#94a3b8")}
          onMouseLeave={e => (e.currentTarget.style.borderColor = "#e2e8f0")}
        >
          {chatExpanded
            ? <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="13 17 18 12 13 7" /><polyline points="6 17 11 12 6 7" /></svg>
            : <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="11 17 6 12 11 7" /><polyline points="18 17 13 12 18 7" /></svg>
          }
        </button>
      </div>

      {/* Chat tab — light themed full height */}
      {tab === "chat" && <ChatPanel docId={docId} />}

      {tab !== "chat" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "10px 14px" }}>
          {tab === "sections" && (sections.length === 0
            ? <p style={{ color: "#94a3b8", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No sections</p>
            : sections.map(s => (
              <div key={s.section_id} style={{ padding: `6px 0 6px ${Math.max((s.level - 1) * 12, 0)}px`, borderBottom: "1px solid #e2e8f0" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {s.heading_number && (<span style={{ fontFamily: "monospace", fontSize: 9, color: "#64748b", background: "#f8fafc", padding: "1px 5px", borderRadius: 3, flexShrink: 0 }}>{s.heading_number}</span>)}
                  <span style={{ fontSize: s.level === 1 ? 12.5 : 11, fontWeight: s.level <= 2 ? 600 : 400, color: s.level === 1 ? "#0f172a" : s.level === 2 ? "#334155" : "#475569", flex: 1 }}>{s.title}</span>
                  <span style={{ fontSize: 9, color: "#94a3b8", flexShrink: 0 }}>p{s.start_page}–{s.end_page}</span>
                </div>
              </div>
            ))
          )}
          {tab === "tables" && (tables.length === 0
            ? <p style={{ color: "#94a3b8", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No tables</p>
            : <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {tables.map(t => (
                <div key={t.table_id} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px" }}>
                  <div style={{ fontWeight: 700, fontSize: 12, color: "#16a34a", marginBottom: 3 }}>{t.caption || `Table ${t.table_number || t.table_id.slice(0, 8)}`}</div>
                  <div style={{ fontSize: 10, color: "#64748b" }}>{t.row_count}×{t.column_count} · Page {t.start_page}</div>
                  <div style={{ marginTop: 6 }}><ConfBar v={t.confidence_score || 1} height={3} /></div>
                </div>
              ))}
            </div>
          )}
          {tab === "refs" && (refs.length === 0
            ? <p style={{ color: "#94a3b8", fontSize: 12, textAlign: "center", paddingTop: 24 }}>No references</p>
            : refs.map(r => (
              <div key={r.ref_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0", borderBottom: "1px solid #e2e8f0" }}>
                <span style={{ fontSize: 10, color: r.is_resolved ? "#16a34a" : "#dc2626", fontWeight: 700, flexShrink: 0 }}>{r.is_resolved ? "Resolved" : "Unresolved"}</span>
                <span style={{ fontSize: 11, color: "#334155", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.ref_text}</span>
                <span style={{ fontSize: 9, color: "#94a3b8", flexShrink: 0 }}>{r.ref_type}</span>
              </div>
            ))
          )}
          {tab === "quality" && !quality && (<p style={{ color: "#94a3b8", fontSize: 12, textAlign: "center", paddingTop: 24 }}>Quality report not available</p>)}
          {tab === "quality" && quality && (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 12 }}>
                {[["Critical", quality.critical, "#dc2626"], ["High", quality.high, "#d97706"], ["Total", quality.total_flags, "#2563eb"]].map(([l, v, c]) => (
                  <div key={String(l)} style={{ background: "#f8fafc", border: `1px solid ${String(c)}40`, borderRadius: 8, padding: "10px 6px", textAlign: "center" }}>
                    <div style={{ fontSize: 22, fontWeight: 800, color: String(c) }}>{String(v)}</div>
                    <div style={{ fontSize: 9, color: "#64748b", marginTop: 1 }}>{String(l)}</div>
                  </div>
                ))}
              </div>
              {quality.gemini_assessment && (
                <div style={{ background: "#faf5ff", border: "1px solid #e9d5ff", borderRadius: 8, padding: "12px 14px", borderLeft: "3px solid #7c3aed" }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: "#6d28d9", textTransform: "uppercase", letterSpacing: "0.6px", marginBottom: 8 }}>Gemini Risk Assessment</div>
                  <div style={{ fontSize: 11.5, color: "#4c1d95", lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{quality.gemini_assessment}</div>
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
  const [chatExpanded, setChatExpanded] = useState(false);
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
      background: "#f1f5f9", color: "#0f172a",
      fontFamily: "'Inter',system-ui,sans-serif", overflow: "hidden",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
        @keyframes fadeSlide { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        *{box-sizing:border-box;margin:0;padding:0}
        ::-webkit-scrollbar{width:4px;height:4px}
        ::-webkit-scrollbar-track{background:#f1f5f9}
        ::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:2px}
        button{font-family:inherit;outline:none}
      `}</style>

      {/* ═ HEADER ═══════════════════════════════════════════════════════════ */}
      <header style={{
        display: "flex", alignItems: "center", padding: "0 22px", height: 54, flexShrink: 0,
        background: "#ffffff", borderBottom: "1px solid #e2e8f0",
        boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
      }}>
        {/* Brand */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 8, background: "#1e293b",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: "rgba(255,255,255,0.9)" }} />
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 14, letterSpacing: "-0.3px", color: "#0f172a", lineHeight: 1 }}>
              DIS Multi-Agent
            </div>
            <div style={{ fontSize: 9, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "1px", marginTop: 2 }}>
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
              background: "#f8fafc", border: "1px solid #e2e8f0",
              borderRadius: 7, padding: "4px 13px", textAlign: "center", minWidth: 56,
            }}>
              <div style={{ fontSize: 15, fontWeight: 800, color: "#3b82f6", lineHeight: 1 }}>{v}</div>
              <div style={{ fontSize: 8, color: "#94a3b8", textTransform: "capitalize", marginTop: 1, letterSpacing: "0.3px" }}>{k}</div>
            </div>
          ))}
        </div>

        {/* Right: status + button */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            padding: "5px 14px", borderRadius: 18, fontSize: 11, fontWeight: 700, border: "1.5px solid",
            background: jobStatus === "complete" ? "#f0fdf4" : jobStatus === "running" ? "#eff6ff" : jobStatus === "error" ? "#fef2f2" : "transparent",
            borderColor: jobStatus === "complete" ? "#bbf7d0" : jobStatus === "running" ? "#bfdbfe" : jobStatus === "error" ? "#fecaca" : "#e2e8f0",
            color: jobStatus === "complete" ? "#16a34a" : jobStatus === "running" ? "#2563eb" : jobStatus === "error" ? "#dc2626" : "#94a3b8",
          }}>
            {jobStatus === "running" ? "Processing" : jobStatus === "complete" ? "Complete" : jobStatus === "error" ? "Error" : "Idle"}
          </div>

          <button
            onClick={() => startPipeline(DEMO_PATH)}
            disabled={jobStatus === "running"}
            style={{
              padding: "7px 20px", borderRadius: 8, fontWeight: 700, fontSize: 12, border: "none",
              background: jobStatus === "running" ? "#f1f5f9" : "#1e293b",
              color: jobStatus === "running" ? "#94a3b8" : "white",
              cursor: jobStatus === "running" ? "not-allowed" : "pointer", transition: "all .2s",
              boxShadow: jobStatus === "running" ? "none" : "0 1px 4px rgba(0,0,0,0.15)",
            }}>
            {jobStatus === "running" ? "Processing…" : "Run DIS Pipeline"}
          </button>
        </div>
      </header>

      {/* ═ BODY ══════════════════════════════════════════════════════════════ */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: `196px 1fr ${chatExpanded ? "560px" : "340px"}`, overflow: "hidden", transition: "grid-template-columns .25s ease" }}>

        {/* LEFT SIDEBAR */}
        <aside style={{
          background: "#ffffff", borderRight: "1px solid #e2e8f0",
          overflowY: "auto", display: "flex", flexDirection: "column"
        }}>
          {/* Upload */}
          <div style={{ padding: "13px 14px", borderBottom: "1px solid #e2e8f0" }}>
            <div style={{
              fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.9px",
              color: "#94a3b8", marginBottom: 7
            }}>Upload PDF</div>
            <div
              onDragOver={e => { e.preventDefault(); setIsDrag(true) }}
              onDragLeave={() => setIsDrag(false)}
              onDrop={e => { e.preventDefault(); setIsDrag(false); const f = e.dataTransfer.files[0]; if (f) startPipeline(undefined, f) }}
              onClick={() => fileRef.current?.click()}
              style={{
                border: `2px dashed ${isDrag ? "#3b82f6" : "#e2e8f0"}`,
                borderRadius: 8, padding: "12px 8px", textAlign: "center",
                cursor: "pointer", color: "#94a3b8", fontSize: 10,
                background: isDrag ? "#eff6ff" : "transparent", transition: "all .2s",
              }}>Drop PDF or click to select
            </div>
            <input ref={fileRef} type="file" accept=".pdf" style={{ display: "none" }}
              onChange={e => { const f = e.target.files?.[0]; if (f) startPipeline(undefined, f) }} />
          </div>

          {/* Flow */}
          <div style={{ padding: "13px 14px", borderBottom: "1px solid #e2e8f0" }}>
            <div style={{
              fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.9px",
              color: "#94a3b8", marginBottom: 12
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
                color: "#94a3b8", marginBottom: 8
              }}>Documents</div>
              {docs.map(d => (
                <div key={d.document_id} onClick={() => setSelectedId(d.document_id)} style={{
                  padding: "8px 10px", borderRadius: 7, cursor: "pointer", marginBottom: 5,
                  background: selectedId === d.document_id ? "#eff6ff" : "transparent",
                  border: `1px solid ${selectedId === d.document_id ? "#bfdbfe" : "#e2e8f0"}`,
                  transition: "all .2s",
                }}>
                  <div style={{ fontSize: 11, color: "#334155", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {d.title || d.source_path}
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                    <span style={{ fontSize: 9, color: "#94a3b8" }}>{d.page_count}pp</span>
                    <span style={{
                      marginLeft: "auto", fontSize: 8, fontWeight: 700, padding: "1px 7px", borderRadius: 3,
                      background: d.status === "complete" ? "#f0fdf4" : "#eff6ff",
                      color: d.status === "complete" ? "#16a34a" : "#2563eb"
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
        <main style={{ display: "flex", flexDirection: "column", overflow: "hidden", background: "#f8fafc" }}>

          {/* Agent cards — 5×2 */}
          <div style={{ flexShrink: 0, borderBottom: "1px solid #e2e8f0" }}>
            <div style={{ padding: "9px 16px 6px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px", color: "#94a3b8" }}>
                Agent Nerve Center — 10 Specialized Agents
              </span>
              <div style={{ display: "flex", gap: 10, fontSize: 9 }}>
                {(["idle", "running", "done", "error"] as const).map(s => (
                  <span key={s} style={{ display: "flex", alignItems: "center", gap: 4, color: STATUS_TEXT[s] }}>
                    <span style={{ width: 5, height: 5, borderRadius: "50%", background: STATUS_TEXT[s], display: "inline-block" }} />
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
              padding: "8px 14px", borderBottom: "1px solid #e2e8f0", flexShrink: 0,
              display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap"
            }}>
              <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px", color: "#94a3b8" }}>
                Pipeline Timeline
              </span>
              <span style={{
                fontSize: 9, color: "#94a3b8", background: "#f1f5f9",
                padding: "2px 8px", borderRadius: 6
              }}>
                {filteredTimeline.length} events
              </span>
              <span style={{ fontSize: 9, color: "#cbd5e1" }}>· Click a DECISION or MESSAGE row to open detail drawer</span>

              {/* Filter */}
              <div style={{ display: "flex", gap: 3, marginLeft: "auto", flexWrap: "wrap" }}>
                <button onClick={() => setFilterAgent("all")} style={{
                  padding: "3px 9px", borderRadius: 4, fontSize: 8.5, fontWeight: 700, cursor: "pointer",
                  background: filterAgent === "all" ? "#1e293b" : "transparent",
                  color: filterAgent === "all" ? "#ffffff" : "#94a3b8",
                  border: `1px solid ${filterAgent === "all" ? "#1e293b" : "#e2e8f0"}`,
                }}>All</button>
                {ROSTER.filter(r => timeline.some(e => e.agent === r.name)).map(r => (
                  <button key={r.name} onClick={() => setFilterAgent(r.name)} style={{
                    padding: "3px 9px", borderRadius: 4, fontSize: 8.5, fontWeight: 700, cursor: "pointer",
                    background: filterAgent === r.name ? `${r.color}15` : "transparent",
                    color: filterAgent === r.name ? r.color : "#94a3b8",
                    border: `1px solid ${filterAgent === r.name ? r.color + "40" : "#e2e8f0"}`,
                  }}>{r.name}</button>
                ))}
              </div>
            </div>

            {/* Scrollable timeline */}
            <div ref={tlRef} style={{ flex: 1, overflowY: "auto", padding: "4px 14px 8px", background: "#ffffff" }}>
              {filteredTimeline.length === 0 ? (
                <div style={{ paddingTop: 48, textAlign: "center", color: "#94a3b8", lineHeight: 2.5 }}>
                  <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>No activity yet</div>
                  <div style={{ fontSize: 10, color: "#94a3b8" }}>
                    Click <strong style={{ color: "#1e293b", fontWeight: 700 }}>Run DIS Pipeline</strong> — every agent step appears here in real time.<br />
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
              borderTop: "1px solid #e2e8f0", flexShrink: 0, flexWrap: "wrap",
              background: "#ffffff",
            }}>
              {Object.entries(KIND_CONFIG).map(([k, c]) => (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <span style={{
                    fontSize: 8, padding: "1px 6px", borderRadius: 3, fontWeight: 800,
                    background: `${c.color}15`, color: c.color, letterSpacing: "0.5px"
                  }}>
                    {c.label}
                  </span>
                  <span style={{ fontSize: 9, color: "#94a3b8" }}>
                    {k === "log" ? "sub-step" : k === "status" ? "stage" : k === "decision" ? "LLM decision" : "inter-agent msg"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </main>

        {/* RIGHT: STRUCTURED OUTPUT + CHAT */}
        <aside style={{
          background: "#ffffff", borderLeft: "1px solid #e2e8f0",
          display: "flex", flexDirection: "column", overflow: "hidden",
          transition: "width .25s ease",
        }}>
          <div style={{ padding: "11px 14px", borderBottom: "1px solid #e2e8f0", flexShrink: 0, background: "#ffffff" }}>
            <div style={{ fontWeight: 600, fontSize: 12, color: "#1e293b" }}>Document Q&amp;A</div>
            {displayDocId
              ? <div style={{ fontSize: 9.5, color: "#94a3b8", marginTop: 2, fontFamily: "monospace" }}>{displayDocId.slice(0, 18)}…</div>
              : <div style={{ fontSize: 9.5, color: "#94a3b8", marginTop: 2 }}>No document selected</div>
            }
          </div>
          <div style={{ flex: 1, overflow: "hidden" }}>
            <OutputPanel docId={displayDocId} chatExpanded={chatExpanded} onToggleChat={() => setChatExpanded(e => !e)} />
          </div>
        </aside>
      </div>

      {/* DETAIL DRAWER + OVERLAY */}
      <DetailDrawer ev={drawerEv} onClose={() => setDrawerEv(null)} />
    </div>
  );
}
