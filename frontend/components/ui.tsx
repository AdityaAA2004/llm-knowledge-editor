"use client";

import { ReactNode, CSSProperties, useState, useEffect } from "react";

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span style={{
      display: "inline-block", width: size, height: size,
      border: "1.6px solid currentColor", borderRightColor: "transparent",
      borderRadius: "50%", animation: "spin .7s linear infinite",
    }} />
  );
}

export function ErrorMsg({ message }: { message: string }) {
  return (
    <div style={{
      background: "var(--danger-soft)", border: "1px solid var(--danger-soft)",
      borderLeft: "3px solid var(--danger)", borderRadius: "8px",
      padding: "10px 13px", fontSize: "13px", color: "var(--danger)",
    }}>
      {message}
    </div>
  );
}

type StatusDot = "ok" | "warn" | "danger" | "info" | "muted";

export function StatusBadge({ label, tone }: { label: string; tone: StatusDot }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "6px",
      fontSize: "11px", fontWeight: 600,
      color: `var(--${tone})`,
      background: `var(--${tone}-soft)`,
      borderRadius: "20px", padding: "3px 10px",
    }}>
      <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: `var(--${tone})` }} />
      {label}
    </span>
  );
}

export function MonoBadge({ label, tone = "muted" }: { label: string; tone?: StatusDot | "accent" }) {
  const bg = tone === "accent" ? "var(--accent-soft)" : `var(--${tone}-soft)`;
  const color = tone === "accent" ? "var(--accent)" : `var(--${tone})`;
  return (
    <span style={{
      fontSize: "10.5px", fontWeight: 600, fontFamily: "'IBM Plex Mono',monospace",
      letterSpacing: "0.4px", color, background: bg,
      borderRadius: "4px", padding: "1px 4px", border: `1px solid var(--border)`,
    }}>
      {label}
    </span>
  );
}

export function Button({
  children, onClick, disabled, variant = "primary", size = "md", type = "button", style: extraStyle,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
  type?: "button" | "submit";
  style?: CSSProperties;
}) {
  const base: CSSProperties = {
    display: "inline-flex", alignItems: "center", gap: "6px",
    borderRadius: "8px", fontWeight: 600, cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.5 : 1, border: "none", fontFamily: "inherit",
    fontSize: size === "sm" ? "12px" : "12.5px",
    padding: size === "sm" ? "6px 11px" : "9px 16px",
  };
  const variants: Record<string, CSSProperties> = {
    primary: { background: "var(--accent)", color: "var(--accent-fg)" },
    secondary: { background: "transparent", color: "var(--text)", border: "1px solid var(--border-strong)" },
    danger: { background: "transparent", color: "var(--danger)", border: "1px solid var(--danger-soft)" },
    ghost: { background: "transparent", color: "var(--text-muted)", border: "none", fontWeight: 500 },
  };
  return (
    <button type={type} onClick={disabled ? undefined : onClick} style={{ ...base, ...variants[variant], ...extraStyle }}>
      {children}
    </button>
  );
}

export function FieldInput({
  label, value, onChange, placeholder, multiline, required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  multiline?: boolean;
  required?: boolean;
}) {
  const inputStyle: CSSProperties = {
    width: "100%", background: "var(--surface-2)", border: "1px solid var(--border)",
    borderRadius: "8px", padding: "9px 11px",
    fontSize: multiline ? "12.5px" : "13px", lineHeight: multiline ? "1.5" : "1.4",
    color: "var(--text)", outline: "none",
    fontFamily: multiline ? "'IBM Plex Mono',monospace" : "inherit",
    resize: multiline ? "vertical" : "none",
  };
  return (
    <div>
      <label style={{ display: "block", fontSize: "11.5px", fontWeight: 500, color: "var(--text-muted)", marginBottom: "6px" }}>
        {label}{required && <span style={{ color: "var(--danger)", marginLeft: "2px" }}>*</span>}
      </label>
      {multiline ? (
        <textarea
          rows={3}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          style={inputStyle}
        />
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          required={required}
          style={inputStyle}
        />
      )}
    </div>
  );
}

