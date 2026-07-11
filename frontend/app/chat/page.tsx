"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ChatEntity, ChatMessage, ChatSession, ChatSessionDetail, ChatSendResponse } from "@/lib/types";
import { Spinner, ErrorMsg } from "@/components/ui";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Example questions. The backend retrieves matching KB facts from Postgres (including
// retrieval-only request/response bodies that aren't in the model's weights) and injects
// them into the prompt, so both edited facts and bodies are answerable. Incident
// references by cause + rough time resolve against the incident table, and imperative
// requests (close/ack/assign) become confirmable actions.
const EXAMPLE_QUESTIONS: string[] = [
  "Who is the tech lead of the Payment Mgmt Team?",
  "What broke in payments yesterday afternoon?",
  "What is the request body of POST /v1/payments?",
  "Close the payment incident from this morning",
];

// Where an entity pill under an answer links to; unknown types render no pill.
function entityHref(e: ChatEntity): string | null {
  switch (e.type) {
    case "incident": return `/incident-log/${e.id}`;
    case "api": return `/knowledge-base/apis/${e.id}`;
    case "endpoint": return `/knowledge-base/endpoints/${e.id}`;
    case "team": return `/knowledge-base/teams/${e.id}`;
    default: return null;
  }
}

const ENTITY_TAG: Record<string, string> = {
  incident: "INCIDENT",
  api: "API",
  endpoint: "ENDPOINT",
  team: "TEAM",
};

type Streaming = { id: string; text: string };

// Fixed decoding config — no user-facing knobs (ChatGPT-style). Low temperature keeps
// answers grounded. Penalties stay mild: HF applies them over the whole sequence
// (prompt included), so aggressive values ban the model from restating the retrieved
// facts — which is exactly what a RAG answer has to do.
const GEN = {
  max_new_tokens: 256,
  temperature: 0.3,
  top_p: 0.9,
  repetition_penalty: 1.1,
  no_repeat_ngram_size: 0,
};

export default function ChatPage() {
  const qc = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const { data: sessions } = useQuery<ChatSession[]>({
    queryKey: ["chat-sessions"],
    queryFn: () => api.get<ChatSession[]>("/chat/sessions"),
  });

  const { data: session, isLoading: sessionLoading } = useQuery<ChatSessionDetail>({
    queryKey: ["chat-session", sessionId],
    queryFn: () => api.get<ChatSessionDetail>(`/chat/sessions/${sessionId}`),
    enabled: !!sessionId,
  });

  // Auto-select the most recent session on first load.
  useEffect(() => {
    if (!sessionId && sessions && sessions.length > 0) setSessionId(sessions[0].id);
  }, [sessions, sessionId]);

  // Clean up the EventSource on unmount.
  useEffect(() => () => esRef.current?.close(), []);

  // Keep the thread scrolled to the bottom as tokens arrive.
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [session?.messages.length, streaming?.text]);

  // Auto-grow the composer textarea as the user types.
  function autoGrow(el: HTMLTextAreaElement | null) {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }
  useEffect(() => {
    if (!input) autoGrow(inputRef.current);
  }, [input]);

  const newSessionMut = useMutation({
    mutationFn: () => api.post<ChatSession>("/chat/sessions", { title: "New chat" }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      setSessionId(s.id);
    },
  });

  const deleteSessionMut = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/chat/sessions/${id}`),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      if (sessionId === id) setSessionId(null);
    },
  });

  function openStream(messageId: string) {
    esRef.current?.close();
    setStreaming({ id: messageId, text: "" });
    const es = new EventSource(`${BASE}/api/v1/chat/stream/${messageId}`);
    esRef.current = es;
    es.onmessage = (e) => {
      const data = JSON.parse(e.data) as { type: string; t?: string; message?: string };
      if (data.type === "token") {
        setStreaming((s) => (s && s.id === messageId ? { ...s, text: s.text + (data.t ?? "") } : s));
      } else if (data.type === "done") {
        es.close();
        setStreaming(null);
        qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
      } else if (data.type === "error") {
        es.close();
        setStreamError(data.message ?? "Generation failed");
        setStreaming(null);
        qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
      }
    };
    es.onerror = () => {
      es.close();
      setStreamError("Lost connection to the model stream.");
      setStreaming(null);
    };
  }

  const sendMut = useMutation({
    mutationFn: (vars: { sid: string; prompt: string }) =>
      api.post<ChatSendResponse>(`/chat/sessions/${vars.sid}/messages`, {
        prompt: vars.prompt,
        ...GEN,
      }),
    onSuccess: async (res) => {
      setStreamError(null);
      await qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      // Deterministic turns (action proposals) are already complete — nothing to stream.
      if (res.stream_url) openStream(res.assistant_message_id);
    },
    onError: (e) => setStreamError((e as Error).message),
  });

  const actionMut = useMutation({
    mutationFn: (vars: { mid: string; decision: "confirm" | "dismiss" }) =>
      api.post<ChatMessage>(`/chat/messages/${vars.mid}/action`, { decision: vars.decision }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
      qc.invalidateQueries({ queryKey: ["incident-log"] });
    },
    onError: (e) => setStreamError((e as Error).message),
  });

  async function handleSend() {
    const prompt = input.trim();
    if (!prompt || streaming) return;

    let sid = sessionId;
    if (!sid) {
      const s = await newSessionMut.mutateAsync();
      sid = s.id;
    }
    setInput("");
    sendMut.mutate({ sid, prompt });
  }

  function stopStream() {
    esRef.current?.close();
    if (streaming) {
      qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
    }
    setStreaming(null);
  }

  function applyExample(question: string) {
    setInput(question);
    requestAnimationFrame(() => {
      autoGrow(inputRef.current);
      inputRef.current?.focus();
    });
  }

  const busy = sendMut.isPending || !!streaming;
  const hasMessages = (session?.messages?.length ?? 0) > 0;

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
      {/* Session rail */}
      <aside style={{
        width: "220px", flex: "0 0 220px", borderRight: "1px solid var(--border)",
        background: "var(--surface)", display: "flex", flexDirection: "column",
      }}>
        <div style={{ padding: "14px 14px 10px" }}>
          <button
            onClick={() => newSessionMut.mutate()}
            style={{
              width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: "7px",
              background: "var(--accent)", color: "var(--accent-fg)", border: "none",
              borderRadius: "8px", padding: "9px 12px", cursor: "pointer",
              font: "600 12.5px 'IBM Plex Sans'",
            }}
          >
            + New chat
          </button>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: "0 8px 12px" }}>
          {(sessions ?? []).map((s) => (
            <div
              key={s.id}
              onClick={() => setSessionId(s.id)}
              style={{
                display: "flex", alignItems: "center", gap: "6px",
                padding: "8px 10px", borderRadius: "8px", cursor: "pointer", marginBottom: "2px",
                background: s.id === sessionId ? "var(--accent-soft)" : "transparent",
                color: s.id === sessionId ? "var(--accent)" : "var(--text-muted)",
              }}
            >
              <span style={{ flex: 1, fontSize: "12.5px", fontWeight: s.id === sessionId ? 600 : 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {s.title}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); deleteSessionMut.mutate(s.id); }}
                title="Delete chat"
                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-faint)", fontSize: "14px", lineHeight: 1, padding: "0 2px" }}
              >
                ×
              </button>
            </div>
          ))}
          {(sessions ?? []).length === 0 && (
            <div style={{ padding: "16px 10px", fontSize: "12px", color: "var(--text-faint)" }}>
              No chats yet.
            </div>
          )}
        </div>
      </aside>

      {/* Conversation */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div ref={threadRef} style={{ flex: 1, overflow: "auto", padding: "24px 0" }}>
          <div style={{ maxWidth: "720px", margin: "0 auto", padding: "0 24px" }}>
            {!hasMessages && !sessionLoading && (
              <div style={{
                minHeight: "60vh", display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center", textAlign: "center", padding: "20px",
              }}>
                <div style={{ fontSize: "22px", fontWeight: 700, color: "var(--text)", marginBottom: "10px" }}>
                  Ask the knowledge base
                </div>
                <div style={{ fontSize: "13px", color: "var(--text-faint)", maxWidth: "440px", lineHeight: 1.6, marginBottom: "26px" }}>
                  Relevant facts — including request/response bodies that live only in
                  Postgres — are retrieved and given to the model as context (RAG) before it answers.
                </div>
                <div style={{
                  display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px",
                  width: "100%", maxWidth: "520px",
                }}>
                  {EXAMPLE_QUESTIONS.slice(0, 4).map((q) => (
                    <button
                      key={q}
                      onClick={() => applyExample(q)}
                      style={{
                        textAlign: "left", background: "var(--surface)", border: "1px solid var(--border)",
                        borderRadius: "12px", padding: "12px 14px", cursor: "pointer",
                        fontSize: "12.5px", color: "var(--text-muted)", lineHeight: 1.45,
                        transition: "border-color 0.12s",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                      onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {sessionLoading && <div style={{ textAlign: "center", padding: "40px" }}><Spinner /></div>}

            {(session?.messages ?? []).map((m) => {
              const isStreamingThis = streaming?.id === m.id;
              const text = isStreamingThis ? streaming!.text : m.content;
              const isUser = m.role === "user";
              return (
                <div key={m.id} style={{ marginBottom: "22px", display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start" }}>
                  <div style={{
                    maxWidth: isUser ? "80%" : "100%",
                    background: isUser ? "var(--accent-soft)" : "transparent",
                    border: "none",
                    borderRadius: isUser ? "16px" : "0",
                    padding: isUser ? "10px 14px" : "2px 0",
                    fontSize: "14px", lineHeight: 1.6, color: "var(--text)",
                    whiteSpace: "pre-wrap", wordBreak: "break-word",
                    fontFamily: "inherit",
                  }}>
                    {text}
                    {isStreamingThis && (
                      <span style={{ display: "inline-block", width: "7px", height: "14px", marginLeft: "2px", background: "var(--accent)", verticalAlign: "text-bottom", animation: "pulseDot 1s infinite" }} />
                    )}
                    {!text && isStreamingThis && <span style={{ color: "var(--text-faint)" }}>…</span>}
                  </div>
                  {/* On-call copilot: proposed action → confirm/dismiss; then outcome. */}
                  {m.role === "assistant" && m.gen_params?.proposed_action && (() => {
                    const pa = m.gen_params!.proposed_action!;
                    if (pa.status === "proposed") {
                      return (
                        <div style={{ display: "flex", gap: "8px", marginTop: "10px" }}>
                          <button
                            onClick={() => actionMut.mutate({ mid: m.id, decision: "confirm" })}
                            disabled={actionMut.isPending}
                            style={{
                              background: "var(--accent)", color: "var(--accent-fg)", border: "none",
                              borderRadius: "8px", padding: "7px 16px", cursor: "pointer",
                              font: "600 12.5px 'IBM Plex Sans'", opacity: actionMut.isPending ? 0.6 : 1,
                            }}
                          >
                            {actionMut.isPending ? "Working…" : `Confirm ${pa.type} ${pa.incident_number}`}
                          </button>
                          <button
                            onClick={() => actionMut.mutate({ mid: m.id, decision: "dismiss" })}
                            disabled={actionMut.isPending}
                            style={{
                              background: "var(--surface)", color: "var(--text-muted)",
                              border: "1px solid var(--border)", borderRadius: "8px",
                              padding: "7px 16px", cursor: "pointer", font: "500 12.5px 'IBM Plex Sans'",
                            }}
                          >
                            Dismiss
                          </button>
                        </div>
                      );
                    }
                    return (
                      <div style={{
                        marginTop: "8px", fontSize: "12px",
                        color: pa.status === "executed" ? "var(--ok)" : "var(--text-faint)",
                      }}>
                        {pa.status === "executed" ? "✓ " : ""}{pa.result}
                      </div>
                    );
                  })()}

                  {/* Deterministic entity pills — links to the incident / KB pages behind the answer. */}
                  {m.role === "assistant" && m.status !== "streaming" && (m.gen_params?.entities?.length ?? 0) > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "10px" }}>
                      {m.gen_params!.entities!.map((e) => {
                        const href = entityHref(e);
                        if (!href) return null;
                        return (
                          <Link
                            key={`${e.type}-${e.id}`}
                            href={href}
                            style={{
                              display: "inline-flex", alignItems: "center", gap: "6px",
                              background: e.type === "incident" ? "var(--danger-soft)" : "var(--accent-soft)",
                              color: e.type === "incident" ? "var(--danger)" : "var(--accent)",
                              border: "1px solid var(--border)", borderRadius: "999px",
                              padding: "3px 11px", fontSize: "11.5px", fontWeight: 600,
                              textDecoration: "none",
                            }}
                          >
                            <span style={{ fontSize: "9px", fontWeight: 700, letterSpacing: "0.06em", opacity: 0.75 }}>
                              {ENTITY_TAG[e.type] ?? e.type.toUpperCase()}
                            </span>
                            {e.label}
                            <span aria-hidden style={{ opacity: 0.6 }}>→</span>
                          </Link>
                        );
                      })}
                    </div>
                  )}

                  {m.role === "assistant" && m.status !== "streaming" && m.checkpoint_id && (
                    <div style={{ fontSize: "10px", color: "var(--text-faint)", marginTop: "4px", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>
                      checkpoint {m.checkpoint_id.slice(0, 8)}
                    </div>
                  )}
                  {m.role === "assistant" && m.status !== "streaming" && (m.gen_params?.retrieved?.length ?? 0) > 0 && (
                    <details style={{ marginTop: "6px", maxWidth: "88%" }}>
                      <summary style={{ fontSize: "10.5px", color: "var(--text-faint)", cursor: "pointer", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>
                        {m.gen_params!.retrieved!.length} fact{m.gen_params!.retrieved!.length > 1 ? "s" : ""} retrieved (RAG)
                      </summary>
                      <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "4px" }}>
                        {m.gen_params!.retrieved!.map((s, i) => (
                          <div key={i} style={{
                            fontSize: "11px", color: "var(--text-muted)", background: "var(--surface-2)",
                            border: "1px solid var(--border)", borderRadius: "6px", padding: "6px 8px",
                            whiteSpace: "pre-wrap", wordBreak: "break-word",
                            fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
                          }}>
                            {s}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Composer */}
        <div style={{ borderTop: "1px solid var(--border)", background: "var(--surface)", padding: "12px 0" }}>
          <div style={{ maxWidth: "720px", margin: "0 auto", padding: "0 24px" }}>
            {streamError && <div style={{ marginBottom: "10px" }}><ErrorMsg message={streamError} /></div>}

            {/* Input pill with embedded send / stop button */}
            <div style={{
              display: "flex", alignItems: "flex-end", gap: "8px",
              background: "var(--surface-2)", border: "1px solid var(--border)",
              borderRadius: "24px", padding: "8px 8px 8px 16px",
            }}>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => { setInput(e.target.value); autoGrow(e.target); }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
                }}
                placeholder="Ask about the API knowledge base…"
                rows={1}
                style={{
                  flex: 1, resize: "none", background: "transparent", border: "none",
                  padding: "6px 0", fontSize: "14px", lineHeight: 1.5, maxHeight: "200px",
                  color: "var(--text)", outline: "none", fontFamily: "inherit",
                }}
              />
              <button
                onClick={streaming ? stopStream : handleSend}
                disabled={!streaming && (busy || !input.trim())}
                title={streaming ? "Stop generating" : "Send"}
                style={{
                  flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "center",
                  width: "34px", height: "34px", borderRadius: "50%", border: "none",
                  background: streaming ? "var(--surface)" : "var(--accent)",
                  color: streaming ? "var(--text)" : "var(--accent-fg)",
                  cursor: streaming ? "pointer" : busy || !input.trim() ? "default" : "pointer",
                  opacity: !streaming && (busy || !input.trim()) ? 0.4 : 1,
                }}
              >
                {streaming ? (
                  <span style={{ width: "11px", height: "11px", background: "currentColor", borderRadius: "2px" }} />
                ) : sendMut.isPending ? (
                  <Spinner size={13} />
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="19" x2="12" y2="5" />
                    <polyline points="5 12 12 5 19 12" />
                  </svg>
                )}
              </button>
            </div>
            <div style={{ textAlign: "center", fontSize: "10.5px", color: "var(--text-faint)", marginTop: "7px" }}>
              Base LLaMA 3.2 3B with RAG over the KB — answers may be rough. Enter to send, Shift+Enter for newline.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
