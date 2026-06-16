import type { ReactNode } from "react";
import { Link } from "@/i18n/navigation";

export function AuthPanel({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <main className="min-h-screen bg-[#F4F5F7] px-4 py-10 text-[#1A1C22]">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-6xl items-center justify-center">
        <div className="grid w-full overflow-hidden rounded-[2rem] border border-[#E9EAEE] bg-white shadow-[0_24px_70px_rgba(20,22,30,0.08)] lg:grid-cols-[0.92fr_1.08fr]">
          <section className="relative hidden overflow-hidden bg-[linear-gradient(145deg,#14161B_0%,#1E2432_100%)] p-10 text-white lg:block">
            <div className="absolute right-[-20%] top-[-20%] h-72 w-72 rounded-full bg-[#2F5BEA]/25 blur-[90px]" />
            <div className="relative z-10 flex h-full flex-col justify-between">
              <Link href="/" className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/10 font-manrope text-sm font-bold tracking-[0.16em] text-[#9BB2FF]">
                  AR
                </div>
                <div>
                  <div className="font-manrope text-lg font-bold">AI Recruit</div>
                  <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8f96a7]">
                    Verification Cloud
                  </div>
                </div>
              </Link>
              <div>
                <div className="mb-5 inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.18em] text-[#9BB2FF]">
                  Role-aware access
                </div>
                <h2 className="font-manrope text-4xl font-bold leading-tight tracking-tight">
                  Проверка навыков без шума и лишней бюрократии.
                </h2>
                <p className="mt-4 max-w-sm text-sm leading-6 text-[#b8bfcd]">
                  Один аккаунт — один правильный кабинет. Кандидат, компания и админ не смешиваются между собой.
                </p>
              </div>
            </div>
          </section>

          <section className="p-6 sm:p-10">
            <Link href="/" className="mb-8 inline-flex items-center gap-2 text-sm font-bold text-[#56596a] transition hover:text-[#1A1C22] lg:hidden">
              ← AI Recruit
            </Link>
            <div className="mb-8 text-center sm:text-left">
              <h1 className="font-manrope text-3xl font-bold tracking-tight text-[#1A1C22]">{title}</h1>
              <p className="mt-2 text-sm leading-6 text-[#56596a]">{subtitle}</p>
            </div>
            {children}
            {footer && <div className="mt-6 text-center text-sm font-semibold text-[#56596a]">{footer}</div>}
          </section>
        </div>
      </div>
    </main>
  );
}

export function AuthError({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
      {children}
    </div>
  );
}

export const authInputClass =
  "w-full rounded-xl border border-[#E0E1E6] bg-[#FAFBFC] px-4 py-3 text-[#1A1C22] placeholder-slate-400 outline-none transition focus:border-[#2F5BEA] focus:ring-4 focus:ring-[#2F5BEA]/10";

export const authLabelClass = "mb-1.5 block text-sm font-bold text-[#56596a]";

export const authButtonClass =
  "candidate-btn-primary w-full rounded-xl py-3 text-sm font-bold shadow-[0_8px_20px_rgba(47,91,234,0.22)] disabled:cursor-not-allowed disabled:opacity-50";
