"use client";

import { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/hooks/useAuth";
import { WorkspaceShell } from "@/components/workspace-shell";

interface AdminShellProps {
  children: ReactNode;
}

export function AdminShell({ children }: AdminShellProps) {
  const { user, loading, logout } = useAuth({
    redirectTo: "/admin/login",
    allowedRoles: ["platform_admin"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const common = useTranslations("common");

  return (
    <WorkspaceShell
      loading={loading}
      loadingLabel={common("status.loading") || "Загрузка..."}
      homeHref="/admin/dashboard"
      workspaceLabel="Admin Console"
      navSectionLabel="Администрирование"
      navItems={[
        { href: "/admin/dashboard", label: "Обзор" },
        { href: "/admin/platform", label: "Платформа" },
        { href: "/admin/ai-settings", label: "AI настройки" },
        { href: "/admin/interviews", label: "Интервью" },
        { href: "/admin/users", label: "Пользователи" },
        { href: "/admin/companies", label: "Компании" },
        { href: "/admin/reports", label: "Отчёты" },
        { href: "/admin/audit-log", label: "Аудит" },
      ]}
      userDisplayName={user?.email || ""}
      userRoleLabel="Platform Admin"
      userInitials={user?.email ? user.email.slice(0, 2).toUpperCase() : "AI"}
      signOutLabel={common("actions.signOut") || "Выйти"}
      onLogout={logout}
    >
      {children}
    </WorkspaceShell>
  );
}
