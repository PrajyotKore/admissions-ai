"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type Lead, type Member, type Task } from "@/lib/api";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Loading, Select, Textarea, fmtDate, inr, useToast } from "@/components/ui";
import { useApp } from "../../app-shell";

type Activity = { id: string; kind: string; message: string; actor_id: string | null; created_at: string };
type ConsentRec = { id: string; purpose: string; status: string; source: string; evidence: Record<string, string>; created_at: string };
const PURPOSES = [["automated_calls", "Automated calls"], ["marketing", "Marketing"], ["data_processing", "Data processing"]];
const KIND_ICON: Record<string, string> = { created: "＋", updated: "✎", note: "✉", status: "◉", assigned: "☺", consent: "✔", task: "⏰", call: "☎" };

type QualResult = {
  id: string; category: string; priority_score: number;
  hard_failures: string[]; reasons: string[]; missing_fields: string[]; next_action: string; created_at: string;
};

type CallItem = {
  id: string;
  lead_id: string;
  lead_name: string | null;
  job_id: string | null;
  provider: string;
  is_synthetic: boolean;
  status: string;
  outcome: string | null;
  duration_seconds: number | null;
  cost_cents: number;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
};

type CallDetail = CallItem & {
  transcript: string | null;
  summary: {
    summary: string | null;
    extracted_fields: Record<string, unknown>;
    next_action: string | null;
    is_ai_generated: boolean;
  } | null;
};

