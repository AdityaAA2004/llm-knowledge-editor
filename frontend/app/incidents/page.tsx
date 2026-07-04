"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  IncidentBriefQueuedResponse,
  IncidentContext,
  IncidentBriefRequest,
  IncidentSeverity,
} from "@/lib/types";
import { Button, Card, ErrorMsg, FieldInput, MonoBadge, SectionLabel, Spinner } from "@/components/ui";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const INITIAL_FORM: IncidentBriefRequest = {
  title: "Payments API 5xx spike",
  severity: "high",
  signal_source: "synthetic monitor",
  service_hint: "Payment Mgmt Team",
  api_hint: "Payments API",
  http_method: "POST",
  path: "/v1/payments",
  symptom: "POST /v1/payments is returning elevated 5xx responses and latency is spiking.",
};

const SEVERITIES: IncidentSeverity[] = ["low", "medium", "high", "critical"];

type StreamState = {
  requestId: string;
};

function SummaryItem({ label, value }: { label: string; value: string | null }) {
  return (
    <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
      <div style={{ fontSize: "10.5px", textTransform: "uppercase", letterSpacing: "0.45px", color: "var(--text-faint)", marginBottom: "4px" }}>
        {label}
      </div>
      <div style={{ fontSize: "13px", color: value ? "var(--text)" : "var(--text-faint)", fontFamily: value ? "inherit" : "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>
        {value ?? "unknown"}
      </div>
    </div>
  );
}

function FactList({ title, facts, tone }: { title: string; facts: string[]; tone: "info" | "ok" | "warn" | "muted" }) {
  return (
    <Card>
      <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: `var(--${tone})` }} />
        <span style={{ fontSize: "12.5px", fontWeight: 600 }}>{title}</span>
      </div>
      {facts.length === 0 ? (
        <div style={{ padding: "16px 14px", fontSize: "12px", color: "var(--text-faint)" }}>No matching facts found.</div>
      ) : (
        facts.map((fact, idx) => (
          <div
            key={`${title}-${idx}`}
            style={{
              padding: "11px 14px",
              borderBottom: idx === facts.length - 1 ? "none" : "1px solid var(--border)",
              fontSize: "12px",
              lineHeight: 1.55,
              color: "var(--text-muted)",
              fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {fact}
          </div>
        ))
      )}
    </Card>
  );
}

export default function IncidentsPage() {
  const [form, setForm] = useState<IncidentBriefRequest>(INITIAL_FORM);
  const [queued, setQueued] = useState<IncidentBriefQueuedResponse | null>(null);
  const [briefText, setBriefText] = useState("");
  const [stream, setStream] = useState<StreamState | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => () => esRef.current?.close(), []);

  const submitMut = useMutation({
    mutationFn: (body: IncidentBriefRequest) =>
      api.post<IncidentBriefQueuedResponse>("/incidents/brief", {
        ...body,
        signal_source: body.signal_source || null,
        service_hint: body.service_hint || null,
        api_hint: body.api_hint || null,
        http_method: body.http_method || null,
        path: body.path || null,
      }),
    onSuccess: (result) => {
      setQueued(result);
      setBriefText("");
      setStreamError(null);
      openStream(result);
    },
    onError: (error) => {
      setStream(null);
      setStreamError((error as Error).message);
    },
  });

  const summary = queued?.context.deterministic_summary ?? null;
  const context: IncidentContext | null = queued?.context ?? null;
  const isStreaming = !!stream;

  function update<K extends keyof IncidentBriefRequest>(key: K, value: IncidentBriefRequest[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function openStream(result: IncidentBriefQueuedResponse) {
    esRef.current?.close();
    setStream({ requestId: result.request_id });
    const es = new EventSource(`${BASE}${result.stream_url}`);
    esRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data) as { type: string; t?: string; message?: string };
      if (data.type === "token") {
        setBriefText((current) => current + (data.t ?? ""));
      } else if (data.type === "done") {
        es.close();
        setStream(null);
      } else if (data.type === "error") {
        es.close();
        setStream(null);
        setStreamError(data.message ?? "Incident brief generation failed.");
      }
    };

    es.onerror = () => {
      es.close();
      setStream(null);
      setStreamError("Lost connection to the incident brief stream.");
    };
  }

  const generatedBrief = useMemo(() => briefText, [briefText]);

  return (
    <div style={{ height: "100%", minHeight: 0, display: "grid", gridTemplateColumns: "380px minmax(0, 1fr)" }}>
      <aside style={{ borderRight: "1px solid var(--border)", background: "var(--surface)", padding: "24px 20px", overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
          <MonoBadge label="INCIDENT" tone="accent" />
          <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Simulate a production alert</span>
        </div>

        <Card>
          <div style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "14px" }}>
            <FieldInput label="Alert title" value={form.title} onChange={(value) => update("title", value)} required />

            <div>
              <label style={{ display: "block", fontSize: "11.5px", fontWeight: 500, color: "var(--text-muted)", marginBottom: "6px" }}>
                Severity
              </label>
              <select
                value={form.severity}
                onChange={(event) => update("severity", event.target.value as IncidentSeverity)}
                style={{
                  width: "100%",
                  background: "var(--surface-2)",
                  border: "1px solid var(--border)",
                  borderRadius: "8px",
                  padding: "9px 11px",
                  fontSize: "13px",
                  color: "var(--text)",
                  outline: "none",
                }}
              >
                {SEVERITIES.map((severity) => (
                  <option key={severity} value={severity}>
                    {severity}
                  </option>
                ))}
              </select>
            </div>

            <FieldInput label="Signal source" value={form.signal_source ?? ""} onChange={(value) => update("signal_source", value)} placeholder="synthetic monitor" />
            <FieldInput label="Service hint" value={form.service_hint ?? ""} onChange={(value) => update("service_hint", value)} placeholder="Payment Mgmt Team" />
            <FieldInput label="API hint" value={form.api_hint ?? ""} onChange={(value) => update("api_hint", value)} placeholder="Payments API" />
            <div style={{ display: "grid", gridTemplateColumns: "110px 1fr", gap: "10px" }}>
              <FieldInput label="HTTP method" value={form.http_method ?? ""} onChange={(value) => update("http_method", value)} placeholder="POST" />
              <FieldInput label="Path" value={form.path ?? ""} onChange={(value) => update("path", value)} placeholder="/v1/payments" />
            </div>
            <FieldInput label="Symptom" value={form.symptom} onChange={(value) => update("symptom", value)} multiline required />
          </div>
          <div style={{ padding: "14px 16px", borderTop: "1px solid var(--border)", background: "var(--surface-2)", display: "flex", gap: "8px" }}>
            <Button
              onClick={() => submitMut.mutate(form)}
              disabled={submitMut.isPending || isStreaming}
            >
              {(submitMut.isPending || isStreaming) && <Spinner size={12} />}
              Generate incident brief
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                esRef.current?.close();
                setForm(INITIAL_FORM);
                setQueued(null);
                setBriefText("");
                setStream(null);
                setStreamError(null);
              }}
            >
              Reset
            </Button>
          </div>
        </Card>

        <div style={{ marginTop: "14px", fontSize: "11.5px", color: "var(--text-faint)", lineHeight: 1.6 }}>
          This demo keeps retrieval deterministic and lets the model only write the operator-facing summary. It should never invent owners, endpoints, or remediation.
        </div>
      </aside>

      <main style={{ padding: "24px 24px 32px", overflow: "auto" }}>
        <div style={{ display: "grid", gap: "18px" }}>
          <div>
            <SectionLabel>Matched context</SectionLabel>
            <Card>
              <div style={{ padding: "14px 16px", display: "flex", flexWrap: "wrap", gap: "8px" }}>
                {(context?.matched_subjects ?? []).length > 0 ? (
                  context!.matched_subjects.map((subject) => (
                    <span
                      key={subject}
                      style={{
                        fontSize: "11px",
                        color: "var(--info)",
                        background: "var(--info-soft)",
                        borderRadius: "999px",
                        padding: "4px 10px",
                        fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
                      }}
                    >
                      {subject}
                    </span>
                  ))
                ) : (
                  <span style={{ fontSize: "12px", color: "var(--text-faint)" }}>No context yet. Submit a simulated alert to retrieve evidence.</span>
                )}
              </div>
            </Card>
          </div>

          <div>
            <SectionLabel>Owners / contacts</SectionLabel>
            <Card>
              <SummaryItem label="Owner team" value={summary?.owner_team ?? null} />
              <SummaryItem label="Tech lead" value={summary?.tech_lead ?? null} />
              <SummaryItem label="Point of contact" value={summary?.point_of_contact ?? null} />
            </Card>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "16px" }}>
            <FactList title="Endpoint / behavior" facts={[...(context?.endpoint_facts ?? []), ...(context?.behavior_facts ?? [])]} tone="info" />
            <FactList title="Structured bodies" facts={context?.body_facts ?? []} tone="muted" />
          </div>

          <div>
            <SectionLabel>Generated brief</SectionLabel>
            <Card style={{ border: "1px solid var(--accent-soft)" }}>
              <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--accent)" }} />
                <span style={{ fontSize: "12.5px", fontWeight: 600 }}>Model-written operator brief</span>
                {isStreaming && <span style={{ marginLeft: "auto" }}><Spinner size={12} /></span>}
              </div>
              <div style={{ padding: "16px", minHeight: "180px", whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "13px", lineHeight: 1.65, color: "var(--text)" }}>
                {generatedBrief || (isStreaming ? "Generating incident brief…" : "No generated brief yet.")}
              </div>
            </Card>
          </div>

          {streamError && <ErrorMsg message={streamError} />}
        </div>
      </main>
    </div>
  );
}
