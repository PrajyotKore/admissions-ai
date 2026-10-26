"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, saveSession, type Session } from "@/lib/api";
import { Button, Field, Input } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup" | "forgot" | "reset">("login");
  const [f, setF] = useState({ email: "", password: "", full_name: "", organization_name: "", token: "" });
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setInfo(""); setBusy(true);
    try {
      if (mode === "login" || mode === "signup") {
        const s = await api<Session>(mode === "login" ? "/auth/login" : "/auth/signup", {
          method: "POST",
          json: mode === "login" ? { email: f.email, password: f.password }
            : { email: f.email, password: f.password, full_name: f.full_name, organization_name: f.organization_name || undefined },
        });
        saveSession(s);
        router.push("/dashboard");
      } else if (mode === "forgot") {
        const r = await api<{ detail: string; dev_reset_token?: string }>("/auth/forgot-password", { method: "POST", json: { email: f.email } });
        setInfo(r.detail);
        if (r.dev_reset_token) { setF({ ...f, token: r.dev_reset_token }); setMode("reset"); setInfo("Development mode: reset token filled in for you. Enter a new password."); }
      } else {
        await api("/auth/reset-password", { method: "POST", json: { token: f.token, new_password: f.password } });
        setMode("login"); setInfo("Password updated. Please sign in.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally { setBusy(false); }
  }

  const titles = { login: "Welcome back", signup: "Create your consultancy account", forgot: "Reset your password", reset: "Choose a new password" };
  return (
    <main className="bg-auth grid min-h-screen place-items-center p-4">
      <div className="animate-fade-up w-full max-w-md">
        <div className="mb-6 text-center text-white">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-indigo-400 to-sky-400 text-xl font-bold shadow-lg">A</div>
          <h1 className="text-2xl font-semibold tracking-tight">Admissions AI</h1>
          <p className="mt-1 text-sm text-slate-300">Lead capture, qualification and follow-up for admissions consultancies</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl bg-white/95 p-6 shadow-2xl backdrop-blur">
          <h2 className="text-lg font-semibold">{titles[mode]}</h2>
          {info && <p role="status" className="rounded-lg bg-emerald-50 p-2.5 text-sm text-emerald-700">{info}</p>}
          {error && <p role="alert" className="rounded-lg bg-rose-50 p-2.5 text-sm text-rose-700">{error}</p>}
          {mode === "signup" && <>
            <Field label="Your name" id="full_name"><Input id="full_name" required value={f.full_name} onChange={set("full_name")} /></Field>
            <Field label="Consultancy name" id="organization_name"><Input id="organization_name" required value={f.organization_name} onChange={set("organization_name")} /></Field>
          </>}
          {mode !== "reset" && <Field label="Email" id="email"><Input id="email" type="email" required autoComplete="email" value={f.email} onChange={set("email")} /></Field>}
          {mode !== "forgot" && <Field label={mode === "reset" ? "New password" : "Password"} id="password">
            <Input id="password" type="password" required minLength={mode === "login" ? 1 : 10} autoComplete={mode === "login" ? "current-password" : "new-password"} value={f.password} onChange={set("password")} />
            {mode !== "login" && <p className="text-xs text-muted">At least 10 characters.</p>}
          </Field>}
          <Button type="submit" loading={busy} className="w-full">
            {{ login: "Sign in", signup: "Create account", forgot: "Send reset link", reset: "Update password" }[mode]}
          </Button>
          <div className="flex justify-between text-sm text-brand-600">
            {mode === "login" ? <>
              <button type="button" onClick={() => setMode("signup")} className="hover:underline">Create an account</button>
              <button type="button" onClick={() => setMode("forgot")} className="hover:underline">Forgot password?</button>
            </> : <button type="button" onClick={() => setMode("login")} className="hover:underline">Back to sign in</button>}
          </div>
        </form>
      </div>
    </main>
  );
}
