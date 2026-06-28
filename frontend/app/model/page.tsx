"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { ModelStatus, ModelCheckpoint } from "@/lib/types";
import { Spinner, SectionLabel, Card, Toast, MetaGrid } from "@/components/ui";

function fmtRel(ts: string) {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

export default function ModelPage() {
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "warn" | "info" | "danger" | "muted" } | null>(null);

  const { data: status, isLoading: statusLoading } = useQuery<ModelStatus>({
    queryKey: ["model-status"],
    queryFn: () => api.get<ModelStatus>("/model/status"),
    refetchInterval: 5000,
    retry: false,
  });

  const { data: checkpoints, isLoading: cpLoading } = useQuery<ModelCheckpoint[]>({
    queryKey: ["checkpoints"],
    queryFn: () => api.get<ModelCheckpoint[]>("/model/checkpoints/"),
    refetchInterval: 5000,
    retry: false,
  });

  const rollbackMut = useMutation({
    mutationFn: (checkpoint_id: string) => api.post("/model/rollback", { checkpoint_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["checkpoints"] });
      qc.invalidateQueries({ queryKey: ["model-status"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setToast({ msg: "Rollback queued → job dispatched", tone: "info" });
    },
    onError: (e) => setToast({ msg: (e as Error).message, tone: "danger" }),
  });

  const reloadMut = useMutation({
    mutationFn: () => api.post("/model/reload"),
    onSuccess: () => setToast({ msg: "Reload triggered — active checkpoint loading into VRAM", tone: "info" }),
  });

  const cpSorted = [...(checkpoints ?? [])].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  const modelOnline = status?.model_loaded ?? false;

  const modelMeta = [
    { label: "Device", value: "RTX 3090" },
    { label: "Precision", value: "fp16" },
    { label: "Parameters", value: "3.2 B" },
    { label: "Edit layers", value: "[4–8].mlp" },
  ];

  return (
    <div style={{ maxWidth: "980px", padding: "24px 28px" }}>
      {/* Model status card */}
      <Card style={{ padding: "20px 22px", marginBottom: "22px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "18px" }}>
          <span style={{
            width: "9px", height: "9px", borderRadius: "50%",
            background: modelOnline ? "var(--ok)" : "var(--border-strong)",
            boxShadow: modelOnline ? "0 0 0 4px var(--ok-soft)" : "none",
          }} />
          <span style={{ fontSize: "16px", fontWeight: 600 }}>meta-llama/Llama-3.2-3B</span>
          {statusLoading ? (
            <Spinner size={14} />
          ) : (
            <span style={{ fontSize: "11px", fontWeight: 600, color: "var(--ok)", background: "var(--ok-soft)", borderRadius: "20px", padding: "3px 10px" }}>
              {modelOnline ? "Loaded · fp16" : "Offline"}
            </span>
          )}
          <button
            onClick={() => reloadMut.mutate()}
            disabled={reloadMut.isPending}
            style={{ marginLeft: "auto", background: "transparent", border: "1px solid var(--border-strong)", borderRadius: "8px", padding: "7px 13px", font: "500 12px 'IBM Plex Sans'", color: "var(--text)", cursor: "pointer" }}
          >
            {reloadMut.isPending ? <Spinner size={12} /> : "Reload weights"}
          </button>
        </div>

        <MetaGrid items={modelMeta} />

        <div style={{ marginTop: "18px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--text-muted)", marginBottom: "6px" }}>
            <span>GPU memory</span>
            <span style={{ fontFamily: "'IBM Plex Mono',monospace" }}>6.8 GB / 24 GB</span>
          </div>
          <div style={{ height: "8px", borderRadius: "5px", background: "var(--border)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: "28%", background: "var(--accent)", borderRadius: "5px" }} />
          </div>
        </div>
      </Card>

      {/* Checkpoint history */}
      <div style={{ display: "flex", alignItems: "center", marginBottom: "12px" }}>
        <SectionLabel>Checkpoint history</SectionLabel>
        <span style={{ marginLeft: "9px", fontSize: "11px", color: "var(--text-faint)", fontFamily: "'IBM Plex Mono',monospace" }}>
          {cpSorted.length} checkpoints · /data/checkpoints
        </span>
      </div>

      {cpLoading && <div style={{ textAlign: "center", padding: "30px" }}><Spinner /></div>}

      <Card>
        {cpSorted.length === 0 && !cpLoading && (
          <div style={{ textAlign: "center", padding: "40px 20px", fontSize: "13px", color: "var(--text-faint)" }}>
            No checkpoints yet. Run a model edit job first.
          </div>
        )}
        {cpSorted.map((cp) => (
          <div key={cp.id} style={{ display: "flex", alignItems: "center", gap: "14px", padding: "15px 18px", borderBottom: "1px solid var(--border)", background: cp.is_active ? "var(--ok-soft)" : "transparent" }}>
            <span style={{
              width: "9px", height: "9px", borderRadius: "50%", flex: "0 0 9px",
              background: cp.is_active ? "var(--ok)" : "var(--border-strong)",
              boxShadow: cp.is_active ? "0 0 0 4px var(--ok-soft)" : "none",
            }} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "9px" }}>
                <span style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: "13px", fontWeight: 600 }}>
                  cp-{cp.path.split("-").slice(-1)[0].replace(".bin", "")}
                </span>
                {cp.is_active && (
                  <span style={{ fontSize: "10px", fontWeight: 700, color: "var(--ok)", background: "var(--ok-soft)", borderRadius: "20px", padding: "2px 9px", letterSpacing: "0.3px" }}>
                    ACTIVE
                  </span>
                )}
              </div>
              <div style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: "11px", color: "var(--text-faint)", marginTop: "3px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {cp.path}
              </div>
            </div>
            <div style={{ textAlign: "right", flex: "0 0 auto" }}>
              <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{fmtRel(cp.created_at)}</div>
              {cp.job_id && (
                <div style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "'IBM Plex Mono',monospace" }}>{cp.job_id.slice(0, 8)}…</div>
              )}
            </div>
            {cp.is_active ? (
              <span style={{ flex: "0 0 auto", fontSize: "12px", color: "var(--text-faint)", padding: "7px 13px" }}>Current</span>
            ) : (
              <button
                onClick={() => rollbackMut.mutate(cp.id)}
                disabled={rollbackMut.isPending}
                style={{ flex: "0 0 auto", background: "transparent", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: "8px", padding: "7px 13px", font: "500 12px 'IBM Plex Sans'", cursor: "pointer" }}
              >
                {rollbackMut.isPending ? <Spinner size={12} /> : "Roll back"}
              </button>
            )}
          </div>
        ))}
      </Card>

      <div style={{ marginTop: "14px", fontSize: "12px", color: "var(--text-faint)", display: "flex", alignItems: "center", gap: "8px" }}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="7" cy="7" r="6" /><path d="M7 6.2V10 M7 4.2V4.3" />
        </svg>
        Every successful edit writes a full ~6.8 GB checkpoint. Rolling back loads a past checkpoint and rewinds the committed state of its triples.
      </div>

      {toast && <Toast msg={toast.msg} tone={toast.tone} />}
    </div>
  );
}
