"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Triple } from "@/lib/types";
import { Spinner, ErrorMsg, TabBar, Toast } from "@/components/ui";

type TFilter = "all" | "committed" | "pending" | "erasure";

function toneOf(t: Triple): "ok" | "warn" | "danger" | "muted" {
  if (t.pending_erasure) return "danger";
  if (t.retrieval_only) return "muted";
  if (!t.committed) return "warn";
  return "ok";
}
function labelOf(t: Triple) {
  if (t.pending_erasure) return "Pending Erasure";
  if (t.retrieval_only) return "Retrieval-only";
  if (!t.committed) return "Pending";
  return "Committed";
}

export default function TriplesPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const [filter, setFilter] = useState<TFilter>("all");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "warn" | "danger" | "info" | "muted" } | null>(null);

  const { data: triples, isLoading, error } = useQuery<Triple[]>({
    queryKey: ["triples", "all"],
    queryFn: () => api.get<Triple[]>("/triples/"),
    refetchInterval: 10000,
  });

  const pushMut = useMutation({
    mutationFn: (tripleIds: string[]) =>
      api.post("/jobs/edit", { triple_ids: tripleIds, job_type: "edit_memit" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["triples", "all"] });
      const count = sel.size;
      setSel(new Set());
      setToast({ msg: `MEMIT queued for ${count} triple(s)`, tone: "info" });
      setTimeout(() => router.push("/jobs"), 1200);
    },
    onError: (e) => setToast({ msg: (e as Error).message, tone: "danger" }),
  });

  const eraseMut = useMutation({
    mutationFn: () => {
      const ids = (triples ?? []).filter((t) => t.pending_erasure).map((t) => t.id);
      return api.post("/jobs/erase", { triple_ids: ids });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setToast({ msg: "ELM erasure queued", tone: "danger" });
    },
  });

  const all = triples ?? [];
  // Retrieval-only bodies are never committed and can't be pushed — treat them as a
  // distinct category rather than lumping them into "pending".
  const isPushable = (t: Triple) => !t.committed && !t.pending_erasure && !t.retrieval_only;
  const counts = {
    all: all.length,
    committed: all.filter((t) => t.committed && !t.pending_erasure).length,
    pending: all.filter(isPushable).length,
    erasure: all.filter((t) => t.pending_erasure).length,
  };

  function matches(t: Triple): boolean {
    if (filter === "all") return true;
    if (filter === "committed") return t.committed && !t.pending_erasure;
    if (filter === "pending") return isPushable(t);
    if (filter === "erasure") return !!t.pending_erasure;
    return false;
  }

  const visible = all.filter(matches);
  const selectable = visible.filter(isPushable);
  const allChecked = selectable.length > 0 && selectable.every((t) => sel.has(t.id));
  const selectedCount = sel.size;
  const canPush = selectedCount > 0;
  const erasureCount = all.filter((t) => t.pending_erasure).length;

  function toggleAll() {
    if (allChecked) setSel(new Set());
    else setSel(new Set(selectable.map((t) => t.id)));
  }
  function toggleOne(id: string, isSelectable: boolean) {
    if (!isSelectable) return;
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  const pushLabel = selectedCount >= 1 ? "Push to Model (MEMIT)" : "Push to Model";

  return (
    <div style={{ maxWidth: "1080px", padding: "24px 28px" }}>
      {/* Action bar */}
      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px", flexWrap: "wrap" }}>
        <TabBar tabs={[
          { label: "All", count: counts.all, active: filter === "all", onClick: () => setFilter("all") },
          { label: "Committed", count: counts.committed, active: filter === "committed", onClick: () => setFilter("committed"), dotTone: "ok" },
          { label: "Pending", count: counts.pending, active: filter === "pending", onClick: () => setFilter("pending"), dotTone: "warn" },
          { label: "Pending Erasure", count: counts.erasure, active: filter === "erasure", onClick: () => setFilter("erasure"), dotTone: "danger" },
        ]} />

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "10px" }}>
          {erasureCount > 0 && (
            <button
              onClick={() => eraseMut.mutate()}
              disabled={eraseMut.isPending}
              style={{
                display: "flex", alignItems: "center", gap: "8px",
                background: "transparent", color: "var(--danger)",
                border: "1px solid var(--danger)", borderRadius: "8px",
                padding: "9px 14px", font: "600 12.5px 'IBM Plex Sans'", cursor: "pointer",
              }}
            >
              {eraseMut.isPending && <Spinner size={12} />}
              Confirm erasure ({erasureCount})
            </button>
          )}
          <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{selectedCount} selected</div>
          <button
            onClick={() => canPush && pushMut.mutate(Array.from(sel))}
            disabled={!canPush || pushMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: "8px",
              background: canPush ? "var(--accent)" : "var(--border)",
              color: canPush ? "var(--accent-fg)" : "var(--text-faint)",
              border: "none", borderRadius: "8px", padding: "9px 16px",
              font: "600 12.5px 'IBM Plex Sans'", cursor: canPush ? "pointer" : "default",
            }}
          >
            {pushMut.isPending ? <Spinner size={12} /> : (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M7 11V3 M3.5 6.5 7 3 10.5 6.5" />
              </svg>
            )}
            {pushLabel}
          </button>
        </div>
      </div>

      {isLoading && <div style={{ textAlign: "center", padding: "40px" }}><Spinner /></div>}
      {error && <ErrorMsg message={(error as Error).message} />}

      {/* Table */}
      {triples && (
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "12px", overflow: "hidden" }}>
          {/* Header */}
          <div style={{ display: "grid", gridTemplateColumns: "38px 1.3fr 0.9fr 1.3fr 0.7fr 130px", gap: "12px", padding: "11px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface-2)", fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase", color: "var(--text-faint)" }}>
            <div onClick={toggleAll} style={{ cursor: "pointer", display: "flex", alignItems: "center" }}>
              <span style={{ width: "15px", height: "15px", borderRadius: "4px", border: "1.5px solid var(--border-strong)", display: "flex", alignItems: "center", justifyContent: "center", background: allChecked ? "var(--accent)" : "transparent", color: "var(--accent-fg)", fontSize: "10px" }}>
                {allChecked ? "✓" : ""}
              </span>
            </div>
            <div>Subject</div>
            <div>Relation</div>
            <div>Object</div>
            <div>Scope</div>
            <div>State</div>
          </div>

          {visible.length === 0 && (
            <div style={{ textAlign: "center", padding: "40px 20px", fontSize: "12px", color: "var(--text-faint)" }}>
              No triples match this filter.
            </div>
          )}

          {visible.map((t) => {
            const isSelectable = isPushable(t);
            const checked = sel.has(t.id);
            const tone = toneOf(t);
            return (
              <div
                key={t.id}
                onClick={() => toggleOne(t.id, isSelectable)}
                title={t.retrieval_only ? "Request/response body — served from Postgres via retrieval, never pushed to the model" : undefined}
                style={{
                  display: "grid", gridTemplateColumns: "38px 1.3fr 0.9fr 1.3fr 0.7fr 130px",
                  gap: "12px", padding: "12px 16px", borderBottom: "1px solid var(--border)",
                  alignItems: "center", background: checked ? "var(--accent-soft)" : "transparent",
                  cursor: isSelectable ? "pointer" : "default",
                }}
              >
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span style={{
                    width: "15px", height: "15px", borderRadius: "4px",
                    border: `1.5px solid ${checked ? "var(--accent)" : "var(--border-strong)"}`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: checked ? "var(--accent)" : "transparent",
                    color: "var(--accent-fg)", fontSize: "10px",
                    opacity: isSelectable ? 1 : 0.3,
                  }}>
                    {checked ? "✓" : ""}
                  </span>
                </div>
                <div style={{ fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontSize: "12.5px", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.subject}</div>
                <div style={{ fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontSize: "12px", color: "var(--accent)" }}>{t.relation}</div>
                <div style={{ fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontSize: "12.5px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.object}</div>
                <div style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>{t.scope}</div>
                <div>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "11px", fontWeight: 600, color: `var(--${tone})`, background: `var(--${tone}-soft)`, borderRadius: "20px", padding: "3px 10px" }}>
                    <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: `var(--${tone})` }} />
                    {labelOf(t)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ marginTop: "14px", fontSize: "12px", color: "var(--text-faint)", display: "flex", alignItems: "center", gap: "8px" }}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="7" cy="7" r="6" /><path d="M7 6.2V10 M7 4.2V4.3" />
        </svg>
        Selected triples are pushed as a <b style={{ margin: "0 3px", color: "var(--text-muted)" }}>MEMIT</b> batch edit (a single triple is a batch of one).
      </div>

      {toast && <Toast msg={toast.msg} tone={toast.tone} />}
    </div>
  );
}
