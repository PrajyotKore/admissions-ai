"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Select,
  fmtDate,
  useToast,
} from "@/components/ui";
import { useApp } from "../app-shell";

type CallAttemptItem = {
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

type CallDetail = CallAttemptItem & {
  transcript: string | null;
  summary: {
    summary: string | null;
    extracted_fields: Record<string, unknown>;
    next_action: string | null;
    is_ai_generated: boolean;
  } | null;
};

type CallJobItem = {
  id: string;
  lead_id: string;
  lead_name: string | null;
  status: string;
  run_at: string;
  attempts: number;
  max_attempts: number;
  trigger: string;
  last_error: string | null;
  created_at: string;
};

type HistoryResponse = {
  items: CallAttemptItem[];
  total: number;
  page: number;
  page_size: number;
};

export default function CallsPage() {
  const { isManager } = useApp();
  const toast = useToast();
  const [tab, setTab] = useState<"history" | "queue">("history");
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [queue, setQueue] = useState<CallJobItem[]>([]);
  const [outcomeFilter, setOutcomeFilter] = useState<string>("");
  const [page, setPage] = useState<number>(1);
  const [isCallingPaused, setIsCallingPaused] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [err, setErr] = useState<string>("");
  const [selectedCall, setSelectedCall] = useState<CallDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(false);
  const [actionBusy, setActionBusy] = useState<boolean>(false);

  const loadData = useCallback(async () => {
    try {
      const outcomeQuery = outcomeFilter ? `&outcome=${encodeURIComponent(outcomeFilter)}` : "";
      const [hRes, qRes, settingsRes] = await Promise.all([
        api<HistoryResponse>(`/calls/history?page=${page}&page_size=20${outcomeQuery}`),
        api<CallJobItem[]>("/calls/queue"),
        api<{ calling_paused: boolean }>("/settings"),
      ]);
      setHistory(hRes);
      setQueue(qRes);
      setIsCallingPaused(settingsRes.calling_paused);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load calls");
    } finally {
      setLoading(false);
    }
  }, [outcomeFilter, page]);

  useEffect(() => {
    let ignore = false;
    const outcomeQuery = outcomeFilter ? `&outcome=${encodeURIComponent(outcomeFilter)}` : "";
    Promise.all([
      api<HistoryResponse>(`/calls/history?page=${page}&page_size=20${outcomeQuery}`),
      api<CallJobItem[]>("/calls/queue"),
      api<{ calling_paused: boolean }>("/settings"),
    ])
      .then(([hRes, qRes, settingsRes]) => {
        if (!ignore) {
          setHistory(hRes);
          setQueue(qRes);
          setIsCallingPaused(settingsRes.calling_paused);
          setErr("");
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!ignore) {
          setErr(e instanceof Error ? e.message : "Failed to load calls");
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [outcomeFilter, page]);

  async function openAttemptDetail(id: string) {
    setLoadingDetail(true);
    try {
      const detail = await api<CallDetail>(`/calls/attempts/${id}`);
      setSelectedCall(detail);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to load call detail");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function toggleCallingPause() {
    setActionBusy(true);
    try {
      const next = !isCallingPaused;
      await api<{ calling_paused: boolean }>(`/calls/queue/pause?paused=${next}`, { method: "POST" });
      setIsCallingPaused(next);
      toast("success", next ? "Calling queue paused" : "Calling queue resumed");
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to toggle queue pause");
    } finally {
      setActionBusy(false);
    }
  }

  async function processQueueBatch() {
    setActionBusy(true);
    try {
      const res = await api<{ processed: number }>("/calls/queue/process", { method: "POST" });
      toast("success", `Processed ${res.processed} pending calls`);
      await loadData();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to process queue");
    } finally {
      setActionBusy(false);
    }
  }

  async function cancelQueueJob(jobId: string) {
    setActionBusy(true);
    try {
      await api(`/calls/queue/${jobId}/cancel`, { method: "POST" });
      toast("success", "Call job cancelled");
      await loadData();
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Failed to cancel job");
    } finally {
      setActionBusy(false);
    }
  }

  if (loading) return <Loading />;
  if (err) return <ErrorState message={err} onRetry={loadData} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Voice Calling & Telephony"
        subtitle="Compliant, grounded voice outreach with automated transcripts and CRM intelligence sync."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {isManager && (
              <>
                <Button
                  variant={isCallingPaused ? "primary" : "secondary"}
                  onClick={toggleCallingPause}
                  disabled={actionBusy}
                  className={isCallingPaused ? "bg-amber-600 hover:bg-amber-700" : ""}
                >
                  {isCallingPaused ? "▶ Resume Calling Queue" : "⏸ Pause Calling Queue"}
                </Button>
                <Button variant="secondary" onClick={processQueueBatch} disabled={actionBusy}>
                  ⚡ Process Due Calls
                </Button>
              </>
            )}
          </div>
        }
      />

      {/* Compliance & Telephony Engine Indicator */}
      <Card className="border-indigo-100 bg-gradient-to-r from-indigo-50/70 via-white to-sky-50/50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-500 ring-2 ring-emerald-200" />
            <span className="font-semibold text-slate-800">Compliance & Telephony Engine Active</span>
            <span className="rounded bg-indigo-100 px-2 py-0.5 font-medium text-indigo-800">
              Provider: Mock Telephony (is_synthetic=True)
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-slate-600">
            <span>• E.164 Verified Indian (+91) Numbers</span>
            <span>• Quiet Hours (9 PM - 9 AM) Enforced</span>
            <span>• Consent Verified Prior to Dialing</span>
            <span>• DNC Auto-Blocked</span>
          </div>
        </div>
      </Card>

      {/* Tabs */}
      <div className="flex items-center justify-between border-b border-line">
        <div className="flex gap-4">
          <button
            type="button"
            className={`border-b-2 pb-2 text-sm font-semibold transition ${
              tab === "history"
                ? "border-brand-600 text-brand-600"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
            onClick={() => setTab("history")}
          >
            Call History & Transcripts ({history?.total ?? 0})
          </button>
          <button
            type="button"
            className={`border-b-2 pb-2 text-sm font-semibold transition ${
              tab === "queue"
                ? "border-brand-600 text-brand-600"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
            onClick={() => setTab("queue")}
          >
            Pending Call Queue ({queue.length})
          </button>
        </div>

        {tab === "history" && (
          <div className="flex items-center gap-2 pb-2">
            <label htmlFor="outcome-filter" className="text-xs font-medium text-slate-500">
              Outcome:
            </label>
            <Select
              id="outcome-filter"
              value={outcomeFilter}
              onChange={(e) => {
                setOutcomeFilter(e.target.value);
                setPage(1);
              }}
              className="py-1 text-xs"
            >
              <option value="">All Outcomes</option>
              <option value="Interested">Interested</option>
              <option value="Appointment Booked">Appointment Booked</option>
              <option value="Callback Requested">Callback Requested</option>
              <option value="Not Interested">Not Interested</option>
              <option value="Escalation Required">Escalation Required</option>
              <option value="no_answer">No Answer</option>
              <option value="busy">Busy</option>
              <option value="failed">Failed</option>
            </Select>
          </div>
        )}
      </div>

      {/* Tab: History */}
      {tab === "history" && (
        <div className="space-y-4">
          {!history || history.items.length === 0 ? (
            <Card className="p-8">
              <EmptyState
                title="No call attempts recorded"
                hint="Calls can be triggered directly from any eligible student profile or via automated intake."
              />
            </Card>
          ) : (
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-line bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Student Lead</th>
                      <th className="px-4 py-3">Outcome</th>
                      <th className="px-4 py-3">Duration</th>
                      <th className="px-4 py-3">Provider / Flag</th>
                      <th className="px-4 py-3">Date & Time</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {history.items.map((item) => (
                      <tr key={item.id} className="hover:bg-slate-50/70">
                        <td className="px-4 py-3 font-medium text-slate-900">
                          {item.lead_name ? (
                            <Link
                              href={`/leads/${item.lead_id}`}
                              className="text-brand-600 hover:underline"
                            >
                              {item.lead_name}
                            </Link>
                          ) : (
                            <span className="text-slate-500">Unknown Lead</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
                              item.outcome === "Interested" || item.outcome === "Appointment Booked"
                                ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                                : item.outcome === "Not Interested" || item.outcome === "failed"
                                ? "bg-rose-50 text-rose-700 ring-rose-600/20"
                                : item.outcome === "Callback Requested"
                                ? "bg-amber-50 text-amber-700 ring-amber-600/20"
                                : "bg-slate-100 text-slate-600 ring-slate-500/20"
                            }`}
                          >
                            {item.outcome ?? item.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          {item.duration_seconds != null ? `${item.duration_seconds}s` : "-"}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1.5">
                            <span className="font-mono text-xs uppercase text-slate-600">{item.provider}</span>
                            {item.is_synthetic && (
                              <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700">
                                SYNTHETIC
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(item.created_at)}</td>
                        <td className="px-4 py-3 text-right">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => openAttemptDetail(item.id)}
                            disabled={loadingDetail}
                          >
                            View Transcript
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {history.total > history.page_size && (
                <div className="flex items-center justify-between border-t border-line px-4 py-3 text-xs text-slate-500">
                  <span>
                    Showing {(page - 1) * history.page_size + 1} -{" "}
                    {Math.min(page * history.page_size, history.total)} of {history.total} calls
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={page * history.page_size >= history.total}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          )}
        </div>
      )}

      {/* Tab: Queue */}
      {tab === "queue" && (
        <div className="space-y-4">
          {queue.length === 0 ? (
            <Card className="p-8">
              <EmptyState
                title="Calling queue is clear"
                hint="No pending or scheduled calls at the moment. As leads enter with call consent, jobs are automatically placed in this queue."
              />
            </Card>
          ) : (
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-line bg-slate-50 text-xs font-semibold uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Student Lead</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Scheduled Run At</th>
                      <th className="px-4 py-3">Attempts</th>
                      <th className="px-4 py-3">Trigger Source</th>
                      <th className="px-4 py-3">Last Note / Error</th>
                      {isManager && <th className="px-4 py-3 text-right">Action</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {queue.map((job) => (
                      <tr key={job.id} className="hover:bg-slate-50/70">
                        <td className="px-4 py-3 font-medium text-slate-900">
                          {job.lead_name ? (
                            <Link href={`/leads/${job.lead_id}`} className="text-brand-600 hover:underline">
                              {job.lead_name}
                            </Link>
                          ) : (
                            <span className="text-slate-500">{job.lead_id}</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            tone={
                              job.status === "running"
                                ? "bg-sky-50 text-sky-700 ring-sky-600/20"
                                : job.status === "queued"
                                ? "bg-amber-50 text-amber-700 ring-amber-600/20"
                                : "bg-slate-100 text-slate-600 ring-slate-500/20"
                            }
                          >
                            {job.status}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600">{fmtDate(job.run_at)}</td>
                        <td className="px-4 py-3 text-xs font-medium text-slate-700">
                          {job.attempts} / {job.max_attempts}
                        </td>
                        <td className="px-4 py-3 text-xs font-mono text-slate-500">{job.trigger}</td>
                        <td className="max-w-xs truncate px-4 py-3 text-xs text-slate-500">
                          {job.last_error ?? "-"}
                        </td>
                        {isManager && (
                          <td className="px-4 py-3 text-right">
                            {job.status === "queued" || job.status === "running" ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-rose-600 hover:bg-rose-50"
                                onClick={() => cancelQueueJob(job.id)}
                                disabled={actionBusy}
                              >
                                Cancel
                              </Button>
                            ) : null}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Call Details & Transcript Modal */}
      {selectedCall && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between border-b border-line pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-slate-900">
                    Call Record: {selectedCall.lead_name ?? "Student"}
                  </h3>
                  <span className="rounded bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-700">
                    Synthetic Call
                  </span>
                </div>
                <p className="text-xs text-slate-500">
                  Attempt ID: {selectedCall.id} · Recorded {fmtDate(selectedCall.created_at)}
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
                  <span className="text-slate-500">Telephony Engine</span>
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
                    AI Conversation Summary & Extracted Intelligence
                  </h4>
                  <p className="mt-1 text-sm text-slate-800">{selectedCall.summary.summary}</p>
                  {selectedCall.summary.next_action && (
                    <div className="mt-2 text-xs">
                      <span className="font-semibold text-indigo-900">Recommended Next Action: </span>
                      <span className="text-slate-700">{selectedCall.summary.next_action}</span>
                    </div>
                  )}
                  {selectedCall.summary.extracted_fields &&
                    Object.keys(selectedCall.summary.extracted_fields).length > 0 && (
                      <div className="mt-2 border-t border-indigo-200/50 pt-2 text-xs">
                        <span className="font-semibold text-indigo-900">Extracted Lead Fields: </span>
                        <code className="text-slate-700">
                          {JSON.stringify(selectedCall.summary.extracted_fields, null, 2)}
                        </code>
                      </div>
                    )}
                </div>
              )}

              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Full Conversation Audio Transcript
                </h4>
                {selectedCall.transcript ? (
                  <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 font-mono text-xs text-slate-100">
                    {selectedCall.transcript}
                  </pre>
                ) : (
                  <p className="text-xs italic text-slate-400">No transcript recorded for this call.</p>
                )}
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              {selectedCall.lead_id && (
                <Link href={`/leads/${selectedCall.lead_id}`}>
                  <Button variant="secondary" onClick={() => setSelectedCall(null)}>
                    Go to Student Profile
                  </Button>
                </Link>
              )}
              <Button variant="primary" onClick={() => setSelectedCall(null)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
