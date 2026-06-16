"use client";

import { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/hooks/useAuth";
import { WorkspaceShell } from "@/components/workspace-shell";

interface CompanyShellProps {
  children: ReactNode;
}

export function CompanyShell({ children }: CompanyShellProps) {
  const { user, loading, logout } = useAuth({
    redirectTo: "/company/login",
    allowedRoles: ["company_admin", "company_member"],
    unauthorizedRedirectTo: "/candidate/dashboard",
  });
  const common = useTranslations("common");

  return (
    <WorkspaceShell
      loading={loading}
      loadingLabel={common("status.loading") || "Загрузка..."}
      homeHref="/company/dashboard"
      workspaceLabel="Company Workspace"
      navSectionLabel="Компания"
      navItems={[
        { href: "/company/dashboard", label: "Обзор и кандидаты", activePrefixes: ["/company/candidates"] },
        { href: "/company/reports", label: "Отчёты", activePrefixes: ["/company/interviews"] },
        { href: "/company/templates", label: "Шаблоны" },
        { href: "/company/employees", label: "Сотрудники" },
        { href: "/company/team", label: "Команда" },
        { href: "/company/settings", label: "Настройки" },
      ]}
      userDisplayName={user?.email || ""}
      userRoleLabel={user?.role === "company_admin" ? "Company Admin" : "Recruiter"}
      userInitials={user?.email ? user.email.slice(0, 2).toUpperCase() : "AI"}
      signOutLabel={common("actions.signOut") || "Выйти"}
      onLogout={logout}
    >
      {children}
    </WorkspaceShell>
  );
}
