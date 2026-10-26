"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type Task } from "@/lib/api";
import { Card, EmptyState, ErrorState, Loading, PageHeader, fmtDate, useToast } from "@/components/ui";

export default function TasksPage() {
  const toast = useToast();
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [err, setErr] = useState("");
  const [mountedNow, setMountedNow] = useState<number | null>(null);

  const load = useCallback(() => {
    setErr("");
    api<Task[]>("/tasks?status=open").then(setTasks).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    let ignore = false;
    api<Task[]>("/tasks?status=open")
      .then((data) => {
        if (!ignore) {
          setTasks(data);
          setErr("");
          setMountedNow(Date.now());
        }
      })
      .catch((e) => {
        if (!ignore) setErr(e.message);
      });
    return () => { ignore = true; };
  }, []);

  if (err) return <ErrorState message={err} onRetry={load} />;
  if (!tasks) return <Loading />;

  return (
    <>
      <PageHeader title="Follow-ups" subtitle="Open follow-up tasks, soonest first" />
      <Card>
        {tasks.length === 0 ? <EmptyState title="You're all caught up" hint="Add follow-ups from a lead's detail page." /> : (
          <ul className="divide-y divide-line">{tasks.map((t) => {
            const overdue = mountedNow ? new Date(t.due_at).getTime() < mountedNow : false;
            return (
              <li key={t.id} className="flex items-center gap-3 p-4">
                <input type="checkbox" aria-label={`Complete ${t.title}`} onChange={async () => {
                  try { await api(`/tasks/${t.id}`, { method: "PATCH", json: { status: "done" } }); toast("success", "Task completed"); load(); } catch (e) { toast("error", e instanceof Error ? e.message : "Failed"); } }} />
                <div className="min-w-0 flex-1"><p className="font-medium">{t.title}</p>
                  <p className={`text-xs ${overdue ? "font-medium text-rose-600" : "text-muted"}`}>{overdue ? "Overdue · " : ""}Due {fmtDate(t.due_at)}</p></div>
                <Link href={`/leads/${t.lead_id}`} className="text-sm text-brand-700 hover:underline">Open lead</Link>
              </li>);
          })}</ul>)}
      </Card>
    </>
  );
}
