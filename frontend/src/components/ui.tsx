"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

/* ---------- Button ---------- */
export function Button({ variant = "primary", size = "md", loading, className = "", children, ...p }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost"; size?: "sm" | "md"; loading?: boolean }) {
  const styles = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm shadow-brand-600/30",
    secondary: "bg-white text-ink border border-line hover:bg-slate-50",
    danger: "bg-rose-600 text-white hover:bg-rose-700",
    ghost: "text-muted hover:bg-slate-100",
  }[variant];
  const sizeStyles = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm";
  return (
    <button {...p} disabled={p.disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition active:scale-[.98] disabled:opacity-50 disabled:cursor-not-allowed ${styles} ${sizeStyles} ${className}`}>
      {loading && <span className="spinner !h-4 !w-4 !border-white/40 !border-t-white" />}
      {children}
    </button>
  );
}

/* ---------- Form fields ---------- */
const inputCls = "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";
export function Field({ label, id, error, children }: { label: string; id: string; error?: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-medium text-slate-600">{label}</label>
      {children}
      {error && <p className="text-xs text-rose-600">{error}</p>}
    </div>
  );
}
export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={`${inputCls} ${p.className ?? ""}`} />;
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={`${inputCls} ${p.className ?? ""}`} />;
export const Textarea = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={`${inputCls} ${p.className ?? ""}`} />;

/* ---------- Card / Badge / states ---------- */
export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`rounded-xl border border-line bg-white shadow-sm ${className}`}>{children}</div>
);

const STATUS_COLORS: Record<string, string> = {
  New: "bg-sky-50 text-sky-700 ring-sky-600/20", "Contact Pending": "bg-amber-50 text-amber-700 ring-amber-600/20",
  Contacted: "bg-indigo-50 text-indigo-700 ring-indigo-600/20", Qualified: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  "Counselling Scheduled": "bg-violet-50 text-violet-700 ring-violet-600/20", Converted: "bg-green-100 text-green-800 ring-green-700/20",
  "Not Interested": "bg-slate-100 text-slate-600 ring-slate-500/20", Invalid: "bg-slate-100 text-slate-500 ring-slate-500/20",
  "Do Not Contact": "bg-rose-50 text-rose-700 ring-rose-600/20",
};
export const Badge = ({ children, tone }: { children: ReactNode; tone?: string }) => (
  <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tone ?? STATUS_COLORS[String(children)] ?? "bg-slate-100 text-slate-600 ring-slate-500/20"}`}>{children}</span>
);

export const Spinner = () => <div role="status" aria-label="Loading" className="spinner" />;
export const Loading = () => <div className="flex justify-center py-16"><Spinner /></div>;
export const ErrorState = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-center text-sm text-rose-700">
    <p>{message}</p>{onRetry && <Button variant="secondary" className="mt-3" onClick={onRetry}>Try again</Button>}
  </div>
);
export const EmptyState = ({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) => (
  <div className="flex flex-col items-center gap-2 py-14 text-center">
    <div className="grid h-12 w-12 place-items-center rounded-full bg-brand-50 text-xl">✦</div>
    <p className="font-medium">{title}</p>{hint && <p className="max-w-sm text-sm text-muted">{hint}</p>}{action}
  </div>
);

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-2xl font-semibold tracking-tight">{title}</h1>{subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}</div>
      <div className="flex gap-2">{actions}</div>
    </div>
  );
}

/* ---------- Modal ---------- */
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/50 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
        className="animate-fade-up max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button aria-label="Close dialog" onClick={onClose} className="rounded p-1 text-muted hover:bg-slate-100">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ---------- Toasts ---------- */
type Toast = { id: number; kind: "success" | "error"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((i) => [...i, { id, kind, text }]);
    setTimeout(() => setItems((i) => i.filter((t) => t.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed bottom-4 right-4 z-[60] space-y-2">
        {items.map((t) => (
          <div key={t.id} className={`animate-fade-up rounded-lg px-4 py-2.5 text-sm text-white shadow-lg ${t.kind === "success" ? "bg-emerald-600" : "bg-rose-600"}`}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "-");
export const inr = (n?: number | null) => (n == null ? "-" : `₹${n.toLocaleString("en-IN")}`);
