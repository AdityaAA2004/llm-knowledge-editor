"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { EditJob, JobStatus, Triple } from "@/lib/types";
import { Spinner, ErrorMsg, MetaGrid, SectionLabel, Card } from "@/components/ui";

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

function toneOf(t: Triple): "ok" | "warn" | "danger" {
  if (t.pending_erasure) return "danger";
  if (!t.committed) return "warn";
  return "ok";
}
function labelOf(t: Triple) {
  if (t.pending_erasure) return "Pending Erasure";
  if (!t.committed) return "Pending";
  return "Committed";
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: job, isLoading, error } = useQuery<EditJob>({
    queryKey: ["job", id],
    queryFn: () => api.get<EditJob>(`/jobs/${id}`),
    refetchInterval: (q) => {
      const s = (q.state.data as EditJob | undefined)?.status;
      return s === "RUNNING" || s === "QUEUED" ? 2000 : false;
    },
  });

  const { data: allTriples } = useQuery<Triple[]>({
    queryKey: ["triples", "all"],
    queryFn: () => api.get<Triple[]>("/triples/"),
    enabled: !!job?.triple_ids?.length,
  });

  const cancelMut = useMutation({
    mutationFn: () => api.post(`/jobs/${id}/cancel`),
    onSuccess: () => {
      setActionError(null);
      qc.invalidateQueries({ queryKey: ["job", id] });
    },
    onError: (e) => {
      const msg = (e as Error).message;
      setActionError(
        msg.startsWith("409")
          ? "Job can no longer be cancelled — it has already finished."
          : `Cancel failed: ${msg}`
      );
      qc.invalidateQueries({ queryKey: ["job", id] });
    },
  });

  const rerunMut = useMutation({
    mutationFn: () => api.post<EditJob>(`/jobs/${id}/rerun`),
    onSuccess: (newJob) => {
      setActionError(null);
      qc.invalidateQueries({ queryKey: ["jobs"] });
      router.push(`/jobs/${newJob.id}`);
    },
    onError: (e) => setActionError(`Re-run failed: ${(e as Error).message}`),
  });

  if (isLoading) return <div style={{ display: "flex", justifyContent: "center", padding: "60px" }}><Spinner /></div>;
  if (error) return <div style={{ padding: "28px" }}><ErrorMsg message={(error as Error).message} /></div>;
  if (!job) return null;

  const sv = STATUS_VAR[job.status];
  const running = job.status === "RUNNING";
  const completed = job.status === "COMPLETED";
  const failed = job.status === "FAILED";
  const stages = STAGES[job.job_type] ?? [];
  const dur = completed && job.started_at && job.completed_at
    ? fmtDur(new Date(job.completed_at).getTime() - new Date(job.started_at).getTime())
    : running && job.started_at
    ? fmtDur(Date.now() - new Date(job.started_at).getTime())
    : "—";

  // compute stage states
  const progress = running ? 45 : completed ? 100 : failed ? 60 : 0;
  const stageIdx = Math.min(stages.length - 1, Math.floor((progress / 100) * stages.length));

  const metaItems = [
    { label: "Algorithm", value: { edit_rome: "ROME", edit_memit: "MEMIT", erase_elm: "ELM (LoRA)", rollback: "rollback" }[job.job_type] ?? job.job_type },
    { label: "Triples", value: String(job.triple_ids?.length ?? 0) },
    { label: "Duration", value: dur },
    { label: "Checkpoint", value: job.checkpoint_path ? "✓ saved" : failed ? "— none" : "pending" },
  ];

  const canCancel = job.status === "QUEUED" || job.status === "RUNNING";

  const jobTriples = job.triple_ids
    ? (allTriples ?? []).filter((t) => job.triple_ids!.includes(t.id))
    : [];

  return (
    <div style={{ maxWidth: "860px", padding: "24px 28px" }}>
      {/* Back */}
      <Link href="/jobs" style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--text-muted)", cursor: "pointer", marginBottom: "16px" }}>
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8 3 4.5 6.5 8 10" />
        </svg>
        All jobs
      </Link>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: "14px", marginBottom: "22px" }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "11px", marginBottom: "7px" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "7px", fontSize: "12px", fontWeight: 600, color: `var(--${sv})`, background: `var(--${sv}-soft)`, borderRadius: "20px", padding: "4px 12px" }}>
              {running && <span style={{ width: "11px", height: "11px", border: `1.6px solid var(--${sv})`, borderRightColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin .7s linear infinite" }} />}
              {job.status}
            </span>
            <span style={{ fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontSize: "11.5px", color: "var(--text-faint)" }}>{job.id}</span>
          </div>
          <div style={{ fontSize: "22px", fontWeight: 600, letterSpacing: "-0.3px" }}>{TYPE_LABELS[job.job_type] ?? job.job_type}</div>
          <div style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "3px" }}>
            {(job.triple_ids?.length ?? 0)} triple(s) · queue: model_writes · concurrency 1
          </div>
        </div>
        {canCancel && (
          <button
            onClick={() => cancelMut.mutate()}
            disabled={cancelMut.isPending}
            style={{ background: "transparent", color: "var(--danger)", border: "1px solid var(--danger-soft)", borderRadius: "8px", padding: "9px 14px", font: "500 12.5px 'IBM Plex Sans'", cursor: "pointer" }}
          >
            {cancelMut.isPending ? <Spinner size={12} /> : "Cancel job"}
          </button>
        )}
        {(completed || failed) && (
          <button
            onClick={() => rerunMut.mutate()}
            disabled={rerunMut.isPending}
            style={{ background: "var(--info)", color: "#fff", border: "1px solid var(--info)", borderRadius: "8px", padding: "9px 14px", font: "500 12.5px 'IBM Plex Sans'", cursor: "pointer" }}
          >
            {rerunMut.isPending ? <Spinner size={12} /> : "Run again"}
          </button>
        )}
      </div>

      {actionError && (
        <div style={{ marginBottom: "16px" }}>
          <ErrorMsg message={actionError} />
        </div>
      )}

      {/* Meta grid */}
      <div style={{ marginBottom: "20px" }}>
        <MetaGrid items={metaItems} />
      </div>

      {/* Progress bar for running */}
      {running && (
        <Card style={{ padding: "16px", marginBottom: "20px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "9px" }}>
            <span style={{ color: "var(--text-muted)" }}>{stages[stageIdx] ?? ""}</span>
            <span style={{ fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", color: "var(--info)" }}>{progress}%</span>
          </div>
          <div style={{ height: "7px", borderRadius: "4px", background: "var(--border)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${progress}%`, background: "var(--info)", borderRadius: "4px", transition: "width .45s ease" }} />
          </div>
        </Card>
      )}

      {/* Pipeline stages */}
      <SectionLabel>Pipeline</SectionLabel>
      <Card style={{ padding: "6px 16px", marginBottom: "22px" }}>
        {stages.map((label, i) => {
          const isDone = completed || (failed ? i < stageIdx : (running ? i < stageIdx : false));
          const isActive = (running && i === stageIdx);
          const isFailed = failed && i === stageIdx;
          const isPending = !isDone && !isActive && !isFailed;

          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "11px 0", borderBottom: i < stages.length - 1 ? "1px solid var(--border)" : "none" }}>
              <span style={{
                width: "18px", height: "18px", borderRadius: "50%", flex: "0 0 18px",
                display: "flex", alignItems: "center", justifyContent: "center",
                background: isDone ? "var(--ok-soft)" : isFailed ? "var(--danger-soft)" : "transparent",
                border: `1.5px solid ${isDone ? "var(--ok)" : isFailed ? "var(--danger)" : isActive ? "var(--info)" : "var(--border-strong)"}`,
              }}>
                {isActive ? (
                  <span style={{ width: "9px", height: "9px", border: "1.5px solid var(--info)", borderRightColor: "transparent", borderRadius: "50%", animation: "spin .7s linear infinite" }} />
                ) : (
                  <span style={{ color: isDone ? "var(--ok)" : isFailed ? "var(--danger)" : "transparent", fontSize: "10px" }}>
                    {isDone ? "✓" : isFailed ? "✕" : ""}
                  </span>
                )}
              </span>
              <span style={{ fontSize: "13px", color: isPending ? "var(--text-faint)" : "var(--text)", fontWeight: isActive ? 600 : 400 }}>
                {label}
              </span>
              {isDone && completed && i === stages.length - 1 && job.completed_at && (
                <span style={{ marginLeft: "auto", fontSize: "11.5px", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", color: "var(--text-faint)" }}>
                  {new Date(job.completed_at).toLocaleTimeString()}
                </span>
              )}
            </div>
          );
        })}
      </Card>

      {/* Error */}
      {job.error_message && (
        <div style={{ marginBottom: "22px" }}>
          <ErrorMsg message={job.error_message} />
        </div>
      )}

      {/* Affected triples */}
      {job.triple_ids && job.triple_ids.length > 0 && (
        <>
          <SectionLabel>Affected triples ({job.triple_ids.length})</SectionLabel>
          <Card>
            {job.triple_ids.map((tid) => {
              const t = jobTriples.find((x) => x.id === tid);
              if (!t) return (
                <div key={tid} style={{ display: "flex", alignItems: "center", gap: "10px", padding: "11px 15px", borderBottom: "1px solid var(--border)", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontSize: "12px" }}>
                  <span style={{ color: "var(--text-faint)" }}>{tid}</span>
                </div>
              );
              const tone = toneOf(t);
              return (
                <div key={tid} style={{ display: "flex", alignItems: "center", gap: "10px", padding: "11px 15px", borderBottom: "1px solid var(--border)", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontSize: "12px" }}>
                  <span>{t.subject}</span>
                  <span style={{ color: "var(--accent)" }}>{t.relation}</span>
                  <span style={{ color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{t.object}</span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontFamily: "var(--font-nunito),sans-serif", fontSize: "10.5px", fontWeight: 600, color: `var(--${tone})`, background: `var(--${tone}-soft)`, borderRadius: "20px", padding: "2px 9px" }}>
                    {labelOf(t)}
                  </span>
                </div>
              );
            })}
          </Card>
        </>
      )}
    </div>
  );
}
