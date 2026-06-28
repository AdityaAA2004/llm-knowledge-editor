"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Company, FeatureTeam, API, Endpoint, Triple } from "@/lib/types";
import { Spinner, ErrorMsg, Button, FieldInput, JsonField, StatusBadge, MonoBadge, Card, SectionLabel } from "@/components/ui";

// ── Detail panel sub-components ───────────────────────────────────────────────

function StatCard({ dot, label, count, sub }: { dot: string; label: string; count: number; sub: string }) {
  return (
    <div style={{ flex: 1, minWidth: "120px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "10px", padding: "13px 15px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "7px", fontSize: "11px", color: "var(--text-muted)", marginBottom: "6px" }}>
        <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: `var(--${dot})` }} />
        {label}
      </div>
      <div style={{ fontSize: "22px", fontWeight: 600, fontFamily: "'IBM Plex Mono',monospace" }}>{count}</div>
      <div style={{ fontSize: "10.5px", color: "var(--text-faint)", marginTop: "2px" }}>{sub}</div>
    </div>
  );
}

// ── Company detail ────────────────────────────────────────────────────────────

function CompanyDetail({ company, triples }: { company: Company; triples: Triple[] }) {
  const qc = useQueryClient();
  const [name, setName] = useState(company.name);
  const [errorSchema, setErrorSchema] = useState<Record<string, unknown> | null>(
    company.error_schema_json as Record<string, unknown> | null ?? null
  );
  const [dirty, setDirty] = useState(false);

  const updateMut = useMutation({
    mutationFn: () => api.put(`/companies/${company.id}`, { name, error_schema_json: errorSchema }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["companies"] }); setDirty(false); },
  });

  const own = triples.filter((t) => t.source_id === company.id);
  const committed = own.filter((t) => t.committed && !t.pending_erasure).length;
  const pending = own.filter((t) => !t.committed && !t.pending_erasure).length;
  const erasure = own.filter((t) => t.pending_erasure).length;

  return (
    <DetailShell
      typeLabel="COMPANY"
      id={company.id}
      name={company.name}
      committed={committed} pending={pending} erasure={erasure}
      triples={own}
      dirty={dirty}
      onSave={() => updateMut.mutate()}
      onSaveDisabled={!dirty || updateMut.isPending}
      saving={updateMut.isPending}
    >
      <FieldInput label="Company name" value={name} onChange={(v) => { setName(v); setDirty(true); }} />
      <JsonField
        label="Error envelope (4xx / 5xx schema)"
        value={errorSchema}
        onChange={(v) => { setErrorSchema(v); setDirty(true); }}
        placeholder={'{\n  "error": "string",\n  "code": "integer",\n  "message": "string"\n}'}
        rows={7}
      />
    </DetailShell>
  );
}

// ── Team detail ───────────────────────────────────────────────────────────────

