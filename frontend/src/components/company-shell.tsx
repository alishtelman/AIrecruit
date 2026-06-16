"use client";

import { ReactNode } from "react";
import { useAuth } from "@/hooks/useAuth";
import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { LocaleSwitcher } from "@/components/locale-switcher";

interface CompanyShellProps {
  children: ReactNode;
}

export function CompanyShell({ children }: CompanyShellProps) {
  const { user, loading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const pathname = usePathname();
  const t = useTranslations("companyTeam"); // We can use companyTeam or common namespace
  const common = useTranslations("common");

  // Get initials for the avatar
  const getInitials = () => {
    if (user?.email) {
      return user.email.slice(0, 2).toUpperCase();
    }
    return "CO";
  };

  const getDisplayName = () => {
    return user?.email || "";
  };

  const menuItems = [
    { href: "/company/dashboard", label: "Кандидаты" },
    { href: "/company/employees", label: "Сотрудники" },
    { href: "/company/templates", label: "Шаблоны" },
    { href: "/company/team", label: "Команда" },
    { href: "/company/settings", label: "Настройки ИИ" },
  ];

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F4F5F7] flex items-center justify-center">
        <div className="text-slate-500 font-semibold">{common("status.loading") || "Загрузка..."}</div>
      </div>
    );
  }

  return (
    <div className="candidate-shell-light flex items-stretch min-h-screen">
      {/* Sidebar aside */}
      <aside className="candidate-sidebar w-[248px] flex-none flex flex-col py-6 px-4 sticky top-0 h-screen self-start z-10 border-r border-white/5">
        {/* Sidebar Header */}
        <Link href="/company/dashboard" className="flex items-center gap-3 px-2 py-1">
          <div className="w-9 h-9 rounded-xl bg-[#2F5BEA]/15 text-[#7E9BFF] flex items-center justify-center font-bold text-sm font-manrope">
            AR
          </div>
          <div className="leading-tight">
            <div className="font-manrope font-bold text-sm text-white">AI Recruit</div>
            <div className="text-[9.5px] font-semibold tracking-widest text-[#7f8595]">
              BUSINESS CONSOLE
            </div>
          </div>
        </Link>

        {/* Navigation Section */}
        <div className="text-[10.5px] font-bold tracking-wider text-[#5b6070] uppercase mt-8 mb-2 px-2">
          Компания
        </div>
        <nav className="flex flex-col gap-1">
          {menuItems.map((item) => {
            const isActive = pathname === item.href || (item.href !== "/company/dashboard" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`px-3 py-2.5 rounded-lg text-[14px] font-semibold transition-colors ${
                  isActive
                    ? "bg-[#2F5BEA]/15 text-[#7E9BFF]"
                    : "text-[#8a8f9c] hover:bg-white/5 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex-1" />

        {/* Locale Switcher and Profile Section */}
        <div className="flex flex-col gap-4 border-t border-white/10 pt-4">
          <div className="flex justify-between items-center px-1">
            <span className="text-xs text-[#7f8595] font-semibold">Язык / Language</span>
            <LocaleSwitcher />
          </div>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-white/10 text-[#c7cbd3] flex items-center justify-center font-bold text-xs shrink-0">
              {getInitials()}
            </div>
            <div className="leading-tight min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold text-[#e7e9ee] truncate">
                {getDisplayName()}
              </div>
              <div className="text-[11px] text-[#7f8595]">
                {user?.role === "company_admin" ? "Admin" : "Recruiter"}
              </div>
            </div>
            <button
              type="button"
              onClick={logout}
              aria-label={common("actions.signOut") || "Выйти"}
              className="text-[#7f8595] hover:text-white text-xs font-semibold shrink-0 transition-colors"
            >
              {common("actions.signOut") || "Выйти"}
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Pane */}
      <main className="flex-1 min-w-0 bg-[#F4F5F7] p-8 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
