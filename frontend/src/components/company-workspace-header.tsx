"use client";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";

type CompanyWorkspaceHeaderProps = {
  onLogout?: () => void | Promise<void>;
};

const NAV_ITEMS = [
  { href: "/company/dashboard", key: "dashboard" },
  { href: "/company/templates", key: "templates" },
  { href: "/company/employees", key: "employees" },
  { href: "/company/team", key: "team" },
  { href: "/company/settings", key: "settings" },
] as const;

export function CompanyWorkspaceHeader({ onLogout }: CompanyWorkspaceHeaderProps) {
  const t = useTranslations("companyDashboard.nav");
  const common = useTranslations("common");
  const pathname = usePathname();

  return (
    <header className="ai-panel mb-6 rounded-[1.8rem] px-5 py-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-slate-950/40 text-sm font-semibold tracking-[0.2em] text-slate-200">
            AR
          </div>
          <div>
            <p className="text-lg font-semibold text-white">AI Recruit</p>
            <p className="text-xs uppercase tracking-[0.28em] text-slate-500">{t("workspace")}</p>
          </div>
        </div>

        <div className="flex flex-col gap-3 lg:items-end">
          <nav className="flex flex-wrap items-center gap-2">
            {NAV_ITEMS.map((item) => {
              const active =
                item.href === "/company/dashboard"
                  ? pathname === item.href
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                    active
                      ? "border-blue-500/40 bg-blue-500/15 text-white shadow-[0_0_24px_rgba(59,130,246,0.18)]"
                      : "border-white/8 bg-slate-950/25 text-slate-300 hover:border-white/16 hover:text-white"
                  }`}
                >
                  {t(item.key)}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-2 self-start lg:self-auto">
            <LocaleSwitcher />
            {onLogout && (
              <button
                onClick={onLogout}
                className="rounded-full border border-white/8 bg-slate-950/25 px-4 py-2 text-sm font-medium text-slate-300 transition-colors hover:border-white/16 hover:text-white"
              >
                {common("actions.signOut")}
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