function TeamDetail({ team, triples }: { team: FeatureTeam; triples: Triple[] }) {
  const qc = useQueryClient();
  const [name, setName] = useState(team.name);
  const [lead, setLead] = useState(team.tech_lead ?? "");
  const [dirty, setDirty] = useState(false);

  const updateMut = useMutation({
    mutationFn: () => api.put(`/teams/${team.id}`, { name, tech_lead: lead || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["teams"] }); setDirty(false); },
  });
  const deleteMut = useMutation({
    mutationFn: () => api.delete(`/teams/${team.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["teams"] }),
  });

  const own = triples.filter((t) => t.source_id === team.id);
  const committed = own.filter((t) => t.committed && !t.pending_erasure).length;
  const pending = own.filter((t) => !t.committed && !t.pending_erasure).length;
  const erasure = own.filter((t) => t.pending_erasure).length;

  return (
    <DetailShell
      typeLabel="FEATURE TEAM"
      id={team.id}
      name={team.name}
      committed={committed} pending={pending} erasure={erasure}
      triples={own}
      dirty={dirty}
      onSave={() => updateMut.mutate()}
      onSaveDisabled={!dirty || updateMut.isPending}
      saving={updateMut.isPending}
      onDelete={() => deleteMut.mutate()}
      deleting={deleteMut.isPending}
      deleteError={deleteMut.isError ? "Cannot delete — reassign APIs first" : undefined}
    >
      <FieldInput label="Team name" value={name} onChange={(v) => { setName(v); setDirty(true); }} />
      <FieldInput label="Tech lead" value={lead} onChange={(v) => { setLead(v); setDirty(true); }} />
    </DetailShell>
  );
}

// ── API detail ────────────────────────────────────────────────────────────────

function ApiDetail({ apiObj, triples }: { apiObj: API; triples: Triple[] }) {
  const qc = useQueryClient();
  const [name, setName] = useState(apiObj.name);
  const [desc, setDesc] = useState(apiObj.description ?? "");
  const [poc, setPoc] = useState(apiObj.point_of_contact ?? "");
  const [dirty, setDirty] = useState(false);

  const updateMut = useMutation({
    mutationFn: () => api.put(`/apis/${apiObj.id}`, { name, description: desc || null, point_of_contact: poc || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["apis"] }); setDirty(false); },
  });
  const deleteMut = useMutation({
    mutationFn: () => api.delete(`/apis/${apiObj.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["apis"] }),
  });

  const own = triples.filter((t) => t.source_id === apiObj.id);
  const committed = own.filter((t) => t.committed && !t.pending_erasure).length;
  const pending = own.filter((t) => !t.committed && !t.pending_erasure).length;
  const erasure = own.filter((t) => t.pending_erasure).length;

  return (
    <DetailShell
      typeLabel="API"
      id={apiObj.id}
      name={apiObj.name}
      committed={committed} pending={pending} erasure={erasure}
      triples={own}
      dirty={dirty}
      onSave={() => updateMut.mutate()}
      onSaveDisabled={!dirty || updateMut.isPending}
      saving={updateMut.isPending}
      onDelete={() => deleteMut.mutate()}
      deleting={deleteMut.isPending}
    >
      <FieldInput label="API name" value={name} onChange={(v) => { setName(v); setDirty(true); }} />
      <FieldInput label="Description" value={desc} onChange={(v) => { setDesc(v); setDirty(true); }} multiline />
      <FieldInput label="Point of contact" value={poc} onChange={(v) => { setPoc(v); setDirty(true); }} />
    </DetailShell>
  );
}

// ── Endpoint detail ───────────────────────────────────────────────────────────

