"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { EditJob, JobStatus } from "@/lib/types";
import { Spinner, ErrorMsg, TabBar } from "@/components/ui";

type JFilter = "all" | "RUNNING" | "COMPLETED" | "FAILED";

const TYPE_LABELS: Record<string, string> = {
  edit_rome: "ROME edit",
  edit_memit: "MEMIT batch",
  erase_elm: "ELM erase",
  rollback: "Rollback",
};

const STATUS_VAR: Record<JobStatus, string> = {
  PENDING: "warn", QUEUED: "warn", RUNNING: "info", COMPLETED: "ok", FAILED: "danger",
};

const STAGES: Record<string, string[]> = {
  edit_rome: ["Queued", "Load triples", "Compute ROME edit", "Save checkpoint", "Done"],
  edit_memit: ["Queued", "Load triples", "Compute MEMIT batch", "Save checkpoint", "Done"],
  erase_elm: ["Queued", "Load concept", "Train ELM adapter", "Save checkpoint", "Done"],
  rollback: ["Queued", "Locate checkpoint", "Load weights", "Swap active", "Done"],
};

function fmtDur(ms: number) {
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}
function fmtRel(ts: string) {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

export default function JobsPage() {
  const [filter, setFilter] = useState<JFilter>("all");

  const { data: jobs, isLoading, error } = useQuery<EditJob[]>({
    queryKey: ["jobs"],
    queryFn: () => api.get<EditJob[]>("/jobs/"),
    refetchInterval: 3000,
  });

  const all = jobs ?? [];
  const counts = {
    all: all.length,
    RUNNING: all.filter((j) => j.status === "RUNNING" || j.status === "QUEUED").length,
    COMPLETED: all.filter((j) => j.status === "COMPLETED").length,
    FAILED: all.filter((j) => j.status === "FAILED").length,
  };

  const visible = [...all]
    .sort((a, b) => new Date(b.submitted_at).getTime() - new Date(a.submitted_at).getTime())
    .filter((j) => {
      if (filter === "all") return true;
      if (filter === "RUNNING") return j.status === "RUNNING" || j.status === "QUEUED";
      return j.status === filter;
    });

  const liveCount = counts.RUNNING;

  return (
    <div style={{ maxWidth: "1080px", padding: "24px 28px" }}>
      {/* Filter bar */}
      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
        <TabBar tabs={[
          { label: "All", count: counts.all, active: filter === "all", onClick: () => setFilter("all") },
          { label: "Running", count: counts.RUNNING, active: filter === "RUNNING", onClick: () => setFilter("RUNNING") },
          { label: "Completed", count: counts.COMPLETED, active: filter === "COMPLETED", onClick: () => setFilter("COMPLETED") },
          { label: "Failed", count: counts.FAILED, active: filter === "FAILED", onClick: () => setFilter("FAILED") },
        ]} />
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "7px", fontSize: "12px", color: "var(--text-muted)" }}>
          <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "var(--ok)", animation: liveCount > 0 ? "pulseDot 1.4s infinite" : "none" }} />
          Live · polling every 3s
        </div>
      </div>

      {isLoading && <div style={{ textAlign: "center", padding: "40px" }}><Spinner /></div>}
      {error && <ErrorMsg message={(error as Error).message} />}

      {visible.length === 0 && !isLoading && (
        <div style={{ textAlign: "center", padding: "60px 20px", fontSize: "13px", color: "var(--text-faint)" }}>
          No jobs yet. Push triples to model from the Triples page.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "9px" }}>
        {visible.map((j) => {
          const sv = STATUS_VAR[j.status];
          const running = j.status === "RUNNING";
          const stages = STAGES[j.job_type] ?? [];
          const pct = j.status === "COMPLETED" ? 100 : (j.status === "FAILED" ? (70) : 0);
          const stageIdx = Math.min(stages.length - 1, Math.floor((pct / 100) * stages.length));

          let timeLabel = "";
          if (j.status === "COMPLETED" && j.completed_at && j.started_at) {
            timeLabel = `${fmtDur(new Date(j.completed_at).getTime() - new Date(j.started_at).getTime())} · ${fmtRel(j.completed_at)}`;
          } else if (running && j.started_at) {
            timeLabel = `running ${fmtDur(Date.now() - new Date(j.started_at).getTime())}`;
          } else if (j.status === "FAILED") {
            timeLabel = `failed ${fmtRel(j.completed_at ?? j.submitted_at)}`;
          } else if (j.status === "QUEUED") {
            timeLabel = `queued ${fmtRel(j.submitted_at)}`;
          } else {
            timeLabel = fmtRel(j.submitted_at);
          }

          const summary = j.triple_ids?.length ? `${j.triple_ids.length} triple${j.triple_ids.length > 1 ? "s" : ""}` : "";

          return (
            <Link key={j.id} href={`/jobs/${j.id}`} style={{ textDecoration: "none" }}>
              <div style={{
                background: "var(--surface)", border: `1px solid ${running ? "var(--info-soft)" : "var(--border)"}`,
                borderRadius: "11px", padding: "15px 17px", cursor: "pointer", transition: "border-color .12s",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "7px", fontSize: "11.5px", fontWeight: 600, color: `var(--${sv})`, background: `var(--${sv}-soft)`, borderRadius: "20px", padding: "4px 11px", flex: "0 0 auto" }}>
                    {running ? (
                      <span style={{ width: "11px", height: "11px", border: `1.6px solid var(--${sv})`, borderRightColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin .7s linear infinite" }} />
                    ) : (
                      <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: `var(--${sv})` }} />
                    )}
                    {j.status}
                  </span>
                  <span style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: "13px", fontWeight: 600 }}>
                    {TYPE_LABELS[j.job_type] ?? j.job_type}
                  </span>
                  <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>{summary}</span>
                  <span style={{ marginLeft: "auto", fontFamily: "'IBM Plex Mono',monospace", fontSize: "11px", color: "var(--text-faint)" }}>{j.id.slice(0, 8)}…</span>
                  <span style={{ fontSize: "11.5px", color: "var(--text-faint)", minWidth: "74px", textAlign: "right" }}>{timeLabel}</span>
                </div>

                {running && (
                  <div style={{ marginTop: "12px", display: "flex", alignItems: "center", gap: "11px" }}>
                    <div style={{ flex: 1, height: "6px", borderRadius: "4px", background: "var(--border)", overflow: "hidden" }}>
                      <div style={{ height: "100%", width: "45%", background: "var(--info)", borderRadius: "4px", transition: "width .45s ease" }} />
                    </div>
                    <span style={{ fontSize: "11px", fontFamily: "'IBM Plex Mono',monospace", color: "var(--info)", minWidth: "90px" }}>{stages[stageIdx] ?? ""}</span>
                  </div>
                )}

                {j.error_message && (
                  <div style={{ marginTop: "11px", fontFamily: "'IBM Plex Mono',monospace", fontSize: "11.5px", color: "var(--danger)", background: "var(--danger-soft)", borderRadius: "7px", padding: "8px 11px" }}>
                    {j.error_message}
                  </div>
                )}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
