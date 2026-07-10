"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { IncidentRecord } from "@/lib/types";
import { Spinner, ErrorMsg, StatusBadge } from "@/components/ui";

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

function fmtRel(ts: string) {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

export default function IncidentLogPage() {
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data: incidents, isLoading, error } = useQuery<IncidentRecord[]>({
    queryKey: ["incident-log"],
    queryFn: () => api.get<IncidentRecord[]>("/incident-log/"),
    refetchInterval: 5000,
  });

  const visible = [...(incidents ?? [])].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  return (
    <div style={{ maxWidth: "1080px", padding: "24px 28px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
        <h1 style={{ fontSize: "15px", fontWeight: 600 }}>Incidents</h1>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "7px", fontSize: "12px", color: "var(--text-muted)" }}>
          <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "var(--ok)", animation: "pulseDot 1.4s infinite" }} />
          Live · polling every 5s
        </div>
      </div>

      {isLoading && <div style={{ textAlign: "center", padding: "40px" }}><Spinner /></div>}
      {error && <ErrorMsg message={(error as Error).message} />}

      {visible.length === 0 && !isLoading && (
        <div style={{ textAlign: "center", padding: "60px 20px", fontSize: "13px", color: "var(--text-faint)" }}>
          No incidents detected yet. Auto-detected incidents from the error pipeline will appear here.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "9px" }}>
        {visible.map((inc) => {
          const isOpen = expanded === inc.id;
          return (
            <div
              key={inc.id}
              style={{
                background: "var(--surface)", border: "1px solid var(--border)",
                borderRadius: "11px", padding: "15px 17px", cursor: "pointer",
              }}
              onClick={() => setExpanded(isOpen ? null : inc.id)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <StatusBadge label={inc.severity.toUpperCase()} tone={SEVERITY_TONE[inc.severity] ?? "muted"} />
                <StatusBadge label={inc.status} tone={STATUS_TONE[inc.status] ?? "muted"} />
                <span style={{ fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontSize: "13px", fontWeight: 600 }}>
                  {inc.number}
                </span>
                <span style={{ fontSize: "12px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {inc.title}
                </span>
                <span style={{ marginLeft: "auto", fontSize: "12px", color: "var(--text-muted)" }}>
                  {inc.route_to_team ?? "unassigned"} · {inc.assigned_member ?? "unassigned"}
                </span>
                <span style={{ fontSize: "11.5px", color: "var(--text-faint)", minWidth: "74px", textAlign: "right" }}>
                  {fmtRel(inc.created_at)}
                </span>
              </div>

              {isOpen && (
                <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
                  <Link
                    href={`/incident-log/${inc.id}`}
                    onClick={(e) => e.stopPropagation()}
                    style={{ fontSize: "12px", color: "var(--info)" }}
                  >
                    View incident details →
                  </Link>
                  {inc.stack_trace && (
                    <pre style={{
                      margin: 0, fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace",
                      fontSize: "11.5px", color: "var(--danger)", background: "var(--danger-soft)",
                      borderRadius: "7px", padding: "10px 12px", whiteSpace: "pre-wrap", overflowX: "auto",
                    }}>
                      {inc.stack_trace.length > 800 ? inc.stack_trace.slice(0, 800) + " …(truncated)" : inc.stack_trace}
                    </pre>
                  )}
                  {inc.edit_job_id && (
                    <Link
                      href={`/jobs/${inc.edit_job_id}`}
                      onClick={(e) => e.stopPropagation()}
                      style={{ fontSize: "12px", color: "var(--info)" }}
                    >
                      View model-push job →
                    </Link>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
