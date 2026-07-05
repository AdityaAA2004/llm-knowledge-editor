"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  IncidentBriefQueuedResponse,
  IncidentContext,
  IncidentBriefRequest,
  IncidentConfidence,
  IncidentLikelyMatch,
  IncidentSeverity,
} from "@/lib/types";
import { Button, Card, ErrorMsg, FieldInput, MonoBadge, SectionLabel, Spinner, StatusBadge } from "@/components/ui";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const INITIAL_FORM: IncidentBriefRequest = {
  title: "Payments API 5xx spike",
  severity: "high",
  signal_source: "synthetic monitor",
  service_hint: "Payment Mgmt Team",
  api_hint: "Payments API",
  http_method: "POST",
  path: "/v1/payments",
  symptom: "POST /v1/payments is returning elevated 5xx responses and latency is spiking after a recent deploy.",
};

const SEVERITIES: IncidentSeverity[] = ["low", "medium", "high", "critical"];

type StreamState = {
  requestId: string;
};

function confidenceTone(confidence: IncidentConfidence): "ok" | "warn" | "danger" {
  if (confidence === "high") return "ok";
  if (confidence === "medium") return "warn";
  return "danger";
}

function SummaryItem({ label, value, emphasize = false }: { label: string; value: string | null; emphasize?: boolean }) {
  return (
    <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
      <div style={{ fontSize: "10.5px", textTransform: "uppercase", letterSpacing: "0.45px", color: "var(--text-faint)", marginBottom: "4px" }}>
        {label}
      </div>
      <div
        style={{
          fontSize: emphasize ? "14px" : "13px",
          fontWeight: emphasize && value ? 600 : 400,
          color: value ? "var(--text)" : "var(--text-faint)",
          fontFamily: value ? "inherit" : "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
        }}
      >
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

function LikelyMatchCard({ match, rank }: { match: IncidentLikelyMatch; rank: number }) {
  const tone = confidenceTone(match.confidence);
  return (
    <Card>
      <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "9px" }}>
        <MonoBadge label={`#${rank}`} tone="accent" />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {match.subject}
          </div>
          <div style={{ fontSize: "10.5px", color: "var(--text-faint)", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>
            {match.source_type} · {match.top_relation} · score {match.score}
          </div>
        </div>
        <StatusBadge label={match.confidence} tone={tone} />
      </div>
      <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", fontSize: "12px", lineHeight: 1.6, color: "var(--text-muted)" }}>
        {match.fact_preview}
      </div>
      <div style={{ padding: "12px 14px", display: "flex", flexWrap: "wrap", gap: "6px" }}>
        {match.reasons.map((reason) => (
          <span
            key={`${match.subject}-${reason}`}
            style={{
              fontSize: "10.5px",
              color: "var(--text-muted)",
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: "999px",
              padding: "3px 8px",
            }}
          >
            {reason}
          </span>
        ))}
      </div>
      <div style={{ padding: "10px 14px", borderTop: "1px solid var(--border)", background: "var(--surface-2)", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px", fontSize: "10.5px", color: "var(--text-faint)" }}>
        <div>committed: <span style={{ color: "var(--text)" }}>{match.committed_facts}</span></div>
        <div>pending push: <span style={{ color: "var(--text)" }}>{match.pending_facts}</span></div>
        <div>retrieval-only: <span style={{ color: "var(--text)" }}>{match.retrieval_only_facts}</span></div>
      </div>
    </Card>
  );
}

function fmtFreshness(value: string | null): string {
  if (!value) return "unknown";
  return new Date(value).toLocaleString();
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

  const context: IncidentContext | null = queued?.context ?? null;
  const summary = context?.deterministic_summary ?? null;
  const routing = context?.routing_recommendation ?? null;
  const knowledge = context?.knowledge_status ?? null;
  const likelyMatches = context?.likely_matches ?? [];
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
        setStreamError(data.message ?? "Triage pack generation failed.");
      }
    };

    es.onerror = () => {
      es.close();
      setStream(null);
      setStreamError("Lost connection to the triage stream.");
    };
  }

  const generatedBrief = useMemo(() => briefText, [briefText]);

  return (
    <div style={{ height: "100%", minHeight: 0, display: "grid", gridTemplateColumns: "390px minmax(0, 1fr)" }}>
      <aside style={{ borderRight: "1px solid var(--border)", background: "var(--surface)", padding: "24px 20px", overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
          <MonoBadge label="TRIAGE" tone="accent" />
          <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Operational triage assistant</span>
        </div>
        <div style={{ fontSize: "13px", lineHeight: 1.65, color: "var(--text-muted)", marginBottom: "18px" }}>
          Simulate a production alert, rank the most likely targets, route it to the right team, and generate a short triage pack grounded in exact KB facts.
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
            <Button onClick={() => submitMut.mutate(form)} disabled={submitMut.isPending || isStreaming}>
              {(submitMut.isPending || isStreaming) && <Spinner size={12} />}
              Run triage
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
          This view makes the hybrid contract explicit: retrieval and routing stay deterministic, while the model only writes the operator-facing triage pack.
        </div>
      </aside>

      <main style={{ padding: "24px 24px 32px", overflow: "auto" }}>
        <div style={{ display: "grid", gap: "18px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1.15fr 0.85fr", gap: "16px" }}>
            <Card>
              <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--accent)" }} />
                <span style={{ fontSize: "12.5px", fontWeight: 600 }}>Routing recommendation</span>
                {routing && <span style={{ marginLeft: "auto" }}><StatusBadge label={routing.confidence} tone={confidenceTone(routing.confidence)} /></span>}
              </div>
              <SummaryItem label="Primary target" value={routing?.primary_subject ?? null} emphasize />
              <SummaryItem label="Route to team" value={routing?.route_to_team ?? null} />
              <SummaryItem label="Page/contact first" value={routing?.page_contact ?? null} />
              <SummaryItem label="First check" value={routing?.first_check ?? null} />
              <div style={{ padding: "12px 14px" }}>
                <div style={{ fontSize: "10.5px", textTransform: "uppercase", letterSpacing: "0.45px", color: "var(--text-faint)", marginBottom: "8px" }}>
                  Why this route
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  {(routing?.rationale ?? []).length > 0 ? (
                    routing!.rationale.map((reason) => (
                      <span
                        key={reason}
                        style={{
                          fontSize: "10.5px",
                          color: "var(--text-muted)",
                          background: "var(--surface-2)",
                          border: "1px solid var(--border)",
                          borderRadius: "999px",
                          padding: "3px 8px",
                        }}
                      >
                        {reason}
                      </span>
                    ))
                  ) : (
                    <span style={{ fontSize: "12px", color: "var(--text-faint)" }}>No routing rationale yet.</span>
                  )}
                </div>
              </div>
            </Card>

            <Card>
              <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--info)" }} />
                <span style={{ fontSize: "12.5px", fontWeight: 600 }}>Knowledge status</span>
              </div>
              <SummaryItem label="Matched facts" value={knowledge ? String(knowledge.matched_fact_count) : null} emphasize />
              <SummaryItem label="Already pushed to model" value={knowledge ? String(knowledge.committed_fact_count) : null} />
              <SummaryItem label="Still pending push" value={knowledge ? String(knowledge.pending_fact_count) : null} />
              <SummaryItem label="Retrieval-only facts" value={knowledge ? String(knowledge.retrieval_only_fact_count) : null} />
              <SummaryItem label="Freshest fact update" value={knowledge ? fmtFreshness(knowledge.freshest_fact_at) : null} />
              <div style={{ padding: "12px 14px", borderTop: "1px solid var(--border)", fontSize: "11.5px", lineHeight: 1.6, color: "var(--text-faint)" }}>
                Committed and pending facts are the part ROME or MEMIT can change immediately. Retrieval-only facts stay outside the edited model and are injected at triage time.
              </div>
            </Card>
          </div>

          <Card>
            <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--warn)" }} />
              <span style={{ fontSize: "12.5px", fontWeight: 600 }}>Matched context</span>
            </div>
            <div style={{ padding: "14px", display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {(context?.matched_subjects ?? []).length > 0 ? (
                context!.matched_subjects.map((subject) => (
                  <span
                    key={subject}
                    style={{
                      fontSize: "11px",
                      color: "var(--text)",
                      background: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      borderRadius: "999px",
                      padding: "5px 9px",
                      fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
                    }}
                  >
                    {subject}
                  </span>
                ))
              ) : (
                <span style={{ fontSize: "12px", color: "var(--text-faint)" }}>
                  Submit a simulated alert to see which KB subjects are being used for routing and summary generation.
                </span>
              )}
            </div>
          </Card>

          <div>
            <SectionLabel>Ranked likely matches</SectionLabel>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "16px" }}>
              {likelyMatches.length > 0 ? (
                likelyMatches.map((match, idx) => (
                  <LikelyMatchCard key={`${match.subject}-${idx}`} match={match} rank={idx + 1} />
                ))
              ) : (
                <Card>
                  <div style={{ padding: "16px", fontSize: "12px", color: "var(--text-faint)" }}>
                    No triage candidates yet. Submit a simulated alert to rank likely targets.
                  </div>
                </Card>
              )}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "16px" }}>
            <FactList title="Ownership / escalation evidence" facts={context?.ownership_facts ?? []} tone="ok" />
            <FactList title="Endpoint / behavior evidence" facts={[...(context?.endpoint_facts ?? []), ...(context?.behavior_facts ?? [])]} tone="info" />
          </div>

          <FactList title="Structured bodies (retrieval-only exact facts)" facts={context?.body_facts ?? []} tone="muted" />

          <FactList title="Incident evidence (from auto-detected incidents)" facts={context?.incident_facts ?? []} tone="warn" />

          <div>
            <SectionLabel>Model-written triage pack</SectionLabel>
            <Card style={{ border: "1px solid var(--accent-soft)" }}>
              <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--accent)" }} />
                <span style={{ fontSize: "12.5px", fontWeight: 600 }}>Operator summary grounded in the exact facts above</span>
                {isStreaming && <span style={{ marginLeft: "auto" }}><Spinner size={12} /></span>}
              </div>
              <div style={{ padding: "16px", minHeight: "180px", whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "13px", lineHeight: 1.65, color: "var(--text)" }}>
                {generatedBrief || (isStreaming ? "Generating triage pack…" : "No triage pack yet.")}
              </div>
            </Card>
          </div>

          {streamError && <ErrorMsg message={streamError} />}

          {summary && (
            <Card>
              <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--warn)" }} />
                <span style={{ fontSize: "12.5px", fontWeight: 600 }}>Operational summary snapshot</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
                <SummaryItem label="Owner team" value={summary.owner_team} />
                <SummaryItem label="API name" value={summary.api_name} />
                <SummaryItem label="Endpoint" value={summary.endpoint} />
                <SummaryItem label="Tech lead" value={summary.tech_lead} />
                <SummaryItem label="Point of contact" value={summary.point_of_contact} />
                <SummaryItem label="Business function" value={summary.business_function} />
              </div>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}