function EndpointDetail({ endpoint, triples }: { endpoint: Endpoint; triples: Triple[] }) {
  const qc = useQueryClient();
  const [path, setPath] = useState(endpoint.path);
  const [method, setMethod] = useState(endpoint.http_method);
  const [fn, setFn] = useState(endpoint.business_function ?? "");
  const [dirty, setDirty] = useState(false);

  const updateMut = useMutation({
    mutationFn: () => api.put(`/endpoints/${endpoint.id}`, { path, http_method: method, business_function: fn || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["endpoints"] }); setDirty(false); },
  });
  const deleteMut = useMutation({
    mutationFn: () => api.delete(`/endpoints/${endpoint.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["endpoints"] }),
  });

  const own = triples.filter((t) => t.source_id === endpoint.id);
  const committed = own.filter((t) => t.committed && !t.pending_erasure).length;
  const pending = own.filter((t) => !t.committed && !t.pending_erasure).length;
  const erasure = own.filter((t) => t.pending_erasure).length;

  return (
    <DetailShell
      typeLabel="ENDPOINT"
      id={endpoint.id}
      name={`${endpoint.http_method} ${endpoint.path}`}
      committed={committed} pending={pending} erasure={erasure}
      triples={own}
      dirty={dirty}
      onSave={() => updateMut.mutate()}
      onSaveDisabled={!dirty || updateMut.isPending}
      saving={updateMut.isPending}
      onDelete={() => deleteMut.mutate()}
      deleting={deleteMut.isPending}
    >
      <FieldInput label="Path" value={path} onChange={(v) => { setPath(v); setDirty(true); }} />
      <FieldInput label="HTTP method" value={method} onChange={(v) => { setMethod(v); setDirty(true); }} />
      <FieldInput label="Business function" value={fn} onChange={(v) => { setFn(v); setDirty(true); }} />
    </DetailShell>
  );
}

// ── Shared detail shell ───────────────────────────────────────────────────────

function DetailShell({
  typeLabel, id, name, committed, pending, erasure, triples,
  dirty, onSave, onSaveDisabled, saving, onDelete, deleting, deleteError, children,
}: {
  typeLabel: string; id: string; name: string;
  committed: number; pending: number; erasure: number;
  triples: Triple[];
  dirty: boolean;
  onSave: () => void;
  onSaveDisabled: boolean;
  saving: boolean;
  onDelete?: () => void;
  deleting?: boolean;
  deleteError?: string;
  children: React.ReactNode;
}) {
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

  return (
    <div style={{ maxWidth: "680px", padding: "26px 30px" }}>
      {/* Header */}
      <div style={{ marginBottom: "4px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "9px", marginBottom: "5px" }}>
          <MonoBadge label={typeLabel} tone="accent" />
          <span style={{ fontSize: "11.5px", color: "var(--text-faint)", fontFamily: "'IBM Plex Mono',monospace" }}>{id.slice(0, 8)}</span>
        </div>
        <div style={{ fontSize: "22px", fontWeight: 600, letterSpacing: "-0.4px" }}>{name}</div>
      </div>

      {/* Triple stat summary */}
      <div style={{ display: "flex", gap: "9px", margin: "18px 0 22px", flexWrap: "wrap" }}>
        <StatCard dot="ok" label="Committed" count={committed} sub="live in model weights" />
        <StatCard dot="warn" label="Pending" count={pending} sub="in KB, not yet pushed" />
        <StatCard dot="danger" label="Pending erasure" count={erasure} sub="queued for ELM removal" />
      </div>

      {/* Edit form */}
      <Card>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", fontSize: "12.5px", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.4px" }}>
          Edit fields
        </div>
        <div style={{ padding: "18px 16px", display: "flex", flexDirection: "column", gap: "15px" }}>
          {children}
        </div>
        <div style={{ padding: "13px 16px", borderTop: "1px solid var(--border)", background: "var(--surface-2)", display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            onClick={onSave}
            disabled={onSaveDisabled}
            style={{
              background: onSaveDisabled ? "var(--border)" : "var(--accent)",
              color: onSaveDisabled ? "var(--text-faint)" : "var(--accent-fg)",
              border: "none", borderRadius: "8px", padding: "9px 16px",
              font: "600 12.5px 'IBM Plex Sans'", cursor: onSaveDisabled ? "default" : "pointer",
              display: "flex", alignItems: "center", gap: "6px",
            }}
          >
            {saving && <Spinner size={12} />}
            Save changes
          </button>
          {onDelete && (
            <button
              onClick={onDelete}
              disabled={deleting}
              style={{
                marginLeft: "auto", background: "transparent", color: "var(--danger)",
                border: "1px solid var(--danger-soft)", borderRadius: "8px", padding: "9px 14px",
                font: "500 12.5px 'IBM Plex Sans'", cursor: deleting ? "default" : "pointer",
              }}
            >
              {deleting ? <Spinner size={12} /> : "Soft-delete"}
            </button>
          )}
        </div>
      </Card>

      {deleteError && <div style={{ marginTop: "10px" }}><ErrorMsg message={deleteError} /></div>}

      {dirty && (
        <div style={{ marginTop: "12px", display: "flex", alignItems: "center", gap: "9px", background: "var(--warn-soft)", border: "1px solid var(--warn-soft)", borderRadius: "9px", padding: "10px 13px", fontSize: "12px", color: "var(--warn)" }}>
          <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "var(--warn)", flex: "0 0 7px" }} />
          Unsaved edits. Saving re-derives triples and marks them <b style={{ margin: "0 3px" }}>Pending</b> — they stay out of the model until pushed.
        </div>
      )}

      {/* Derived triples */}
      <div style={{ marginTop: "24px" }}>
        <SectionLabel>Derived triples ({triples.length})</SectionLabel>
        <Card>
          {triples.length === 0 && (
            <div style={{ padding: "18px", textAlign: "center", fontSize: "12px", color: "var(--text-faint)" }}>No triples derived from this entity.</div>
          )}
          {triples.map((t) => (
            <div key={t.id} style={{ display: "flex", alignItems: "center", gap: "10px", padding: "11px 15px", borderBottom: "1px solid var(--border)", fontFamily: "'IBM Plex Mono',monospace", fontSize: "12px" }}>
              <span style={{ color: "var(--text)" }}>{t.subject}</span>
              <span style={{ color: "var(--accent)", fontWeight: 500 }}>{t.relation}</span>
              <span style={{ color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{t.object}</span>
              <StatusBadge label={labelOf(t)} tone={toneOf(t)} />
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}

// ── Add forms ─────────────────────────────────────────────────────────────────

function AddCompanyInline({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const mut = useMutation({
    mutationFn: () => api.post("/companies/", { name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["companies"] }); onDone(); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); mut.mutate(); }} style={{ display: "flex", gap: "8px", padding: "10px 16px", background: "var(--accent-soft)", borderBottom: "1px solid var(--border)", alignItems: "flex-end" }}>
      <div style={{ flex: 1 }}>
        <FieldInput label="Company name" value={name} onChange={setName} required placeholder="e.g. Acme Corp" />
      </div>
      <Button type="submit" disabled={mut.isPending || !name.trim()} size="sm">
        {mut.isPending && <Spinner size={11} />}Add
      </Button>
      <Button variant="ghost" size="sm" onClick={onDone}>Cancel</Button>
    </form>
  );
}

function AddTeamInline({ companyId, onDone }: { companyId: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [lead, setLead] = useState("");
  const mut = useMutation({
    mutationFn: () => api.post("/teams/", { company_id: companyId, name, tech_lead: lead || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["teams"] }); onDone(); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); mut.mutate(); }} style={{ display: "flex", flexDirection: "column", gap: "8px", padding: "10px 16px", background: "var(--accent-soft)", borderBottom: "1px solid var(--border)" }}>
      <FieldInput label="Team name" value={name} onChange={setName} required placeholder="e.g. Platform Team" />
      <FieldInput label="Tech lead (optional)" value={lead} onChange={setLead} placeholder="e.g. alice@company.com" />
      <div style={{ display: "flex", gap: "8px" }}>
        <Button type="submit" disabled={mut.isPending || !name.trim()} size="sm">{mut.isPending && <Spinner size={11} />}Add</Button>
        <Button variant="ghost" size="sm" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function AddApiInline({ teamId, onDone }: { teamId: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const mut = useMutation({
    mutationFn: () => api.post("/apis/", { team_id: teamId, name, description: desc || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["apis"] }); onDone(); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); mut.mutate(); }} style={{ display: "flex", flexDirection: "column", gap: "8px", padding: "10px 16px", background: "var(--accent-soft)", borderBottom: "1px solid var(--border)" }}>
      <FieldInput label="API name" value={name} onChange={setName} required placeholder="e.g. Payments API" />
      <FieldInput label="Description (optional)" value={desc} onChange={setDesc} placeholder="What does this API do?" />
      <div style={{ display: "flex", gap: "8px" }}>
        <Button type="submit" disabled={mut.isPending || !name.trim()} size="sm">{mut.isPending && <Spinner size={11} />}Add</Button>
        <Button variant="ghost" size="sm" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function AddEndpointInline({ apiId, onDone }: { apiId: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [path, setPath] = useState("");
  const [method, setMethod] = useState("GET");
  const mut = useMutation({
    mutationFn: () => api.post("/endpoints/", { api_id: apiId, path, http_method: method }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["endpoints"] }); onDone(); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); mut.mutate(); }} style={{ display: "flex", flexDirection: "column", gap: "8px", padding: "10px 16px", background: "var(--accent-soft)", borderBottom: "1px solid var(--border)" }}>
      <FieldInput label="Path" value={path} onChange={setPath} required placeholder="/v1/payments" />
      <FieldInput label="HTTP method" value={method} onChange={setMethod} placeholder="GET" />
      <div style={{ display: "flex", gap: "8px" }}>
        <Button type="submit" disabled={mut.isPending || !path.trim()} size="sm">{mut.isPending && <Spinner size={11} />}Add</Button>
        <Button variant="ghost" size="sm" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

// ── Tree row ──────────────────────────────────────────────────────────────────

function TreeRow({
  depth, tag, label, hasChildren, expanded, selected, dotTone,
  onSelect, onToggle,
}: {
  depth: number; tag: string; label: string; hasChildren: boolean;
  expanded: boolean; selected: boolean; dotTone: string | null;
  onSelect: () => void; onToggle: (e: React.MouseEvent) => void;
}) {
  const nameColor = selected ? "var(--accent)" : "var(--text)";
  return (
    <div
      onClick={onSelect}
      style={{
        display: "flex", alignItems: "center", gap: "7px",
        padding: "6px 8px", paddingLeft: `${8 + depth * 16}px`,
        borderRadius: "7px", cursor: "pointer",
        background: selected ? "var(--accent-soft)" : "transparent",
        marginBottom: "1px",
      }}
    >
      <span
        onClick={hasChildren ? onToggle : undefined}
        style={{ width: "20px", flex: "0 0 20px", textAlign: "center", color: "var(--text)", fontSize: "18px" }}
      >
        {hasChildren ? (expanded ? "▾" : "▸") : ""}
      </span>
      <MonoBadge label={tag} />
      <span style={{
        fontSize: "12.5px", color: nameColor, fontWeight: selected ? 600 : 400,
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", flex: 1,
      }}>{label}</span>
      {dotTone && (
        <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: `var(--${dotTone})`, flex: "0 0 7px" }} />
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Selection =
  | { type: "company"; data: Company }
  | { type: "team"; data: FeatureTeam }
  | { type: "api"; data: API }
  | { type: "endpoint"; data: Endpoint }
  | null;

export default function KnowledgeBasePage() {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState<Selection>(null);
  const [addingType, setAddingType] = useState<"company" | "team" | "api" | "endpoint" | null>(null);

  // Fetch data lazily
  const { data: companies, isLoading: coLoading, error: coError } = useQuery<Company[]>({
    queryKey: ["companies"],
    queryFn: () => api.get<Company[]>("/companies/"),
  });

  const { data: teams } = useQuery<FeatureTeam[]>({
    queryKey: ["teams"],
    queryFn: () => api.get<FeatureTeam[]>("/teams/"),
    enabled: !!companies,
  });

  const { data: apis } = useQuery<API[]>({
    queryKey: ["apis"],
    queryFn: () => api.get<API[]>("/apis/"),
    enabled: !!teams,
  });

  const { data: endpoints } = useQuery<Endpoint[]>({
    queryKey: ["endpoints"],
    queryFn: () => api.get<Endpoint[]>("/endpoints/"),
    enabled: !!apis,
  });

  const { data: triples } = useQuery<Triple[]>({
    queryKey: ["triples", "all"],
    queryFn: () => api.get<Triple[]>("/triples/"),
    refetchInterval: 15000,
  });

  function toggle(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  const activeTriples = triples ?? [];
  const entityCount = (companies?.length ?? 0) + (teams?.filter((t) => !t.deleted_at).length ?? 0) + (apis?.filter((a) => !a.deleted_at).length ?? 0) + (endpoints?.filter((e) => !e.deleted_at).length ?? 0);

  function tripleStatus(sourceId: string) {
    const own = activeTriples.filter((t) => t.source_id === sourceId);
    if (!own.length) return null;
    if (own.some((t) => t.pending_erasure)) return "danger";
    if (own.some((t) => !t.committed)) return "warn";
    return "ok";
  }

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
      {/* ── Tree panel ── */}
      <div style={{
        width: "340px", flex: "0 0 340px", borderRight: "1px solid var(--border)",
        background: "var(--surface)", display: "flex", flexDirection: "column",
      }}>
        <div style={{ padding: "14px 16px 10px", display: "flex", alignItems: "center", gap: "8px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Knowledge tree</div>
          <span style={{ fontSize: "11px", color: "var(--text-faint)", fontFamily: "'IBM Plex Mono',monospace" }}>{entityCount} entities</span>
          {selected?.type !== "endpoint" && (
            <button
              onClick={() => {
                const t = selected?.type === "company" ? "team"
                  : selected?.type === "team" ? "api"
                  : selected?.type === "api" ? "endpoint"
                  : "company";
                setAddingType(t);
              }}
              style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "5px", background: "transparent", border: "none", cursor: "pointer", color: "var(--accent)", fontSize: "12px", fontWeight: 600 }}
            >
              + {selected?.type === "company" ? "Team" : selected?.type === "team" ? "API" : selected?.type === "api" ? "Endpoint" : "Company"}
            </button>
          )}
        </div>

        {addingType === "company" && <AddCompanyInline onDone={() => setAddingType(null)} />}
        {addingType === "team" && selected?.type === "company" && (
          <AddTeamInline companyId={selected.data.id} onDone={() => setAddingType(null)} />
        )}
        {addingType === "api" && selected?.type === "team" && (
          <AddApiInline teamId={selected.data.id} onDone={() => setAddingType(null)} />
        )}
        {addingType === "endpoint" && selected?.type === "api" && (
          <AddEndpointInline apiId={selected.data.id} onDone={() => setAddingType(null)} />
        )}

        <div style={{ flex: 1, overflow: "auto", padding: "8px 8px 20px" }}>
          {coLoading && <div style={{ padding: "20px", textAlign: "center" }}><Spinner /></div>}
          {coError && <div style={{ padding: "12px" }}><ErrorMsg message={(coError as Error).message} /></div>}

          {companies?.map((co) => (
            <div key={co.id}>
              <TreeRow
                depth={0} tag="CO" label={co.name}
                hasChildren={!!teams?.filter((t) => t.company_id === co.id && !t.deleted_at).length}
                expanded={!!expanded[co.id]} selected={selected?.type === "company" && selected.data.id === co.id}
                dotTone={tripleStatus(co.id)}
                onSelect={() => { setSelected({ type: "company", data: co }); setExpanded((prev) => ({ ...prev, [co.id]: !prev[co.id] })); }}
                onToggle={(e) => toggle(co.id, e)}
              />

              {expanded[co.id] && teams?.filter((t) => t.company_id === co.id && !t.deleted_at).map((tm) => (
                <div key={tm.id}>
                  <TreeRow
                    depth={1} tag="TM" label={tm.name}
                    hasChildren={!!apis?.filter((a) => a.team_id === tm.id && !a.deleted_at).length}
                    expanded={!!expanded[tm.id]} selected={selected?.type === "team" && selected.data.id === tm.id}
                    dotTone={tripleStatus(tm.id)}
                    onSelect={() => { setSelected({ type: "team", data: tm }); setExpanded((prev) => ({ ...prev, [tm.id]: !prev[tm.id] })); }}
                    onToggle={(e) => toggle(tm.id, e)}
                  />

                  {expanded[tm.id] && apis?.filter((a) => a.team_id === tm.id && !a.deleted_at).map((ap) => (
                    <div key={ap.id}>
                      <TreeRow
                        depth={2} tag="API" label={ap.name}
                        hasChildren={!!endpoints?.filter((ep) => ep.api_id === ap.id && !ep.deleted_at).length}
                        expanded={!!expanded[ap.id]} selected={selected?.type === "api" && selected.data.id === ap.id}
                        dotTone={tripleStatus(ap.id)}
                        onSelect={() => { setSelected({ type: "api", data: ap }); setExpanded((prev) => ({ ...prev, [ap.id]: !prev[ap.id] })); }}
                        onToggle={(e) => toggle(ap.id, e)}
                      />

                      {expanded[ap.id] && endpoints?.filter((ep) => ep.api_id === ap.id && !ep.deleted_at).map((ep) => (
                        <TreeRow
                          key={ep.id}
                          depth={3} tag="EP" label={`${ep.http_method} ${ep.path}`}
                          hasChildren={false}
                          expanded={false} selected={selected?.type === "endpoint" && selected.data.id === ep.id}
                          dotTone={tripleStatus(ep.id)}
                          onSelect={() => setSelected({ type: "endpoint", data: ep })}
                          onToggle={() => {}}
                        />
                      ))}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ── Detail panel ── */}
      <div style={{ flex: 1, overflow: "auto", minWidth: 0 }}>
        {!selected && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-faint)", fontSize: "13px" }}>
            Select an entity in the tree to view and edit it
          </div>
        )}
        {selected?.type === "company" && <CompanyDetail company={selected.data} triples={activeTriples} />}
        {selected?.type === "team" && <TeamDetail team={selected.data} triples={activeTriples} />}
        {selected?.type === "api" && <ApiDetail apiObj={selected.data} triples={activeTriples} />}
        {selected?.type === "endpoint" && <EndpointDetail endpoint={selected.data} triples={activeTriples} />}
      </div>
    </div>
  );
}
