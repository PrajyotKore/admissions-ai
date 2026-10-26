"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button, Card, Field, Input, Loading, Select } from "@/components/ui";

type Config = {
  organization_name: string;
  is_demo: boolean;
  consent_disclaimer: string;
  courses_offered: string[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

function FormInner() {
  const searchParams = useSearchParams();
  const key = searchParams.get("key") ?? "";

  const [cfg, setCfg] = useState<Config | null>(null);
  const [f, setF] = useState({
    name: "",
    phone: "",
    email: "",
    preferred_course: "",
    preferred_location: "",
    academic_marks: "",
    budget_max: "",
    admission_timeline: "This year",
    consent_automated_calls: false,
    consent_marketing: false,
  });
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [err, setErr] = useState(() => (!key ? "Missing organization public key (?key=...)" : ""));

  useEffect(() => {
    if (!key) return;
    let ignore = false;
    fetch(`${API_BASE}/public/config?key=${encodeURIComponent(key)}`)
      .then((res) => {
        if (!res.ok) throw new Error("Invalid organization public key");
        return res.json();
      })
      .then((data) => {
        if (!ignore) setCfg(data);
      })
      .catch((e) => {
        if (!ignore) setErr(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [key]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");

    try {
      const res = await fetch(`${API_BASE}/public/lead`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          public_key: key,
          name: f.name,
          phone: f.phone,
          email: f.email || null,
          preferred_course: f.preferred_course || null,
          preferred_location: f.preferred_location || null,
          academic_marks: f.academic_marks ? Number(f.academic_marks) : null,
          budget_max: f.budget_max ? Number(f.budget_max) : null,
          admission_timeline: f.admission_timeline || null,
          consent_automated_calls: f.consent_automated_calls,
          consent_marketing: f.consent_marketing,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail ?? "Failed to submit enquiry");
      }

      setSubmitted(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Submission failed");
    } finally {
      setBusy(false);
    }
  }

  if (err && !cfg) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-50 p-4">
        <div className="max-w-md rounded-2xl border border-rose-200 bg-white p-6 text-center shadow-lg">
          <p className="text-sm font-semibold text-rose-600">Configuration Error</p>
          <p className="mt-1 text-xs text-muted">{err}</p>
        </div>
      </div>
    );
  }

  if (!cfg) return <Loading />;

  return (
    <div className="min-h-screen bg-slate-50 py-10 px-4">
      <div className="mx-auto max-w-xl">
        <Card className="p-6 sm:p-8">
          <div className="mb-6 flex items-start justify-between border-b border-line pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight">{cfg.organization_name}</h1>
              <p className="mt-1 text-xs text-muted">Student Admissions & Eligibility Enquiry Form</p>
            </div>
            <Link
              href={`/widget/chat?key=${encodeURIComponent(key)}`}
              className="rounded-lg border border-line bg-slate-50 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-slate-100"
            >
              💬 Open live chat
            </Link>
          </div>

          {submitted ? (
            <div className="py-10 text-center">
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-emerald-100 text-xl text-emerald-700">
                ✓
              </div>
              <h2 className="text-lg font-semibold text-slate-800">Enquiry Received!</h2>
              <p className="mt-2 text-sm text-muted">
                Thank you, <b>{f.name}</b>. Our admissions counselling team at {cfg.organization_name} will review your course preferences and reach out to you at {f.phone}.
              </p>
              <Button
                variant="secondary"
                className="mt-6"
                onClick={() => {
                  setSubmitted(false);
                  setF({
                    name: "",
                    phone: "",
                    email: "",
                    preferred_course: "",
                    preferred_location: "",
                    academic_marks: "",
                    budget_max: "",
                    admission_timeline: "This year",
                    consent_automated_calls: false,
                    consent_marketing: false,
                  });
                }}
              >
                Submit another enquiry
              </Button>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4 text-sm">
              {err && (
                <div role="alert" className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700">
                  {err}
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Full name *" id="name">
                  <Input
                    id="name"
                    required
                    placeholder="Student full name"
                    value={f.name}
                    onChange={(e) => setF({ ...f, name: e.target.value })}
                  />
                </Field>

                <Field label="Mobile phone *" id="phone">
                  <Input
                    id="phone"
                    required
                    placeholder="98765 43210"
                    value={f.phone}
                    onChange={(e) => setF({ ...f, phone: e.target.value })}
                  />
                </Field>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Email address" id="email">
                  <Input
                    id="email"
                    type="email"
                    placeholder="student@example.com"
                    value={f.email}
                    onChange={(e) => setF({ ...f, email: e.target.value })}
                  />
                </Field>

                <Field label="Program / Course preference" id="course">
                  <Select
                    id="course"
                    value={f.preferred_course}
                    onChange={(e) => setF({ ...f, preferred_course: e.target.value })}
                  >
                    <option value="">Select a course...</option>
                    {cfg.courses_offered.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Academic score (%)" id="marks">
                  <Input
                    id="marks"
                    type="number"
                    step="any"
                    placeholder="e.g. 78"
                    value={f.academic_marks}
                    onChange={(e) => setF({ ...f, academic_marks: e.target.value })}
                  />
                </Field>

                <Field label="Preferred city" id="loc">
                  <Input
                    id="loc"
                    placeholder="Pune, Bengaluru..."
                    value={f.preferred_location}
                    onChange={(e) => setF({ ...f, preferred_location: e.target.value })}
                  />
                </Field>

                <Field label="Max budget (₹)" id="budget">
                  <Input
                    id="budget"
                    type="number"
                    placeholder="e.g. 500000"
                    value={f.budget_max}
                    onChange={(e) => setF({ ...f, budget_max: e.target.value })}
                  />
                </Field>
              </div>

              {/* Consent Section (Audit trail compliant) */}
              <div className="rounded-xl border border-line bg-slate-50 p-4 space-y-3">
                <p className="text-xs font-semibold text-slate-700">Consent & Privacy Declarations</p>
                <p className="text-[11px] text-muted leading-relaxed">{cfg.consent_disclaimer}</p>

                <label className="flex items-start gap-2.5 text-xs text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-0.5 rounded border-line"
                    checked={f.consent_automated_calls}
                    onChange={(e) => setF({ ...f, consent_automated_calls: e.target.checked })}
                  />
                  <span>
                    <b>I consent to receiving follow-up calls</b>, including AI-assisted admissions guidance calls, regarding college admission eligibility and fee counselling.
                  </span>
                </label>

                <label className="flex items-start gap-2.5 text-xs text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-0.5 rounded border-line"
                    checked={f.consent_marketing}
                    onChange={(e) => setF({ ...f, consent_marketing: e.target.checked })}
                  />
                  <span>
                    I agree to receive admissions updates, cutoffs, and scholarship notifications via email or SMS.
                  </span>
                </label>
              </div>

              <Button type="submit" loading={busy} className="w-full py-2.5">
                Submit admissions enquiry
              </Button>
            </form>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function LeadFormPage() {
  return (
    <Suspense fallback={<Loading />}>
      <FormInner />
    </Suspense>
  );
}