export default function LeadDetail() {
  const { id } = useParams<{ id: string }>();
  const { isManager } = useApp();
  const toast = useToast();
  const [lead, setLead] = useState<Lead | null>(null);
  const [acts, setActs] = useState<Activity[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [consents, setConsents] = useState<ConsentRec[]>([]);
  const [qualHistory, setQualHistory] = useState<QualResult[]>([]);
  const [calls, setCalls] = useState<CallItem[]>([]);
  const [selectedCall, setSelectedCall] = useState<CallDetail | null>(null);
  const [loadingCall, setLoadingCall] = useState(false);
  const [team, setTeam] = useState<Member[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [task, setTask] = useState({ title: "", due_at: "" });
  const [consentNote, setConsentNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [callingBusy, setCallingBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [l, a, t, c, q, ch] = await Promise.all([
        api<Lead>(`/leads/${id}`),
        api<Activity[]>(`/leads/${id}/activities`),
        api<Task[]>("/tasks?status=open"),
        api<ConsentRec[]>(`/leads/${id}/consent`),
        api<QualResult[]>(`/leads/${id}/qualification`),
        api<{ items: CallItem[] }>(`/calls/history?lead_id=${id}`),
      ]);
      setLead(l); setActs(a); setTasks(t.filter((x) => x.lead_id === id)); setConsents(c); setQualHistory(q); setCalls(ch.items);
      setForm(Object.fromEntries(["name", "email", "preferred_course", "preferred_college", "education_level", "academic_marks",
        "preferred_location", "budget_min", "budget_max", "admission_timeline"].map((k) => [k, String((l as unknown as Record<string, unknown>)[k] ?? "")])));
      setErr("");
    } catch (e) { setErr(e instanceof Error ? e.message : "Failed to load"); }
  }, [id]);

  useEffect(() => {
    let ignore = false;
    Promise.all([
      api<Lead>(`/leads/${id}`),
      api<Activity[]>(`/leads/${id}/activities`),
      api<Task[]>("/tasks?status=open"),
      api<ConsentRec[]>(`/leads/${id}/consent`),
      api<QualResult[]>(`/leads/${id}/qualification`),
      api<{ items: CallItem[] }>(`/calls/history?lead_id=${id}`),
      api<Member[]>("/team"),
      api<{ lead_statuses: string[] }>("/settings"),
    ])
      .then(([l, a, t, c, q, ch, tm, st]) => {
        if (!ignore) {
          setLead(l);
          setActs(a);
          setTasks(t.filter((x) => x.lead_id === id));
          setConsents(c);
          setQualHistory(q);
          setCalls(ch.items);
          setTeam(tm);
          setStatuses(st.lead_statuses);
          setForm(Object.fromEntries(["name", "email", "preferred_course", "preferred_college", "education_level", "academic_marks",
            "preferred_location", "budget_min", "budget_max", "admission_timeline"].map((k) => [k, String((l as unknown as Record<string, unknown>)[k] ?? "")])));
          setErr("");
        }
      })
      .catch((e) => {
        if (!ignore) setErr(e instanceof Error ? e.message : "Failed to load");
      });
    return () => { ignore = true; };
  }, [id]);

  async function act<T>(fn: () => Promise<T>, ok: string) {
    setBusy(true);
    try { await fn(); toast("success", ok); await load(); } catch (e) { toast("error", e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  }

  async function triggerAiCall() {
    setCallingBusy(true);
    try {
      const res = await api<{ job: unknown; attempt: CallItem }>(`/calls/trigger/${id}?execute_now=true`, { method: "POST" });
      toast("success", "AI Voice call executed (Mock Telephony)");
      await load();
      if (res.attempt) {
        openCallDetail(res.attempt.id);
      }
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to trigger call");
    } finally {
      setCallingBusy(false);
    }
  }

  async function openCallDetail(attemptId: string) {
    setLoadingCall(true);
    try {
      const detail = await api<CallDetail>(`/calls/attempts/${attemptId}`);
      setSelectedCall(detail);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to load call detail");
    } finally {
      setLoadingCall(false);
    }
  }

  const numOrNull = (v: string) => (v === "" ? null : Number(v));

  if (err) return <ErrorState message={err} onRetry={load} />;
  if (!lead) return <Loading />;
  const who = (uid: string | null) => (uid ? team.find((m) => m.user_id === uid)?.full_name ?? "User" : "System");
  const f = (k: string) => ({ id: `f-${k}`, value: form[k] ?? "", onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value }) });
  const prov = (k: string) => lead.field_provenance?.[k];

  const hasCallConsent = lead.consent?.automated_calls === "granted";
  const canCall = hasCallConsent && !lead.do_not_contact;

  return (
    <>
      <Link href="/leads" className="text-sm text-brand-700 hover:underline">← All leads</Link>
      <div className="mb-6 mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{lead.name}</h1>
        <Badge>{lead.status}</Badge>
        {lead.do_not_contact && <Badge tone="bg-rose-600 text-white ring-rose-700">Do Not Contact</Badge>}
        <span className="text-sm text-muted">{lead.phone}</span>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* AI Voice Calling Card */}
          <Card className="border-indigo-100 bg-gradient-to-br from-indigo-50/40 via-white to-sky-50/30 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-indigo-100 pb-3">
              <div>
                <h2 className="flex items-center gap-2 font-semibold text-slate-900">
                  <span className="text-indigo-600">📞</span> AI Voice Calling Follow-up
                </h2>
                <p className="text-xs text-slate-500">
                  Automated qualification & appointment outreach via grounded telephony agent.
                </p>
              </div>
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-inset ring-slate-200">
                Mock Provider (is_synthetic=True)
              </span>
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1 text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-700">Consent:</span>
                  <Badge tone={hasCallConsent ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-rose-50 text-rose-700 ring-rose-600/20"}>
                    {lead.consent?.automated_calls ?? "none"}
                  </Badge>
                  {lead.do_not_contact && (
                    <Badge tone="bg-rose-600 text-white ring-rose-700">DNC Active</Badge>
                  )}
                </div>
                {!canCall && (
                  <p className="text-rose-600">
                    {lead.do_not_contact
                      ? "Lead is on the Do Not Contact list. Automated calling is strictly blocked."
                      : "Automated call consent has not been granted. Record consent below to enable calling."}
                  </p>
                )}
              </div>

              <Button
                variant="primary"
                disabled={!canCall || callingBusy}
                loading={callingBusy}
                onClick={triggerAiCall}
                className="bg-indigo-600 text-white hover:bg-indigo-700"
              >
                Trigger AI Voice Call
              </Button>
            </div>

            {/* Recent Calls on this lead */}
            {calls.length > 0 && (
              <div className="mt-5 border-t border-indigo-100 pt-3">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Call History ({calls.length})
                </h3>
                <div className="space-y-2">
                  {calls.slice(0, 3).map((c) => (
                    <div
                      key={c.id}
                      className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-2.5 text-xs shadow-sm hover:border-indigo-300"
                    >
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-800">{c.outcome ?? c.status}</span>
                          <span className="rounded bg-indigo-50 px-1.5 py-0.2 text-[10px] font-medium text-indigo-700">
                            Synthetic
                          </span>
                        </div>
                        <p className="text-slate-400">
                          {fmtDate(c.created_at)} {c.duration_seconds ? `· ${c.duration_seconds}s` : ""}
                        </p>
                      </div>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => openCallDetail(c.id)}
                        disabled={loadingCall}
                      >
                        View Transcript
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="mb-4 font-semibold">Student details</h2>
            <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault();
              act(() => api(`/leads/${id}`, { method: "PATCH", json: { name: form.name, email: form.email || null, preferred_course: form.preferred_course || null,
                preferred_college: form.preferred_college || null, education_level: form.education_level || null, academic_marks: numOrNull(form.academic_marks),
                preferred_location: form.preferred_location || null, budget_min: numOrNull(form.budget_min), budget_max: numOrNull(form.budget_max),
                admission_timeline: form.admission_timeline || null } }), "Lead updated"); }}>
              <Field label="Name" id="f-name"><Input {...f("name")} required /></Field>
              <Field label="Email" id="f-email"><Input type="email" {...f("email")} /></Field>
              <Field label="Preferred course" id="f-preferred_course"><Input {...f("preferred_course")} /></Field>
              <Field label="Preferred college" id="f-preferred_college"><Input {...f("preferred_college")} /></Field>
              <Field label="Education level" id="f-education_level"><Input {...f("education_level")} /></Field>
              <Field label="Academic marks" id="f-academic_marks"><Input type="number" step="any" {...f("academic_marks")} /></Field>
              <Field label="Preferred location" id="f-preferred_location"><Input {...f("preferred_location")} /></Field>
              <Field label="Admission timeline" id="f-admission_timeline"><Input {...f("admission_timeline")} /></Field>
              <Field label="Budget min (₹)" id="f-budget_min"><Input type="number" {...f("budget_min")} /></Field>
              <Field label="Budget max (₹)" id="f-budget_max"><Input type="number" {...f("budget_max")} /></Field>
              <div className="flex justify-end sm:col-span-2"><Button type="submit" loading={busy}>Save changes</Button></div>
            </form>
            <p className="mt-3 text-xs text-muted">Budget: {inr(lead.budget_min)} – {inr(lead.budget_max)}
              {prov("preferred_course") && ` · Course source: ${prov("preferred_course").source.startsWith("user:") ? "staff entry" : prov("preferred_course").source} (${fmtDate(prov("preferred_course").at)})`}</p>
          </Card>

          <Card className="p-5">
            <h2 className="mb-4 font-semibold">Activity timeline</h2>
            <form className="mb-5 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (!note.trim()) return; act(async () => { await api(`/leads/${id}/notes`, { method: "POST", json: { text: note } }); setNote(""); }, "Note added"); }}>
              <label htmlFor="note" className="sr-only">Add a note</label>
              <Textarea id="note" rows={2} placeholder="Add a note…" value={note} onChange={(e) => setNote(e.target.value)} />
              <Button type="submit" variant="secondary" disabled={!note.trim()}>Add</Button>
            </form>
            {acts.length === 0 ? <EmptyState title="No activity yet" /> : (
              <ol className="relative space-y-4 border-l border-line pl-6">
                {acts.map((a) => (
                  <li key={a.id} className="relative">
                    <span aria-hidden className="absolute -left-[2.15rem] grid h-6 w-6 place-items-center rounded-full bg-brand-50 text-xs text-brand-700 ring-4 ring-white">{KIND_ICON[a.kind] ?? "•"}</span>
                    <p className="whitespace-pre-wrap text-sm">{a.message}</p>
                    <p className="text-xs text-muted">{who(a.actor_id)} · {fmtDate(a.created_at)}</p>
                  </li>))}
              </ol>)}
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="space-y-3 p-5">
            <h2 className="font-semibold">Status & ownership</h2>
            <Field label="Status" id="status"><Select id="status" value={lead.status} disabled={busy} onChange={(e) => act(() => api(`/leads/${id}`, { method: "PATCH", json: { status: e.target.value } }), "Status updated")}>
              {statuses.map((s) => <option key={s}>{s}</option>)}</Select></Field>
            <Field label="Assigned counsellor" id="assign">
              {isManager ? <Select id="assign" value={lead.assigned_to ?? ""} disabled={busy} onChange={(e) => act(() => api(`/leads/${id}/assign`, { method: "POST", json: { assigned_to: e.target.value || null } }), "Assignment updated")}>
                <option value="">Unassigned</option>{team.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name} ({m.role})</option>)}</Select>
                : <p className="text-sm">{who(lead.assigned_to)}</p>}</Field>
            <dl className="grid grid-cols-2 gap-2 text-sm"><dt className="text-muted">Source</dt><dd>{lead.source_name ?? "-"}</dd>
              <dt className="text-muted">Qualification</dt><dd>{lead.qualification_category ?? "Not assessed"}</dd>
              <dt className="text-muted">Last contact</dt><dd>{fmtDate(lead.last_contact_at)}</dd>
              <dt className="text-muted">Next follow-up</dt><dd>{fmtDate(lead.next_follow_up_at)}</dd></dl>
          </Card>

          <Card className="p-5">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-semibold">Qualification result</h2>
              <Button variant="secondary" disabled={busy} onClick={() => act(() => api(`/leads/${id}/qualify`, { method: "POST" }), "Lead re-qualified")}>
                Re-qualify
              </Button>
            </div>
            <div className="mb-3 flex items-center gap-2">
              <Badge tone={lead.qualification_category === "eligible" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : lead.qualification_category === "ineligible" ? "bg-rose-50 text-rose-700 ring-rose-600/20" : "bg-amber-50 text-amber-700 ring-amber-600/20"}>
                {lead.qualification_category ? lead.qualification_category.toUpperCase() : "NOT ASSESSED"}
              </Badge>
              {lead.qualification_score != null && (
                <span className="text-xs font-semibold text-slate-700">
                  Priority score: {lead.qualification_score}/100
                </span>
              )}
            </div>
            {lead.qualification_score != null && (
              <div className="mb-3 h-2 w-full rounded-full bg-slate-100">
                <div
                  className={`h-2 rounded-full ${lead.qualification_category === "eligible" ? "bg-emerald-500" : lead.qualification_category === "ineligible" ? "bg-rose-500" : "bg-amber-500"}`}
                  style={{ width: `${lead.qualification_score}%` }}
                />
              </div>
            )}
            {qualHistory.length > 0 && (
              <div className="space-y-2 border-t border-line pt-2 text-xs text-slate-600">
                <p><b>Recommended next action:</b> {qualHistory[0].next_action}</p>
                {qualHistory[0].reasons.length > 0 && (
                  <div>
                    <span className="font-medium text-emerald-700">Supporting factors:</span>
                    <ul className="list-disc pl-4 text-emerald-800">
                      {qualHistory[0].reasons.map((r, i) => <li key={i}>{r}</li>)}
                    </ul>
                  </div>
                )}
                {qualHistory[0].hard_failures.length > 0 && (
                  <div>
                    <span className="font-medium text-rose-700">Hard criteria failures:</span>
                    <ul className="list-disc pl-4 text-rose-800">
                      {qualHistory[0].hard_failures.map((f, i) => <li key={i}>{f}</li>)}
                    </ul>
                  </div>
                )}
                {qualHistory[0].missing_fields.length > 0 && (
                  <div>
                    <span className="font-medium text-amber-700">Missing fields:</span>
                    <p className="text-amber-800">{qualHistory[0].missing_fields.join(", ")}</p>
                  </div>
                )}
              </div>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 font-semibold">Follow-ups</h2>
            {tasks.length === 0 ? <p className="mb-3 text-sm text-muted">No open follow-ups.</p> : (
              <ul className="mb-3 space-y-2">{tasks.map((t) => (
                <li key={t.id} className="flex items-start gap-2 text-sm">
                  <input type="checkbox" aria-label={`Complete ${t.title}`} className="mt-1" onChange={() => act(() => api(`/tasks/${t.id}`, { method: "PATCH", json: { status: "done" } }), "Task completed")} />
                  <div><p>{t.title}</p><p className="text-xs text-muted">Due {fmtDate(t.due_at)}</p></div></li>))}</ul>)}
            <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); act(async () => { await api(`/leads/${id}/tasks`, { method: "POST", json: { title: task.title, due_at: new Date(task.due_at).toISOString() } }); setTask({ title: "", due_at: "" }); }, "Follow-up created"); }}>
              <Input aria-label="Follow-up title" placeholder="e.g. Call parents about fees" required value={task.title} onChange={(e) => setTask({ ...task, title: e.target.value })} />
              <Input aria-label="Due date and time" type="datetime-local" required value={task.due_at} onChange={(e) => setTask({ ...task, due_at: e.target.value })} />
              <Button type="submit" variant="secondary" className="w-full" disabled={busy}>Add follow-up</Button>
            </form>
          </Card>

          <Card className="p-5">
            <h2 className="mb-1 font-semibold">Consent</h2>
            <p className="mb-3 text-xs text-muted">Every grant or withdrawal is recorded; history is never overwritten.</p>
            <ul className="mb-3 space-y-2">{PURPOSES.map(([p, label]) => {
              const s = lead.consent?.[p] ?? "none";
              return (<li key={p} className="flex items-center justify-between text-sm"><span>{label}</span>
                <span className="flex items-center gap-2"><Badge tone={s === "granted" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : s === "withdrawn" ? "bg-rose-50 text-rose-700 ring-rose-600/20" : undefined}>{s}</Badge>
                  {s === "granted" && <button className="text-xs text-rose-600 hover:underline" disabled={busy} onClick={() => act(() => api(`/leads/${id}/consent`, { method: "POST", json: { purpose: p, status: "withdrawn" } }), "Consent withdrawn")}>Withdraw</button>}</span></li>);
            })}</ul>
            {!lead.do_not_contact && <div className="space-y-2 border-t border-line pt-3">
              <Input aria-label="How was consent obtained?" placeholder="How was consent obtained? (required)" value={consentNote} onChange={(e) => setConsentNote(e.target.value)} />
              <Button variant="secondary" className="w-full" disabled={busy || !consentNote.trim()} onClick={() => act(async () => { await api(`/leads/${id}/consent`, { method: "POST", json: { purpose: "automated_calls", status: "granted", evidence: { note: consentNote } } }); setConsentNote(""); }, "Consent recorded")}>Record call consent</Button></div>}
            {consents.length > 0 && <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer">History ({consents.length})</summary>
              <ul className="mt-2 space-y-1">{consents.map((c) => <li key={c.id}>{fmtDate(c.created_at)}: {c.purpose} {c.status} via {c.source}{c.evidence?.note ? ` (${c.evidence.note})` : ""}</li>)}</ul></details>}
          </Card>
        </div>
      </div>

      {/* Call Details & Transcript Modal */}
      {selectedCall && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between border-b border-line pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-slate-900">Call Record & Transcript</h3>
                  <span className="rounded bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-700">
                    Synthetic Call
                  </span>
                </div>
                <p className="text-xs text-slate-500">
                  Attempt ID: {selectedCall.id} · {fmtDate(selectedCall.created_at)}
                </p>
              </div>
              <button
                type="button"
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                onClick={() => setSelectedCall(null)}
              >
                ✕
              </button>
            </div>

            <div className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-4">
                <div>
                  <span className="text-slate-500">Outcome</span>
                  <p className="font-semibold text-slate-800">{selectedCall.outcome ?? selectedCall.status}</p>
                </div>
                <div>
                  <span className="text-slate-500">Duration</span>
                  <p className="font-semibold text-slate-800">{selectedCall.duration_seconds ?? 0}s</p>
                </div>
                <div>
                  <span className="text-slate-500">Telephony Provider</span>
                  <p className="font-semibold capitalize text-slate-800">{selectedCall.provider}</p>
                </div>
                <div>
                  <span className="text-slate-500">Simulated Cost</span>
                  <p className="font-semibold text-slate-800">${(selectedCall.cost_cents / 100).toFixed(2)}</p>
                </div>
              </div>

              {selectedCall.summary && (
                <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-indigo-900">
                    AI Conversation Summary
                  </h4>
                  <p className="mt-1 text-sm text-slate-800">{selectedCall.summary.summary}</p>
                  {selectedCall.summary.next_action && (
                    <div className="mt-2 text-xs">
                      <span className="font-semibold text-indigo-900">Recommended Next Action: </span>
                      <span className="text-slate-700">{selectedCall.summary.next_action}</span>
                    </div>
                  )}
                  {selectedCall.summary.extracted_fields && Object.keys(selectedCall.summary.extracted_fields).length > 0 && (
                    <div className="mt-2 border-t border-indigo-200/50 pt-2 text-xs">
                      <span className="font-semibold text-indigo-900">Extracted Fields: </span>
                      <code className="text-slate-700">
                        {JSON.stringify(selectedCall.summary.extracted_fields, null, 2)}
                      </code>
                    </div>
                  )}
                </div>
              )}

              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Conversation Transcript
                </h4>
                {selectedCall.transcript ? (
                  <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 font-mono text-xs text-slate-100">
                    {selectedCall.transcript}
                  </pre>
                ) : (
                  <p className="text-xs italic text-slate-400">No transcript available for this call attempt.</p>
                )}
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <Button variant="secondary" onClick={() => setSelectedCall(null)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
