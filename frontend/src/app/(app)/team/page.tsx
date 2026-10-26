"use client";
import { useCallback, useEffect, useState } from "react";
import { api, type Member } from "@/lib/api";
import { Badge, Button, Card, ErrorState, Field, Input, Loading, Modal, PageHeader, Select, useToast } from "@/components/ui";
import { useApp } from "../app-shell";

export default function TeamPage() {
  const { org, isManager, session } = useApp();
  const toast = useToast();
  const [team, setTeam] = useState<Member[] | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", full_name: "", role: "counsellor", password: "" });
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    setErr("");
    api<Member[]>("/team").then(setTeam).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    let ignore = false;
    api<Member[]>("/team")
      .then((res) => { if (!ignore) { setTeam(res); setErr(""); } })
      .catch((e) => { if (!ignore) setErr(e.message); });
    return () => { ignore = true; };
  }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try { await api("/team", { method: "POST", json: { ...f, password: f.password || undefined } }); toast("success", "Member added"); setOpen(false); setF({ email: "", full_name: "", role: "counsellor", password: "" }); load(); }
    catch (er) { toast("error", er instanceof Error ? er.message : "Failed"); } finally { setBusy(false); }
  }
  if (err) return <ErrorState message={err} onRetry={load} />;
  if (!team) return <Loading />;
  const isOwner = org.role === "owner";
  return (
    <>
      <PageHeader title="Team & permissions" subtitle="Owners and managers manage everything; counsellors only see leads assigned to them"
        actions={isManager && <Button onClick={() => setOpen(true)}>+ Add member</Button>} />
      <Card className="overflow-x-auto"><table className="w-full text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted"><tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Email</th><th className="px-4 py-3 text-left">Role</th><th /></tr></thead>
        <tbody className="divide-y divide-line">{team.map((m) => (
          <tr key={m.user_id}><td className="px-4 py-3 font-medium">{m.full_name}{m.user_id === session.user.id && <span className="ml-2 text-xs text-muted">(you)</span>}</td>
            <td className="px-4 py-3 text-muted">{m.email}</td>
            <td className="px-4 py-3">{isOwner && m.user_id !== session.user.id ? (
              <Select aria-label={`Role for ${m.full_name}`} value={m.role} onChange={async (e) => { try { await api(`/team/${m.user_id}`, { method: "PATCH", json: { role: e.target.value } }); toast("success", "Role updated"); load(); } catch (er) { toast("error", er instanceof Error ? er.message : "Failed"); } }}>
                <option value="owner">owner</option><option value="manager">manager</option><option value="counsellor">counsellor</option></Select>) : <Badge tone="bg-brand-50 text-brand-700 ring-brand-600/20">{m.role}</Badge>}</td>
            <td className="px-4 py-3 text-right">{isOwner && m.role !== "owner" && <button className="text-xs text-rose-600 hover:underline" onClick={async () => {
              if (!confirm(`Remove ${m.full_name} from this organization?`)) return;
              try { await api(`/team/${m.user_id}`, { method: "DELETE" }); toast("success", "Member removed"); load(); } catch (er) { toast("error", er instanceof Error ? er.message : "Failed"); } }}>Remove</button>}</td></tr>))}</tbody></table></Card>
      <Modal open={open} onClose={() => setOpen(false)} title="Add team member">
        <form onSubmit={add} className="space-y-3">
          <Field label="Full name" id="tm-name"><Input id="tm-name" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Email" id="tm-email"><Input id="tm-email" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Role" id="tm-role"><Select id="tm-role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {isOwner && <option value="owner">owner</option>}<option value="manager">manager</option><option value="counsellor">counsellor</option></Select></Field>
          <Field label="Temporary password (new users only, min 10 chars)" id="tm-pw"><Input id="tm-pw" type="password" minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={busy}>Add member</Button></div>
        </form>
      </Modal>
    </>
  );
}
