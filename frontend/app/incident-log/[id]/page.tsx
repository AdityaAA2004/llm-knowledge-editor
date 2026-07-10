"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { IncidentRecord } from "@/lib/types";
import { Spinner, ErrorMsg, StatusBadge, MetaGrid, SectionLabel, Card, Button } from "@/components/ui";

const SEVERITY_TONE: Record<string, "danger" | "warn" | "info" | "muted"> = {
  critical: "danger",
  high: "warn",
  medium: "info",
  low: "muted",
};

const STATUS_TONE: Record<string, "warn" | "info" | "ok"> = {
  OPEN: "warn",
  ACK: "info",
  RESOLVED: "ok",
};

function fmt(ts: string) {
  return new Date(ts).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function prettyJson(raw: string | null): string | null {
  if (!raw) return null;
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function BodyBlock({ label, raw, tone }: { label: string; raw: string | null; tone?: "danger" }) {
  const text = prettyJson(raw);
  if (!text) return null;
  return (
    <div>
      <SectionLabel>{label}</SectionLabel>
      <pre style={{
        margin: 0, fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
        fontSize: "11.5px", lineHeight: 1.55,
        color: tone === "danger" ? "var(--danger)" : "var(--text)",
        background: tone === "danger" ? "var(--danger-soft)" : "var(--surface-2)",
        border: "1px solid var(--border)", borderRadius: "8px", padding: "12px 14px",
        whiteSpace: "pre-wrap", wordBreak: "break-word", overflowX: "auto",
      }}>
        {text.length > 4000 ? text.slice(0, 4000) + " …(truncated)" : text}
      </pre>
    </div>
  );
}

export default function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();

  const { data: inc, isLoading, error } = useQuery<IncidentRecord>({
    queryKey: ["incident", id],
    queryFn: () => api.get<IncidentRecord>(`/incident-log/${id}`),
    refetchInterval: 5000,
  });

  const closeMut = useMutation({
    mutationFn: () => api.post<IncidentRecord>(`/incident-log/${id}/close`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incident", id] });
      qc.invalidateQueries({ queryKey: ["incident-log"] });
    },
  });

  if (isLoading) return <div style={{ textAlign: "center", padding: "60px" }}><Spinner /></div>;
  if (error) return <div style={{ padding: "24px 28px" }}><ErrorMsg message={(error as Error).message} /></div>;
  if (!inc) return null;

  return (
    <div style={{ maxWidth: "880px", padding: "24px 28px", display: "flex", flexDirection: "column", gap: "18px" }}>
      <div>
        <Link href="/incident-log" style={{ fontSize: "12px", color: "var(--text-muted)" }}>
          ← All incidents
        </Link>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "10px", flexWrap: "wrap" }}>
          <h1 style={{
            fontSize: "17px", fontWeight: 700, margin: 0,
            fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
          }}>
            {inc.number}
          </h1>
          <StatusBadge label={inc.severity.toUpperCase()} tone={SEVERITY_TONE[inc.severity] ?? "muted"} />
          <StatusBadge label={inc.status} tone={STATUS_TONE[inc.status] ?? "muted"} />
          {inc.status !== "RESOLVED" && (
            <div style={{ marginLeft: "auto" }}>
              <Button onClick={() => closeMut.mutate()} disabled={closeMut.isPending}>
                {closeMut.isPending ? "Closing…" : "Close incident"}
              </Button>
            </div>
          )}
        </div>
        <div style={{ fontSize: "13.5px", color: "var(--text)", marginTop: "8px", lineHeight: 1.5 }}>
          {inc.title}
        </div>
        {closeMut.error && <div style={{ marginTop: "8px" }}><ErrorMsg message={(closeMut.error as Error).message} /></div>}
      </div>

      <Card>
        <MetaGrid
          items={[
            { label: "Routed to team", value: inc.route_to_team ?? "unassigned" },
            { label: "Assigned member", value: inc.assigned_member ?? "unassigned" },
            { label: "HTTP status", value: inc.status_code != null ? String(inc.status_code) : "—" },
            { label: "Created", value: fmt(inc.created_at) },
            { label: "Updated", value: fmt(inc.updated_at) },
          ]}
        />
      </Card>

      <BodyBlock label="Stack trace" raw={inc.stack_trace} tone="danger" />
      <BodyBlock label="Request body" raw={inc.request_body} />
      <BodyBlock label="Response body" raw={inc.response_body} />

      {inc.edit_job_id && (
        <Link href={`/jobs/${inc.edit_job_id}`} style={{ fontSize: "12.5px", color: "var(--info)" }}>
          View model-push job →
        </Link>
      )}
    </div>
  );
}
