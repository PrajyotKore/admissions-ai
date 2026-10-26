"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorState, Field, Input, Loading, PageHeader, Textarea, useToast } from "@/components/ui";
import { useApp } from "../app-shell";

type S = { organization: { id: string; name: string; public_key: string }; timezone: string; lead_statuses: string[]; retention_days: number; calling_paused: boolean };

export default function SettingsPage() {
  const { isManager } = useApp();
  const toast = useToast();
  const [s, setS] = useState<S | null>(null);
  const [err, setErr] = useState("");
  const [statuses, setStatuses] = useState("");
  const [tz, setTz] = useState("");
  const [ret, setRet] = useState(365);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<S>("/settings").then((r) => { setS(r); setStatuses(r.lead_statuses.join("\n")); setTz(r.timezone); setRet(r.retention_days); }).catch((e) => setErr(e.message));
  }, []);
  if (err) return <ErrorState message={err} />;
  if (!s) return <Loading />;
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try {
      const r = await api<S>("/settings", { method: "PATCH", json: { timezone: tz, retention_days: ret, lead_statuses: statuses.split("\n").map((x) => x.trim()).filter(Boolean) } });
      setS(r); toast("success", "Settings saved");
    } catch (er) { toast("error", er instanceof Error ? er.message : "Failed"); } finally { setBusy(false); }
  }
  return (
    <>
      <PageHeader title="Organization settings" subtitle={s.organization.name} />
      <Card className="max-w-2xl p-5">
        <form onSubmit={save} className="space-y-4">
          <Field label="Time zone (IANA name)" id="tz"><Input id="tz" value={tz} disabled={!isManager} onChange={(e) => setTz(e.target.value)} /></Field>
          <Field label="Lead statuses (one per line)" id="st"><Textarea id="st" rows={9} value={statuses} disabled={!isManager} onChange={(e) => setStatuses(e.target.value)} />
            <p className="text-xs text-muted">&quot;New&quot;, &quot;Invalid&quot; and &quot;Do Not Contact&quot; are required.</p></Field>
          <Field label="Data retention (days)" id="ret"><Input id="ret" type="number" min={1} max={3650} value={ret} disabled={!isManager} onChange={(e) => setRet(+e.target.value)} /></Field>
          <Field label="Public key (used by the embeddable chatbot/lead form)" id="pk"><Input id="pk" readOnly value={s.organization.public_key} /></Field>
          {isManager ? <Button type="submit" loading={busy}>Save settings</Button> : <p className="text-sm text-muted">Only owners and managers can change settings.</p>}
        </form>
      </Card>

      <Card className="mt-6 max-w-2xl p-5">
        <h2 className="text-base font-semibold">Website Chatbot & Lead Form Embed</h2>
        <p className="mt-1 text-xs text-muted">
          Embed the AI admissions assistant or the standard lead form directly onto your consultancy website.
        </p>

        <div className="mt-4 space-y-4 text-xs">
          <div>
            <span className="font-medium text-slate-700">1. Direct Chatbot Link</span>
            <div className="mt-1 flex items-center gap-2">
              <Input
                readOnly
                value={typeof window !== "undefined" ? `${window.location.origin}/widget/chat?key=${s.organization.public_key}` : `/widget/chat?key=${s.organization.public_key}`}
              />
              <a
                href={`/widget/chat?key=${s.organization.public_key}`}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 rounded-lg border border-line bg-slate-50 px-3 py-2 font-medium text-brand-600 hover:bg-slate-100"
              >
                Preview ↗
              </a>
            </div>
          </div>

          <div>
            <span className="font-medium text-slate-700">2. Fallback Lead Form Link</span>
            <div className="mt-1 flex items-center gap-2">
              <Input
                readOnly
                value={typeof window !== "undefined" ? `${window.location.origin}/widget/form?key=${s.organization.public_key}` : `/widget/form?key=${s.organization.public_key}`}
              />
              <a
                href={`/widget/form?key=${s.organization.public_key}`}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 rounded-lg border border-line bg-slate-50 px-3 py-2 font-medium text-brand-600 hover:bg-slate-100"
              >
                Preview ↗
              </a>
            </div>
          </div>

          <div>
            <span className="font-medium text-slate-700">3. Iframe Embed Code for Your Website</span>
            <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] text-slate-200">
{`<iframe
  src="${typeof window !== "undefined" ? window.location.origin : ""}/widget/chat?key=${s.organization.public_key}"
  width="420"
  height="600"
  style="border:none;border-radius:16px;box-shadow:0 10px 25px rgba(0,0,0,0.15);"
></iframe>`}
            </pre>
          </div>
        </div>
      </Card>
    </>
  );
}
