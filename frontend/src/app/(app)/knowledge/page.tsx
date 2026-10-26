"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Loading, Modal, PageHeader, Textarea, fmtDate, useToast } from "@/components/ui";
import { useApp } from "../app-shell";

type Doc = {
  id: string;
  organization_id: string;
  title: string;
  content: string;
  is_approved: boolean;
  approved_by: string | null;
  created_at: string;
  updated_at: string;
};

export default function KnowledgePage() {
  const { isManager } = useApp();
  const toast = useToast();
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ title: "", content: "", is_approved: false });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setErr("");
    api<Doc[]>("/knowledge").then(setDocs).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    let ignore = false;
    api<Doc[]>("/knowledge")
      .then((data) => {
        if (!ignore) {
          setDocs(data);
          setErr("");
        }
      })
      .catch((e) => {
        if (!ignore) setErr(e.message);
      });
    return () => { ignore = true; };
  }, []);

  async function createDoc(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/knowledge", { method: "POST", json: f });
      toast("success", "Document added to knowledge base");
      setOpen(false);
      setF({ title: "", content: "", is_approved: false });
      load();
    } catch (er) {
      toast("error", er instanceof Error ? er.message : "Failed to add document");
    } finally {
      setBusy(false);
    }
  }

  async function toggleApproval(doc: Doc) {
    try {
      await api(`/knowledge/${doc.id}`, {
        method: "PATCH",
        json: { is_approved: !doc.is_approved },
      });
      toast("success", doc.is_approved ? "Document moved to draft" : "Document approved for AI usage");
      load();
    } catch (er) {
      toast("error", er instanceof Error ? er.message : "Failed to update approval");
    }
  }

  async function removeDoc(doc: Doc) {
    if (!confirm(`Delete "${doc.title}" from knowledge base?`)) return;
    try {
      await api(`/knowledge/${doc.id}`, { method: "DELETE" });
      toast("success", "Document removed");
      load();
    } catch (er) {
      toast("error", er instanceof Error ? er.message : "Failed to remove document");
    }
  }

  if (err) return <ErrorState message={err} onRetry={load} />;
  if (!docs) return <Loading />;

  return (
    <>
      <PageHeader
        title="Knowledge base"
        subtitle="Authorized facts, fee sheets, cutoff marks, and admissions policies"
        actions={isManager && <Button onClick={() => setOpen(true)}>+ Add document</Button>}
      />

      <div className="mb-6 rounded-xl border border-indigo-100 bg-indigo-50/60 p-4 text-xs text-indigo-900">
        <p className="font-semibold">AI Safety & Truthfulness Guardrail</p>
        <p className="mt-1 text-indigo-700">
          The website chatbot and voice calling agent answer prospective students using <b>approved documents only</b>.
          If a student asks about college fees, eligibility, or cutoffs not documented in approved files, the AI will refuse to guess and route the enquiry to a counsellor.
        </p>
      </div>

      {docs.length === 0 ? (
        <EmptyState
          title="No knowledge documents yet"
          hint="Upload verified college brochures, fee schedules, or cutoff rules so your AI assistant can answer student queries accurately."
          action={isManager ? <Button onClick={() => setOpen(true)}>Add your first document</Button> : undefined}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {docs.map((d) => (
            <Card key={d.id} className="flex flex-col justify-between p-5">
              <div>
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h2 className="font-semibold tracking-tight">{d.title}</h2>
                  <Badge tone={d.is_approved ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-amber-50 text-amber-700 ring-amber-600/20"}>
                    {d.is_approved ? "Approved for AI" : "Draft / Unapproved"}
                  </Badge>
                </div>
                <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-sm text-slate-600">
                  {d.content}
                </p>
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-xs text-muted">
                <span>Updated {fmtDate(d.updated_at)}</span>
                {isManager && (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => toggleApproval(d)}>
                      {d.is_approved ? "Revoke approval" : "Approve for AI"}
                    </Button>
                    <button
                      className="text-rose-600 hover:underline"
                      onClick={() => removeDoc(d)}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Add knowledge document">
        <form onSubmit={createDoc} className="space-y-4">
          <Field label="Document title *" id="doc-title">
            <Input
              id="doc-title"
              required
              placeholder="e.g. MBA 2026 Fees & Entrance Cutoffs"
              value={f.title}
              onChange={(e) => setF({ ...f, title: e.target.value })}
            />
          </Field>

          <Field label="Document text / facts *" id="doc-content">
            <Textarea
              id="doc-content"
              rows={8}
              required
              placeholder="Enter verified facts: eligibility criteria, program fees, admission dates, hostel charges, refund policy..."
              value={f.content}
              onChange={(e) => setF({ ...f, content: e.target.value })}
            />
          </Field>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={f.is_approved}
              onChange={(e) => setF({ ...f, is_approved: e.target.checked })}
            />
            <span>Approve immediately (allows AI chatbot & voice agent to use these facts)</span>
          </label>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              Save document
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
