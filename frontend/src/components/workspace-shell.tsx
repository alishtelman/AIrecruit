"use client";

import { ReactNode, useState } from "react";
import { AppBrand } from "@/components/app-brand";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Link, usePathname } from "@/i18n/navigation";

type WorkspaceNavItem = {
  href: string;
  label: string;
  activePrefixes?: string[];
};

type WorkspaceShellProps = {
  children: ReactNode;
  loading?: boolean;
  loadingLabel: string;
  homeHref: string;
  workspaceLabel: string;
  navSectionLabel: string;
  navItems: WorkspaceNavItem[];
  userDisplayName: string;
  userRoleLabel: string;
  userInitials: string;
  signOutLabel: string;
  onLogout: () => void | Promise<void>;
  cta?: {
    href: string;
    label: string;
  };
};

function isActivePath(pathname: string, item: WorkspaceNavItem) {
  return (
    pathname === item.href ||
    (item.href !== "/" && pathname.startsWith(`${item.href}/`)) ||
    Boolean(item.activePrefixes?.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)))
  );
}

function SidebarContent({
  homeHref,
  workspaceLabel,
  navSectionLabel,
  navItems,
  userDisplayName,
  userRoleLabel,
  userInitials,
  signOutLabel,
  onLogout,
  cta,
  onNavigate,
}: Omit<WorkspaceShellProps, "children" | "loading" | "loadingLabel"> & {
  onNavigate?: () => void;
}) {
  const pathname = usePathname();

  return (
    <>
      <Link href={homeHref} onClick={onNavigate} className="px-2 py-1">
        <AppBrand workspaceLabel={workspaceLabel} />
      </Link>

      <div className="mt-8 px-2 text-[10.5px] font-bold uppercase tracking-wider text-[#5b6070]">
        {navSectionLabel}
      </div>
      <nav className="mt-2 flex flex-col gap-1">
        {navItems.map((item) => {
          const active = isActivePath(pathname, item);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={`rounded-lg px-3 py-2.5 text-[14px] font-semibold transition-colors ${
                active
                  ? "bg-[#2F5BEA]/15 text-[#7E9BFF]"
                  : "text-[#8a8f9c] hover:bg-white/5 hover:text-white"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      {cta && (
        <Link
          href={cta.href}
          onClick={onNavigate}
          className="candidate-btn-primary mt-6 rounded-xl py-2.5 text-center text-xs font-bold shadow-[0_4px_12px_rgba(47,91,234,0.3)] transition-all hover:shadow-[0_6px_16px_rgba(47,91,234,0.4)]"
        >
          {cta.label}
        </Link>
      )}

      <div className="flex-1" />

      <div className="flex flex-col gap-4 border-t border-white/10 pt-4">
        <div className="flex items-center justify-between px-1">
          <span className="text-xs font-semibold text-[#7f8595]">Язык / Language</span>
          <LocaleSwitcher />
        </div>
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold text-[#c7cbd3]">
            {userInitials}
          </div>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[12.5px] font-semibold text-[#e7e9ee]">
              {userDisplayName}
            </div>
            <div className="text-[11px] text-[#7f8595]">{userRoleLabel}</div>
          </div>
          <button
            type="button"
            onClick={onLogout}
            aria-label={signOutLabel}
            className="shrink-0 text-xs font-semibold text-[#7f8595] transition-colors hover:text-white"
          >
            {signOutLabel}
          </button>
        </div>
      </div>
    </>
  );
}

export function WorkspaceShell(props: WorkspaceShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  if (props.loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F4F5F7]">
        <div className="font-semibold text-slate-500">{props.loadingLabel}</div>
      </div>
    );
  }

  return (
    <div className="candidate-shell-light flex min-h-screen items-stretch">
      <aside className="candidate-sidebar sticky top-0 z-10 hidden h-screen w-[248px] flex-none flex-col border-r border-white/5 px-4 py-6 lg:flex">
        <SidebarContent {...props} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-[#E9EAEE] bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
          <Link href={props.homeHref}>
            <AppBrand workspaceLabel={props.workspaceLabel} />
          </Link>
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Открыть меню"
            className="rounded-xl border border-[#E0E1E6] bg-white px-4 py-2 text-sm font-bold text-[#1A1C22]"
          >
            Меню
          </button>
        </header>

        <main className="min-w-0 flex-1 overflow-y-auto bg-[#F4F5F7] p-4 sm:p-6 lg:p-8">
          {props.children}
        </main>
      </div>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Закрыть меню"
            className="absolute inset-0 bg-slate-950/50"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="candidate-sidebar relative flex h-full w-[286px] max-w-[86vw] flex-col px-4 py-6 shadow-2xl">
            <SidebarContent {...props} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
    </div>
  );
}
