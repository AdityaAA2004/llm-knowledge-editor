"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ModelStatus } from "@/lib/types";

const PAGE_META: Record<string, { title: string }> = {
  "/incidents": { title: "Incidents" },
  "/knowledge-base": { title: "Knowledge Base" },
  "/triples": { title: "Triples" },
  "/jobs": { title: "Jobs" },
  "/model": { title: "Model" },
  "/chat": { title: "Chat" },
};

export function Topbar() {
  const pathname = usePathname();

  const { data: status } = useQuery<ModelStatus>({
    queryKey: ["model-status"],
    queryFn: () => api.get<ModelStatus>("/model/status"),
    refetchInterval: 8000,
    staleTime: 5000,
    retry: false,
  });

  const activeCp = status?.active_checkpoint;
  const cpShort = activeCp ? activeCp.path.split("-").slice(-1)[0].replace(".bin", "") : "—";

  const isJobDetail = pathname.startsWith("/jobs/") && pathname !== "/jobs";
  const baseKey = isJobDetail ? "/jobs" : pathname;
  const meta = PAGE_META[baseKey] ?? { title: "SLM Platform" };
  const title = isJobDetail ? "Job detail" : meta.title;

  return (
    <header style={{
      height: "56px", flex: "0 0 56px",
      borderBottom: "1px solid var(--border)", background: "var(--surface)",
      display: "flex", alignItems: "center", padding: "0 22px", gap: "14px",
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: "15px", fontWeight: 600, letterSpacing: "-0.2px", lineHeight: 1.3 }}>{title}</div>
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "10px" }}>
        <Link
          href="/model"
          style={{
            display: "flex", alignItems: "center", gap: "8px",
            background: "var(--surface-2)", border: "1px solid var(--border)",
            borderRadius: "8px", padding: "6px 11px", cursor: "pointer",
          }}
        >
          <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>active checkpoint</span>
          <span style={{ fontSize: "11.5px", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", fontWeight: 600 }}>{cpShort}</span>
        </Link>
      </div>
    </header>
  );
}