export function JsonField({
  label, value, onChange, placeholder, rows = 6,
}: {
  label: string;
  value: Record<string, unknown> | null;
  onChange: (v: Record<string, unknown> | null) => void;
  placeholder?: string;
  rows?: number;
}) {
  const [raw, setRaw] = useState(() => value ? JSON.stringify(value, null, 2) : "");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setRaw(value ? JSON.stringify(value, null, 2) : "");
  }, []);  // sync only on mount; parent owns the value after that

  function handleChange(text: string) {
    setRaw(text);
    if (!text.trim()) {
      setErr(null);
      onChange(null);
      return;
    }
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Must be a JSON object");
      setErr(null);
      onChange(parsed as Record<string, unknown>);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", marginBottom: "6px", gap: "8px" }}>
        <label style={{ fontSize: "11.5px", fontWeight: 500, color: "var(--text-muted)" }}>{label}</label>
        {err ? (
          <span style={{ fontSize: "11px", color: "var(--danger)", fontFamily: "'IBM Plex Mono',monospace" }}>invalid JSON</span>
        ) : raw.trim() ? (
          <span style={{ fontSize: "11px", color: "var(--ok)", fontFamily: "'IBM Plex Mono',monospace" }}>✓ valid</span>
        ) : null}
      </div>
      <textarea
        rows={rows}
        value={raw}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder ?? '{\n  "key": "value"\n}'}
        style={{
          width: "100%", background: "var(--surface-2)",
          border: `1px solid ${err ? "var(--danger)" : "var(--border)"}`,
          borderRadius: "8px", padding: "9px 11px", fontSize: "12.5px",
          lineHeight: "1.5", color: "var(--text)", outline: "none",
          fontFamily: "'IBM Plex Mono',monospace", resize: "vertical",
        }}
      />
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{
      fontSize: "12px", fontWeight: 600, color: "var(--text-muted)",
      textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: "10px",
    }}>
      {children}
    </div>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: "12px", overflow: "hidden", ...style,
    }}>
      {children}
    </div>
  );
}

export function MetaGrid({ items }: { items: { label: string; value: string }[] }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: `repeat(${items.length},1fr)`,
      gap: "1px", background: "var(--border)", border: "1px solid var(--border)",
      borderRadius: "11px", overflow: "hidden",
    }}>
      {items.map((m) => (
        <div key={m.label} style={{ background: "var(--surface)", padding: "13px 15px" }}>
          <div style={{ fontSize: "10.5px", textTransform: "uppercase", letterSpacing: "0.4px", color: "var(--text-faint)", marginBottom: "5px" }}>{m.label}</div>
          <div style={{ fontSize: "13.5px", fontWeight: 600, fontFamily: "'IBM Plex Mono',monospace" }}>{m.value}</div>
        </div>
      ))}
    </div>
  );
}

export function TabBar({ tabs }: {
  tabs: { label: string; count?: number; active: boolean; onClick: () => void; dotTone?: StatusDot }[];
}) {
  return (
    <div style={{ display: "flex", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "8px", padding: "3px" }}>
      {tabs.map((t) => (
        <div
          key={t.label}
          onClick={t.onClick}
          style={{
            padding: "6px 12px", borderRadius: "6px", fontSize: "12px",
            fontWeight: t.active ? 600 : 500, cursor: "pointer",
            background: t.active ? "var(--accent-soft)" : "transparent",
            color: t.active ? "var(--accent)" : "var(--text-muted)",
            display: "flex", alignItems: "center", gap: "6px",
          }}
        >
          {t.dotTone && (
            <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: `var(--${t.dotTone})` }} />
          )}
          {t.label}
          {t.count !== undefined && (
            <span style={{ opacity: 0.55, fontFamily: "'IBM Plex Mono',monospace", fontSize: "11px" }}>
              {t.count}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export function Toast({ msg, tone }: { msg: string; tone: StatusDot }) {
  return (
    <div style={{
      position: "fixed", bottom: "22px", left: "50%", transform: "translateX(-50%)",
      zIndex: 60, background: "var(--surface)", border: "1px solid var(--border)",
      borderLeft: `3px solid var(--${tone})`, borderRadius: "10px",
      boxShadow: "var(--shadow)", padding: "13px 18px",
      display: "flex", alignItems: "center", gap: "11px",
      animation: "fadeUp .2s ease", maxWidth: "520px",
    }}>
      <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: `var(--${tone})`, flex: "0 0 8px" }} />
      <span style={{ fontSize: "13px", color: "var(--text)" }}>{msg}</span>
    </div>
  );
}
