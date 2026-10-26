// Session lives in localStorage (simple for an MVP). Tradeoff: readable by any XSS. Moving to an httpOnly
// cookie issued by the backend is listed in README "Known limitations".
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

export type OrgMembership = { organization_id: string; name: string; slug: string; role: string; is_demo: boolean };
export type Session = {
  access_token?: string;
  user: { id: string; email: string; full_name: string; is_platform_admin: boolean };
  organizations: OrgMembership[];
};

const isBrowser = () => typeof window !== "undefined";
export const getToken = () => (isBrowser() ? localStorage.getItem("token") : null);
export const getOrgId = () => (isBrowser() ? localStorage.getItem("orgId") : null);
export const setOrgId = (id: string) => localStorage.setItem("orgId", id);
export const saveSession = (s: Session) => {
  if (s.access_token) localStorage.setItem("token", s.access_token);
  if (!getOrgId() || !s.organizations.some((o) => o.organization_id === getOrgId())) {
    if (s.organizations[0]) setOrgId(s.organizations[0].organization_id);
    else localStorage.removeItem("orgId");
  }
};
export const clearSession = () => {
  localStorage.removeItem("token");
  localStorage.removeItem("orgId");
};

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

function messageFrom(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: string }).message);
  return "Something went wrong";
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const org = getOrgId();
  if (org) headers["X-Organization-Id"] = org;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Is the backend running?");
  }
  if (res.status === 401 && isBrowser() && !path.startsWith("/auth/login")) {
    clearSession();
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(res.status, messageFrom(data.detail), data.detail);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export type Lead = {
  id: string; name: string; phone: string; email: string | null; preferred_course: string | null;
  preferred_college: string | null; education_level: string | null; academic_marks: number | null;
  preferred_location: string | null; budget_min: number | null; budget_max: number | null;
  admission_timeline: string | null; source_name: string | null; assigned_to: string | null;
  qualification_score: number | null; qualification_category: string | null; status: string;
  last_contact_at: string | null; next_follow_up_at: string | null; do_not_contact: boolean;
  field_provenance: Record<string, { source: string; at: string }>; created_at: string; updated_at: string;
  consent?: Record<string, string>;
};
export type Member = { user_id: string; email: string; full_name: string; role: string };
export type Task = { id: string; lead_id: string; title: string; due_at: string; status: string; assigned_to: string | null };
