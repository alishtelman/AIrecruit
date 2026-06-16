import type { ComponentPropsWithoutRef, ReactNode } from "react";

function joinClasses(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

type Tone = "default" | "success" | "info" | "warning" | "danger" | "neutral";

const badgeTone: Record<Tone, string> = {
  default: "border-slate-200 bg-white text-slate-700",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  info: "border-blue-200 bg-blue-50 text-blue-700",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  danger: "border-red-200 bg-red-50 text-red-700",
  neutral: "border-slate-200 bg-slate-50 text-slate-600",
};

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && (
          <div className="text-xs font-bold uppercase tracking-[0.22em] text-slate-400">{eyebrow}</div>
        )}
        <h1 className="mt-2 font-manrope text-3xl font-bold tracking-tight text-[#1A1C22] sm:text-4xl">{title}</h1>
        {description && <p className="mt-2 max-w-3xl text-sm leading-6 text-[#56596a] sm:text-base">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PanelCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={joinClasses("rounded-[1.35rem] border border-[#E9EAEE] bg-white shadow-[0_12px_32px_rgba(20,22,30,0.06)]", className)}>
      {children}
    </section>
  );
}

export function StatusBadge({ children, tone = "default" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={joinClasses("inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-bold", badgeTone[tone])}>
      {children}
    </span>
  );
}

export function PrimaryButton({ className, ...props }: ComponentPropsWithoutRef<"button">) {
  return (
    <button
      {...props}
      className={joinClasses(
        "rounded-xl bg-[#2F5BEA] px-5 py-3 text-sm font-bold text-white shadow-[0_8px_20px_rgba(47,91,234,0.25)] transition hover:bg-[#2348C8] disabled:cursor-not-allowed disabled:opacity-45",
        className,
      )}
    />
  );
}

export function SecondaryButton({ className, ...props }: ComponentPropsWithoutRef<"button">) {
  return (
    <button
      {...props}
      className={joinClasses(
        "rounded-xl border border-[#E0E1E6] bg-white px-5 py-3 text-sm font-bold text-[#1A1C22] transition hover:border-[#14161B] disabled:cursor-not-allowed disabled:opacity-45",
        className,
      )}
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <PanelCard className="p-10 text-center">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 text-xs font-bold tracking-[0.2em] text-[#2F5BEA]">
        AR
      </div>
      <h2 className="text-lg font-bold text-[#1A1C22]">{title}</h2>
      {description && <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[#56596a]">{description}</p>}
      {action && <div className="mt-6">{action}</div>}
    </PanelCard>
  );
}
