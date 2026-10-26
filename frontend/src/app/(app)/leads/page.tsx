"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, getOrgId, getToken, type Lead, type Member } from "@/lib/api";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Loading, Modal, PageHeader, Select, fmtDate, useToast } from "@/components/ui";
import { useApp } from "../app-shell";

type Page = { items: Lead[]; total: number; page: number; page_size: number };
const FIELDS = ["name", "phone", "email", "preferred_course", "preferred_college", "education_level", "academic_marks",
  "preferred_location", "budget_min", "budget_max", "admission_timeline", "source_name"];

export default function LeadsPage() {
  const { isManager } = useApp();
  const toast = useToast();
  const [data, setData] = useState<Page | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("created_at");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(1);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [team, setTeam] = useState<Member[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [bulk, setBulk] = useState<null | { action: string }>(null);

  const load = useCallback(() => {
    const p = new URLSearchParams({ page: String(page), page_size: "20", sort, order });
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    setErr("");
    api<Page>(`/leads?${p}`).then(setData).catch((e) => setErr(e.message));
  }, [page, q, status, sort, order]);

  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t); }, [load, q]);
  useEffect(() => {
    api<{ lead_statuses: string[] }>("/settings").then((s) => setStatuses(s.lead_statuses));
    api<Member[]>("/team").then(setTeam);
  }, []);

  const name = (id: string | null) => team.find((m) => m.user_id === id)?.full_name ?? "Unassigned";
  const toggleSort = (col: string) => { if (sort === col) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(col); setOrder("asc"); } setPage(1); };

  async function exportCsv() {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/leads/export`, {
      headers: { Authorization: `Bearer ${getToken()}`, "X-Organization-Id": getOrgId() ?? "" } });
    if (!res.ok) return toast("error", "Export failed");
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: "leads.csv" });
    a.click(); URL.revokeObjectURL(url);
  }

  const th = (col: string, label: string) => (
    <th scope="col" className="px-4 py-3 text-left" aria-sort={sort === col ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button onClick={() => toggleSort(col)} className="font-medium hover:text-ink">{label}{sort === col ? (order === "asc" ? " ↑" : " ↓") : ""}</button>
    </th>
  );

  return (
    <>
      <PageHeader title="Leads" subtitle="Search, qualify and manage every student enquiry"
        actions={<>
          {isManager && <Button variant="secondary" onClick={exportCsv}>Export CSV</Button>}
          {isManager && <Button variant="secondary" onClick={() => setShowImport(true)}>Import CSV</Button>}
          <Button onClick={() => setShowNew(true)}>+ New lead</Button></>} />
      <Card>
        <div className="flex flex-wrap gap-3 border-b border-line p-4">
          <div className="min-w-56 flex-1"><label className="sr-only" htmlFor="lead-search">Search leads</label>
            <Input id="lead-search" placeholder="Search name, phone, email or course…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
          <div><label className="sr-only" htmlFor="status-filter">Filter by status</label>
            <Select id="status-filter" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">All statuses</option>{statuses.map((s) => <option key={s}>{s}</option>)}</Select></div>
          {isManager && selected.length > 0 && (
            <div className="flex items-center gap-2 text-sm"><span className="text-muted">{selected.length} selected</span>
              <Button variant="secondary" onClick={() => setBulk({ action: "assign" })}>Assign</Button>
              <Button variant="secondary" onClick={() => setBulk({ action: "status" })}>Set status</Button>
              <Button variant="danger" onClick={() => setBulk({ action: "delete" })}>Delete</Button></div>)}
        </div>
        {err ? <div className="p-4"><ErrorState message={err} onRetry={load} /></div> : !data ? <Loading /> :
          data.items.length === 0 ? <EmptyState title={q || status ? "No leads match your filters" : "No leads yet"}
            hint={q || status ? "Try clearing the search or filter." : "Create a lead, import a CSV, or embed the chatbot on your website."}
            action={!q && !status ? <Button onClick={() => setShowNew(true)}>Create your first lead</Button> : undefined} /> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted"><tr>
                  {isManager && <th className="w-10 px-4"><input type="checkbox" aria-label="Select all on page"
                    checked={data.items.every((l) => selected.includes(l.id))}
                    onChange={(e) => setSelected(e.target.checked ? data.items.map((l) => l.id) : [])} /></th>}
                  {th("name", "Student")}<th className="px-4 py-3 text-left">Course</th>{th("status", "Status")}
                  <th className="px-4 py-3 text-left">Assigned</th>{th("next_follow_up_at", "Follow-up")}{th("created_at", "Created")}
                </tr></thead>
                <tbody className="divide-y divide-line">
                  {data.items.map((l) => (
                    <tr key={l.id} className="transition hover:bg-slate-50">
                      {isManager && <td className="px-4"><input type="checkbox" aria-label={`Select ${l.name}`} checked={selected.includes(l.id)}
                        onChange={(e) => setSelected(e.target.checked ? [...selected, l.id] : selected.filter((x) => x !== l.id))} /></td>}
                      <td className="px-4 py-3"><Link href={`/leads/${l.id}`} className="font-medium text-brand-700 hover:underline">{l.name}</Link>
                        <div className="text-xs text-muted">{l.phone}</div></td>
                      <td className="px-4 py-3">{l.preferred_course ?? "-"}</td>
                      <td className="px-4 py-3"><Badge>{l.status}</Badge></td>
                      <td className="px-4 py-3 text-muted">{name(l.assigned_to)}</td>
                      <td className="px-4 py-3 text-muted">{fmtDate(l.next_follow_up_at)}</td>
                      <td className="px-4 py-3 text-muted">{fmtDate(l.created_at)}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between border-t border-line p-3 text-sm text-muted">
            <span>{(data.page - 1) * data.page_size + 1}–{Math.min(data.page * data.page_size, data.total)} of {data.total}</span>
            <div className="flex gap-2"><Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button variant="secondary" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>Next</Button></div>
          </div>)}
      </Card>
      <NewLead open={showNew} onClose={() => setShowNew(false)} team={team} isManager={isManager} onDone={load} />
      <ImportModal open={showImport} onClose={() => setShowImport(false)} onDone={load} />
      <BulkModal bulk={bulk} onClose={() => setBulk(null)} ids={selected} team={team} statuses={statuses} onDone={() => { setSelected([]); load(); }} />
    </>
  );
}

function NewLead({ open, onClose, team, isManager, onDone }: { open: boolean; onClose: () => void; team: Member[]; isManager: boolean; onDone: () => void }) {
  const toast = useToast();
  const empty = { name: "", phone: "", email: "", preferred_course: "", preferred_location: "", source_name: "", assigned_to: "" };
  const [f, setF] = useState(empty);
  const [err, setErr] = useState("");
  const [dupId, setDupId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr(""); setDupId(null); setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v === "" ? null : v]));
      await api("/leads", { method: "POST", json: body });
      toast("success", "Lead created"); setF(empty); onClose(); onDone();
    } catch (er) {
      const e2 = er as { message: string; detail?: { existing_lead_id?: string } };
      setErr(e2.message); setDupId(e2.detail?.existing_lead_id ?? null);
    } finally { setBusy(false); }
  }
  return (
    <Modal open={open} onClose={onClose} title="New lead">
      <form onSubmit={submit} className="space-y-3">
        {err && <div role="alert" className="rounded-lg bg-rose-50 p-2.5 text-sm text-rose-700">{err}
          {dupId && <> <Link className="font-medium underline" href={`/leads/${dupId}`}>View existing lead</Link></>}</div>}
        <Field label="Student name *" id="nl-name"><Input id="nl-name" required value={f.name} onChange={set("name")} /></Field>
        <Field label="Phone *" id="nl-phone"><Input id="nl-phone" required placeholder="98765 43210" value={f.phone} onChange={set("phone")} /></Field>
        <Field label="Email" id="nl-email"><Input id="nl-email" type="email" value={f.email} onChange={set("email")} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Preferred course" id="nl-course"><Input id="nl-course" value={f.preferred_course} onChange={set("preferred_course")} /></Field>
          <Field label="Preferred location" id="nl-loc"><Input id="nl-loc" value={f.preferred_location} onChange={set("preferred_location")} /></Field>
        </div>
        <Field label="Source" id="nl-src"><Input id="nl-src" placeholder="Walk-in, Referral…" value={f.source_name} onChange={set("source_name")} /></Field>
        {isManager && <Field label="Assign to" id="nl-assign"><Select id="nl-assign" value={f.assigned_to} onChange={set("assigned_to")}>
          <option value="">Unassigned</option>{team.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}</Select></Field>}
        <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>Create lead</Button></div>
      </form>
    </Modal>
  );
}

type Report = { dry_run: boolean; created: number; error_count: number; duplicate_count: number;
  errors: { row: number; error: string }[]; duplicates: { row: number; phone: string; reason: string }[] };

function ImportModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [cols, setCols] = useState<string[]>([]);
  const [map, setMap] = useState<Record<string, string>>({});
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function pick(f: File) {
    setFile(f); setReport(null); setErr("");
    const header = (await f.slice(0, 20000).text()).replace(/^\uFEFF/, "").split(/\r?\n/)[0] ?? "";
    const c = header.split(",").map((s) => s.trim().replace(/^"|"$/g, "")).filter(Boolean);
    setCols(c);
    const guess: Record<string, string> = {};
    FIELDS.forEach((fld) => { const m = c.find((x) => x.toLowerCase().replace(/[\s_-]/g, "") === fld.replace(/_/g, "")); if (m) guess[fld] = m; });
    if (!guess.phone) { const m = c.find((x) => /phone|mobile/i.test(x)); if (m) guess.phone = m; }
    setMap(guess);
  }
  async function run(dry: boolean) {
    if (!file) return;
    setBusy(true); setErr("");
    const fd = new FormData();
    fd.append("file", file); fd.append("mapping", JSON.stringify(Object.fromEntries(Object.entries(map).filter(([, v]) => v))));
    fd.append("dry_run", String(dry));
    try {
      const r = await api<Report>("/leads/import", { method: "POST", body: fd });
      setReport(r);
      if (!dry) { toast("success", `Imported ${r.created} leads`); onDone(); }
    } catch (e) { setErr(e instanceof Error ? e.message : "Import failed"); } finally { setBusy(false); }
  }
  const ready = file && map.name && map.phone;
  return (
    <Modal open={open} onClose={() => { onClose(); setFile(null); setReport(null); }} title="Import leads from CSV">
      <div className="space-y-4 text-sm">
        <p className="text-muted">UTF-8 CSV, up to 2 MB / 5,000 rows. Duplicates (by phone number) are reported and never overwrite existing leads.</p>
        <input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])} />
        {cols.length > 0 && <div className="grid grid-cols-2 gap-3">
          {FIELDS.map((fld) => (
            <Field key={fld} label={`${fld.replace(/_/g, " ")}${fld === "name" || fld === "phone" ? " *" : ""}`} id={`map-${fld}`}>
              <Select id={`map-${fld}`} value={map[fld] ?? ""} onChange={(e) => { setMap({ ...map, [fld]: e.target.value }); setReport(null); }}>
                <option value="">-</option>{cols.map((c) => <option key={c}>{c}</option>)}</Select></Field>))}
        </div>}
        {err && <p role="alert" className="rounded-lg bg-rose-50 p-2.5 text-rose-700">{err}</p>}
        {report && <div className="rounded-lg border border-line bg-slate-50 p-3" role="status">
          <p className="font-medium">{report.dry_run ? "Preview" : "Result"}: {report.created} {report.dry_run ? "would be created" : "created"}, {report.duplicate_count} duplicates, {report.error_count} errors</p>
          {report.errors.length > 0 && <ul className="mt-2 max-h-32 list-disc space-y-0.5 overflow-y-auto pl-5 text-rose-700">{report.errors.map((e, i) => <li key={i}>Row {e.row}: {e.error}</li>)}</ul>}
          {report.duplicates.length > 0 && <ul className="mt-2 max-h-32 list-disc space-y-0.5 overflow-y-auto pl-5 text-amber-700">{report.duplicates.map((d, i) => <li key={i}>Row {d.row} ({d.phone}): {d.reason}</li>)}</ul>}
        </div>}
        <div className="flex justify-end gap-2"><Button variant="secondary" disabled={!ready} loading={busy} onClick={() => run(true)}>Preview</Button>
          <Button disabled={!ready || !report || report.created === 0 || !report.dry_run} loading={busy} onClick={() => run(false)}>Import</Button></div>
      </div>
    </Modal>
  );
}

function BulkModal({ bulk, onClose, ids, team, statuses, onDone }: { bulk: { action: string } | null; onClose: () => void; ids: string[]; team: Member[]; statuses: string[]; onDone: () => void }) {
  const toast = useToast();
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  if (!bulk) return null;
  async function go() {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { lead_ids: ids, action: bulk!.action, confirm: true };
      if (bulk!.action === "assign") body.assigned_to = val || null;
      if (bulk!.action === "status") body.status = val;
      const r = await api<{ affected: number }>("/leads/bulk", { method: "POST", json: body });
      toast("success", `${r.affected} leads updated`); onClose(); onDone();
    } catch (e) { toast("error", e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={`Confirm bulk ${bulk.action}`}>
      <p className="mb-3 text-sm">This will affect <b>{ids.length}</b> lead(s).{bulk.action === "delete" && " Deleting cannot be undone."}</p>
      {bulk.action === "assign" && <Field label="Assign to" id="bulk-assign"><Select id="bulk-assign" value={val} onChange={(e) => setVal(e.target.value)}>
        <option value="">Unassigned</option>{team.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}</Select></Field>}
      {bulk.action === "status" && <Field label="New status" id="bulk-status"><Select id="bulk-status" value={val} onChange={(e) => setVal(e.target.value)}>
        <option value="">Choose…</option>{statuses.map((s) => <option key={s}>{s}</option>)}</Select></Field>}
      <div className="mt-4 flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant={bulk.action === "delete" ? "danger" : "primary"} loading={busy} disabled={bulk.action === "status" && !val} onClick={go}>Confirm</Button></div>
    </Modal>
  );
}
