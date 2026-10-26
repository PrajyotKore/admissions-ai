"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, ErrorState, Loading, PageHeader, EmptyState } from "@/components/ui";
import { useApp } from "../app-shell";

type Ratio = { numerator: number; denominator: number; value: number | null; definition: string };
type Dash = {
  window_days: number; total_leads: number; leads_by_status: Record<string, number>;
  leads_by_source: Record<string, number>; new_leads_over_time: { date: string; count: number }[];
  qualified_leads: number; qualification_rate: Ratio; calls_attempted: number; calls_completed: number;
  contact_rate: Ratio; appointments_booked: number; conversion_rate: Ratio; estimated_cost_cents: number;
  synthetic_cost_cents_excluded: number; follow_ups_due: number; failed_calls_needing_attention: number;
};

const pct = (r: Ratio) => (r.value == null ? "-" : `${(r.value * 100).toFixed(1)}%`);

function Stat({ label, value, sub, tone }: { label: string; value: string | number; sub?: string; tone?: string }) {
  return (
    <Card className="animate-fade-up p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-1 text-3xl font-semibold tracking-tight ${tone ?? ""}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-muted" title={sub}>{sub}</p>}
    </Card>
  );
}

function Bars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map((e) => e[1]));
  if (!entries.length) return <p className="py-6 text-center text-sm text-muted">No data yet</p>;
  return (
    <ul className="space-y-2.5">
      {entries.map(([k, v]) => (
        <li key={k} className="text-sm">
          <div className="mb-1 flex justify-between"><span>{k}</span><span className="font-medium">{v}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-sky-400 transition-all duration-700" style={{ width: `${(v / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function Dashboard() {
  const { org } = useApp();
  const [d, setD] = useState<Dash | null>(null);
  const [err, setErr] = useState("");
  const [days, setDays] = useState(30);
  const load = useCallback(() => {
    setD(null); setErr("");
    api<Dash>(`/dashboard?days=${days}`).then(setD).catch((e) => setErr(e.message));
  }, [days]);

  useEffect(() => {
    let ignore = false;
    api<Dash>(`/dashboard?days=${days}`)
      .then((data) => { if (!ignore) { setD(data); setErr(""); } })
      .catch((e) => { if (!ignore) setErr(e.message); });
    return () => { ignore = true; };
  }, [days]);

  if (err) return <ErrorState message={err} onRetry={load} />;
  if (!d) return <Loading />;
  const maxDay = Math.max(1, ...d.new_leads_over_time.map((p) => p.count));

  return (
    <>
      <PageHeader title="Dashboard" subtitle={`${org.name}: figures use only this organization's stored data`}
        actions={<select aria-label="Time window" value={days} onChange={(e) => setDays(+e.target.value)}
          className="rounded-lg border border-line bg-white px-2 py-1.5 text-sm">
          {[7, 30, 90, 365].map((n) => <option key={n} value={n}>Last {n} days</option>)}</select>} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total leads" value={d.total_leads} />
        <Stat label="Qualified leads" value={d.qualified_leads} sub={`Qualification rate ${pct(d.qualification_rate)}`} />
        <Stat label="Follow-ups due" value={d.follow_ups_due} tone={d.follow_ups_due ? "text-amber-600" : ""} />
        <Stat label="Failed calls to review" value={d.failed_calls_needing_attention} tone={d.failed_calls_needing_attention ? "text-rose-600" : ""} />
        <Stat label="Calls attempted" value={d.calls_attempted} sub={`${d.calls_completed} completed`} />
        <Stat label="Contact rate" value={pct(d.contact_rate)} sub={`${d.contact_rate.numerator} of ${d.contact_rate.denominator} attempts`} />
        <Stat label="Appointments booked" value={d.appointments_booked} />
        <Stat label="Conversion rate" value={pct(d.conversion_rate)} sub={`${d.conversion_rate.numerator} of ${d.conversion_rate.denominator} closed leads`} />
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <h2 className="mb-4 font-semibold">New leads, last {d.window_days} days</h2>
          {d.new_leads_over_time.length === 0 ? <EmptyState title="No new leads in this window" hint="Add leads manually, import a CSV, or embed the chatbot." /> : (
            <div className="flex h-40 items-end gap-1" role="img" aria-label="New leads per day">
              {d.new_leads_over_time.map((p) => (
                <div key={p.date} title={`${p.date}: ${p.count}`} className="min-w-1 flex-1 rounded-t bg-gradient-to-t from-brand-600 to-brand-500/70 transition-all hover:opacity-80"
                  style={{ height: `${(p.count / maxDay) * 100}%` }} />
              ))}
            </div>
          )}
        </Card>
        <Card className="p-5"><h2 className="mb-4 font-semibold">By source</h2><Bars data={d.leads_by_source} /></Card>
        <Card className="p-5 lg:col-span-3"><h2 className="mb-4 font-semibold">By status</h2><Bars data={d.leads_by_status} /></Card>
      </div>
      <Card className="mt-6 p-5 text-sm text-muted">
        <h2 className="mb-2 font-semibold text-ink">Metric definitions</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>Qualification rate: {d.qualification_rate.definition}</li>
          <li>Contact rate: {d.contact_rate.definition}</li>
          <li>Conversion rate: {d.conversion_rate.definition}</li>
          <li>Estimated cost: ₹{(d.estimated_cost_cents / 100).toFixed(2)} from real calls only; synthetic (mock) call cost is excluded.</li>
        </ul>
      </Card>
    </>
  );
}
