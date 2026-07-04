"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTheme } from "@/components/ThemeProvider";
import { api } from "@/lib/api";
import type { ModelStatus, Triple, EditJob } from "@/lib/types";

function NavSection({ label }: { label: string }) {
  return (
    <div style={{ fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.6px", color: "var(--text-faint)", textTransform: "uppercase", padding: "8px 10px 6px" }}>
      {label}
    </div>
  );
}

function NavItem({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      style={{
        display: "flex", alignItems: "center", gap: "11px",
        padding: "9px 10px", borderRadius: "8px", cursor: "pointer",
        color: active ? "var(--accent)" : "var(--text-muted)",
        background: active ? "var(--accent-soft)" : "transparent",
        fontWeight: active ? 600 : 500,
        fontSize: "13px",
        transition: "background .12s",
      }}
    >
      {children}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();

  const { data: status } = useQuery<ModelStatus>({
    queryKey: ["model-status"],
    queryFn: () => api.get<ModelStatus>("/model/status"),
    refetchInterval: 8000,
    staleTime: 5000,
    retry: false,
  });

  const { data: triples } = useQuery<Triple[]>({
    queryKey: ["triples", "all"],
    queryFn: () => api.get<Triple[]>("/triples/"),
    refetchInterval: 15000,
    staleTime: 10000,
    retry: false,
  });

  const { data: jobs } = useQuery<EditJob[]>({
    queryKey: ["jobs"],
    queryFn: () => api.get<EditJob[]>("/jobs/"),
    refetchInterval: 3000,
    staleTime: 2000,
    retry: false,
  });

  const pendingCount = triples?.filter((t) => !t.committed && !t.pending_erasure && !t.retrieval_only).length ?? 0;
  const activeJobs = jobs?.filter((j) => j.status === "RUNNING" || j.status === "QUEUED").length ?? 0;
  const modelOnline = status?.model_loaded ?? false;
  const activeCp = status?.active_checkpoint;
  const cpShort = activeCp ? activeCp.path.split("-").slice(-1)[0].replace(".bin", "") : "—";

  const isIncidents = pathname.startsWith("/incidents");
  const isKb = pathname.startsWith("/knowledge-base");
  const isTriples = pathname === "/triples";
  const isJobs = pathname.startsWith("/jobs");
  const isModel = pathname === "/model";
  const isChat = pathname.startsWith("/chat");

  return (
    <aside style={{
      width: "236px", flex: "0 0 236px",
      background: "var(--surface)", borderRight: "1px solid var(--border)",
      display: "flex", flexDirection: "column", height: "100vh",
    }}>
      {/* Logo */}
      <div style={{ padding: "18px 18px 14px", display: "flex", alignItems: "center", gap: "10px", borderBottom: "1px solid var(--border)" }}>
        <div style={{ width: "30px", height: "30px", borderRadius: "8px", background: "var(--accent)", display: "flex", alignItems: "center", justifyContent: "center", flex: "0 0 30px" }}>
          <svg width="17" height="17" viewBox="0 0 18 18" fill="none" stroke="var(--accent-fg)" strokeWidth="1.7">
            <rect x="4" y="4" width="10" height="10" rx="1.6" />
            <rect x="7" y="7" width="4" height="4" rx="0.6" />
            <path d="M9 1.4V4 M9 14V16.6 M1.4 9H4 M14 9H16.6" />
          </svg>
        </div>
        <div style={{ lineHeight: 1.1 }}>
          <div style={{ fontWeight: 600, fontSize: "13.5px", letterSpacing: "-0.1px" }}>SLM Knowledge</div>
          <div style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>Llama-3.2-3B</div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ padding: "12px", display: "flex", flexDirection: "column", gap: "2px", flex: 1 }}>
        <NavSection label="Operations" />

        <NavItem href="/incidents" active={isIncidents}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 2.2 15.2 14H2.8L9 2.2Z" />
            <path d="M9 6.3V10" />
            <path d="M9 12.6v.1" />
          </svg>
          Incidents
        </NavItem>

        <NavSection label="Authoring" />

        <NavItem href="/knowledge-base" active={isKb}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6">
            <rect x="2.5" y="3" width="13" height="3" rx="1" />
            <rect x="2.5" y="7.5" width="13" height="3" rx="1" />
            <rect x="2.5" y="12" width="13" height="3" rx="1" />
          </svg>
          Knowledge Base
        </NavItem>

        <NavItem href="/triples" active={isTriples}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="4" cy="5" r="2" />
            <circle cx="14" cy="5" r="2" />
            <circle cx="9" cy="14" r="2" />
            <path d="M5.9 5.2H12.1 M5.1 6.6 7.9 12.4 M12.9 6.6 10.1 12.4" />
          </svg>
          Triples
          {pendingCount > 0 && (
            <span style={{ marginLeft: "auto", fontSize: "11px", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", color: "var(--text-faint)" }}>
              {pendingCount}
            </span>
          )}
        </NavItem>

        <NavSection label="Model Ops" />

        <NavItem href="/jobs" active={isJobs}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round">
            <path d="M2 9H5.5L7.5 4L10.5 14L12.5 9H16" />
          </svg>
          Jobs
          {activeJobs > 0 && (
            <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: "5px", fontSize: "11px", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", color: "var(--info)" }}>
              <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--info)", animation: "pulseDot 1.2s infinite" }} />
              {activeJobs}
            </span>
          )}
        </NavItem>

        <NavItem href="/model" active={isModel}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6">
            <rect x="4" y="4" width="10" height="10" rx="1.6" />
            <rect x="7" y="7" width="4" height="4" rx="0.6" />
            <path d="M9 1.4V4 M9 14V16.6 M1.4 9H4 M14 9H16.6" />
          </svg>
          Model
        </NavItem>

        <NavSection label="Playground" />

        <NavItem href="/chat" active={isChat}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
            <path d="M2.5 4.5a1.5 1.5 0 0 1 1.5-1.5h10a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H7l-3.5 3v-3H4a1.5 1.5 0 0 1-1.5-1.5z" />
          </svg>
          Chat
        </NavItem>
      </nav>

      {/* Model status + theme toggle */}
      <div style={{ padding: "12px", borderTop: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: "8px" }}>
        {/* Theme toggle */}
        <button
          onClick={toggle}
          style={{
            display: "flex", alignItems: "center", gap: "7px",
            background: "var(--surface-2)", border: "1px solid var(--border)",
            borderRadius: "8px", padding: "7px 11px", cursor: "pointer",
            color: "var(--text)", fontSize: "12px", fontWeight: 500, width: "100%",
          }}
        >
          <span style={{ width: "13px", height: "13px", borderRadius: "50%", border: "2px solid var(--text-muted)", background: theme === "dark" ? "var(--text-muted)" : "transparent" }} />
          {theme === "light" ? "Dark mode" : "Light mode"}
        </button>

        {/* Model status widget */}
        <div style={{ background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "9px", padding: "11px 12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "7px", marginBottom: "8px" }}>
            <span style={{
              width: "7px", height: "7px", borderRadius: "50%",
              background: modelOnline ? "var(--ok)" : "var(--border-strong)",
              boxShadow: modelOnline ? "0 0 0 3px var(--ok-soft)" : "none",
            }} />
            <span style={{ fontSize: "12px", fontWeight: 600 }}>{modelOnline ? "Model online" : "Model offline"}</span>
            <span style={{ marginLeft: "auto", fontSize: "10.5px", color: "var(--text-faint)", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>cuda:0</span>
          </div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace", display: "flex", justifyContent: "space-between" }}>
            <span>active</span>
            <span style={{ color: "var(--text)" }}>{cpShort}</span>
          </div>
          <div style={{ marginTop: "8px", height: "5px", borderRadius: "3px", background: "var(--border)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: "28%", background: "var(--accent)", borderRadius: "3px" }} />
          </div>
          <div style={{ fontSize: "10.5px", color: "var(--text-faint)", marginTop: "5px", fontFamily: "var(--font-jetbrains-mono),'JetBrains Mono',monospace" }}>
            VRAM 6.8 GB / 24 GB
          </div>
        </div>
      </div>
    </aside>
  );
}
