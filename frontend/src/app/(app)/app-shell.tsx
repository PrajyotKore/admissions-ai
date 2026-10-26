"use client";
import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearSession, getOrgId, getToken, saveSession, setOrgId, type OrgMembership, type Session } from "@/lib/api";
import { Button, Loading, ToastProvider, Field, Input, ErrorState } from "@/components/ui";

type Ctx = { session: Session; org: OrgMembership; isManager: boolean; reload: () => void };
const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "▦" },
  { href: "/leads", label: "Leads", icon: "☰" },
  { href: "/calls", label: "AI Calls", icon: "📞" },
  { href: "/tasks", label: "Follow-ups", icon: "✓" },
  { href: "/knowledge", label: "Knowledge base", icon: "📖" },
  { href: "/team", label: "Team", icon: "☺" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  const [orgId, setOrg] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!getToken()) { router.replace("/login"); return; }
    api<Session>("/auth/me").then((s) => { saveSession(s); setSession(s); setOrg(getOrgId()); setError(""); })
      .catch((e) => setError(e.message));
  }, [router, tick]);

  if (error) return <div className="p-8"><ErrorState message={error} onRetry={() => setTick(tick + 1)} /></div>;
  if (!session) return <Loading />;

  const org = session.organizations.find((o) => o.organization_id === orgId);
  if (!org) {
    return (
      <div className="bg-auth grid min-h-screen place-items-center p-4">
        <form className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6 shadow-2xl" onSubmit={async (e) => {
          e.preventDefault();
          try {
            const o = await api<{ organization_id: string }>("/organizations", { method: "POST", json: { name: orgName } });
            setOrgId(o.organization_id); setTick(tick + 1);
          } catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
        }}>
          <h1 className="text-lg font-semibold">Set up your consultancy</h1>
          <p className="text-sm text-muted">Your account isn&apos;t part of an organization yet. Create one to get started.</p>
          <Field label="Consultancy name" id="org"><Input id="org" required value={orgName} onChange={(e) => setOrgName(e.target.value)} /></Field>
          <Button type="submit" className="w-full">Create organization</Button>
        </form>
      </div>
    );
  }

  const isManager = org.role === "owner" || org.role === "manager";
  const logout = async () => { await api("/auth/logout", { method: "POST" }).catch(() => {}); clearSession(); router.replace("/login"); };

  const nav = (
    <nav aria-label="Main" className="space-y-1">
      {NAV.map((n) => {
        const active = path.startsWith(n.href);
        return (
          <Link key={n.href} href={n.href} onClick={() => setMenu(false)}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${active ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-white"}`}>
            <span aria-hidden className="w-4 text-center">{n.icon}</span>{n.label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <AppCtx.Provider value={{ session, org, isManager, reload: () => setTick(tick + 1) }}>
      <ToastProvider>
        <div className="min-h-screen lg:flex">
          <aside className={`${menu ? "block" : "hidden"} fixed inset-y-0 left-0 z-40 w-64 bg-[#0b1020] p-4 lg:static lg:block lg:shrink-0`}>
            <div className="mb-6 flex items-center gap-2 px-2 text-white">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-indigo-400 to-sky-400 font-bold">A</div>
              <span className="font-semibold tracking-tight">Admissions AI</span>
            </div>
            {nav}
          </aside>
          <div className="min-w-0 flex-1">
            <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-white/80 px-4 py-3 backdrop-blur">
              <button className="rounded p-1.5 hover:bg-slate-100 lg:hidden" aria-label="Toggle navigation" onClick={() => setMenu(!menu)}>☰</button>
              <label htmlFor="org-switch" className="sr-only">Organization</label>
              <select id="org-switch" value={org.organization_id} className="rounded-lg border border-line bg-white px-2 py-1.5 text-sm font-medium"
                onChange={(e) => { setOrgId(e.target.value); window.location.reload(); }}>
                {session.organizations.map((o) => <option key={o.organization_id} value={o.organization_id}>{o.name}{o.is_demo ? " (DEMO)" : ""}</option>)}
              </select>
              <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium capitalize text-brand-700">{org.role}</span>
              {org.is_demo && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">Demo data</span>}
              <div className="ml-auto flex items-center gap-3 text-sm">
                <span className="hidden text-muted sm:inline">{session.user.full_name}</span>
                <Button variant="secondary" onClick={logout}>Sign out</Button>
              </div>
            </header>
            <main className="mx-auto max-w-7xl p-4 sm:p-6">{children}</main>
          </div>
        </div>
      </ToastProvider>
    </AppCtx.Provider>
  );
}
