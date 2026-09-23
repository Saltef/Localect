import type { ReactNode } from "react";

export function Card({ title, children, className = "", action }: {
  title?: ReactNode; children: ReactNode; className?: string; action?: ReactNode;
}) {
  return (
    <section className={`rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">{title}</h3>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Button({ children, onClick, kind = "primary", disabled, type = "button", className = "" }: {
  children: ReactNode; onClick?: () => void; kind?: "primary" | "ghost" | "danger";
  disabled?: boolean; type?: "button" | "submit"; className?: string;
}) {
  const base = "inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50";
  const styles = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-500 shadow-sm",
    ghost: "border border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800",
    danger: "text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40",
  }[kind];
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${styles} ${className}`}>
      {children}
    </button>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";

export function Badge({ children, tone = "zinc" }: { children: ReactNode; tone?: "zinc" | "green" | "amber" | "red" | "indigo" }) {
  const t = {
    zinc: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
    red: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
    indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${t}`}>{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700">{children}</p>;
}
