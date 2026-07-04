"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ChatSession, ChatSessionDetail, ChatSendResponse } from "@/lib/types";
import { Spinner, ErrorMsg } from "@/components/ui";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Mirrors worker/triple_to_request.py RELATION_TEMPLATES — the prompts the KB is
// actually edited against, so these probe edited facts directly. Fill in the {}.
const PROBE_TEMPLATES: { label: string; template: string }[] = [
  { label: "tech lead", template: "The tech lead of the {} team is" },
  { label: "team → company", template: "The {} team belongs to the company" },
  { label: "API owner", template: "The {} API is owned by the team" },
  { label: "API description", template: "The {} API is described as" },
  { label: "point of contact", template: "The point of contact for the {} API is" },
  { label: "endpoint → API", template: "The {} endpoint belongs to the API" },
  { label: "business function", template: "The business function of {} is" },
];

type Streaming = { id: string; text: string };

export default function ChatPage() {
  const qc = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [greedy, setGreedy] = useState(true);
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(64);
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
        max_new_tokens: maxTokens,
        temperature: greedy ? 0 : temperature,
        top_p: 1.0,
      }),
    onSuccess: async (res) => {
      setStreamError(null);
      await qc.invalidateQueries({ queryKey: ["chat-session", sessionId] });
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      openStream(res.assistant_message_id);
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

  function applyProbe(template: string) {
    setInput(template);
    inputRef.current?.focus();
  }

  const busy = sendMut.isPending || !!streaming;

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
            {!sessionId && (
              <div style={{ textAlign: "center", padding: "60px 20px", color: "var(--text-faint)", fontSize: "13px" }}>
                Start a new chat and probe the model. This is a base completion model —
                fill in a template below and it will complete the sentence.
              </div>
            )}
            {sessionLoading && <div style={{ textAlign: "center", padding: "40px" }}><Spinner /></div>}

            {(session?.messages ?? []).map((m) => {
              const isStreamingThis = streaming?.id === m.id;
              const text = isStreamingThis ? streaming!.text : m.content;
              const isUser = m.role === "user";
              return (
                <div key={m.id} style={{ marginBottom: "18px", display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start" }}>
                  <div style={{ fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.4px", textTransform: "uppercase", color: "var(--text-faint)", marginBottom: "5px" }}>
                    {isUser ? "You" : "Model"}
                  </div>
                  <div style={{
                    maxWidth: "88%",
                    background: isUser ? "var(--accent-soft)" : "var(--surface)",
                    border: `1px solid ${isUser ? "transparent" : "var(--border)"}`,
                    borderRadius: "12px", padding: "11px 14px",
                    fontSize: "13.5px", lineHeight: 1.55, color: "var(--text)",
                    whiteSpace: "pre-wrap", wordBreak: "break-word",
                    fontFamily: isUser ? "inherit" : "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
                  }}>
                    {text}
                    {isStreamingThis && (
                      <span style={{ display: "inline-block", width: "7px", height: "14px", marginLeft: "2px", background: "var(--accent)", verticalAlign: "text-bottom", animation: "pulseDot 1s infinite" }} />
                    )}
                    {!text && isStreamingThis && <span style={{ color: "var(--text-faint)" }}>…</span>}
                  </div>
                  {m.role === "assistant" && m.status !== "streaming" && m.checkpoint_id && (
                    <div style={{ fontSize: "10px", color: "var(--text-faint)", marginTop: "4px", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>
                      checkpoint {m.checkpoint_id.slice(0, 8)}
                    </div>
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

            {/* Probe chips */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "10px" }}>
              {PROBE_TEMPLATES.map((p) => (
                <button
                  key={p.label}
                  onClick={() => applyProbe(p.template)}
                  title={p.template}
                  style={{
                    background: "var(--surface-2)", border: "1px solid var(--border)",
                    borderRadius: "20px", padding: "4px 11px", cursor: "pointer",
                    fontSize: "11.5px", color: "var(--text-muted)",
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* Input row */}
            <div style={{ display: "flex", gap: "9px", alignItems: "flex-end" }}>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
                }}
                placeholder="The tech lead of the Payments team is"
                rows={2}
                style={{
                  flex: 1, resize: "none", background: "var(--surface-2)", border: "1px solid var(--border)",
                  borderRadius: "10px", padding: "10px 12px", fontSize: "13.5px", lineHeight: 1.5,
                  color: "var(--text)", outline: "none", fontFamily: "inherit",
                }}
              />
              <button
                onClick={handleSend}
                disabled={busy || !input.trim()}
                style={{
                  flex: "0 0 auto", background: "var(--accent)", color: "var(--accent-fg)", border: "none",
                  borderRadius: "10px", padding: "10px 18px", cursor: busy || !input.trim() ? "default" : "pointer",
                  opacity: busy || !input.trim() ? 0.5 : 1, font: "600 13px 'IBM Plex Sans'", height: "42px",
                }}
              >
                {busy ? <Spinner size={13} /> : "Send"}
              </button>
            </div>

            {/* Generation controls */}
            <div style={{ display: "flex", alignItems: "center", gap: "16px", marginTop: "10px", fontSize: "11.5px", color: "var(--text-muted)" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input type="checkbox" checked={greedy} onChange={(e) => setGreedy(e.target.checked)} />
                Greedy (deterministic)
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", opacity: greedy ? 0.4 : 1 }}>
                temp
                <input
                  type="number" min={0.1} max={2} step={0.1} value={temperature} disabled={greedy}
                  onChange={(e) => setTemperature(parseFloat(e.target.value) || 0.1)}
                  style={{ width: "56px", background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "6px", padding: "3px 6px", color: "var(--text)", fontSize: "11.5px" }}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                max tokens
                <input
                  type="number" min={1} max={1024} step={1} value={maxTokens}
                  onChange={(e) => setMaxTokens(Math.max(1, Math.min(1024, parseInt(e.target.value) || 64)))}
                  style={{ width: "62px", background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "6px", padding: "3px 6px", color: "var(--text)", fontSize: "11.5px" }}
                />
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
