"use client";

import { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/hooks/useAuth";
import { WorkspaceShell } from "@/components/workspace-shell";

interface CandidateShellProps {
  children: ReactNode;
}

function getInitials(fullName?: string | null, email?: string | null) {
  if (fullName) {
    const parts = fullName.trim().split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return fullName.slice(0, 2).toUpperCase();
  }
  return email ? email.slice(0, 2).toUpperCase() : "AI";
}

export function CandidateShell({ children }: CandidateShellProps) {
  const { user, loading, logout } = useAuth({ allowedRoles: ["candidate"] });
  const t = useTranslations("candidateDashboard");
  const common = useTranslations("common");

  return (
    <WorkspaceShell
      loading={loading}
      loadingLabel={common("status.loading") || "Загрузка..."}
      homeHref="/candidate/dashboard"
      workspaceLabel={t("workspaceLabel") || "Candidate Workspace"}
      navSectionLabel="Навигация"
      navItems={[
        { href: "/candidate/dashboard", label: t("workspaceKicker") || "Кабинет" },
        { href: "/candidate/reports", label: "Мои интервью" },
        { href: "/candidate/resume", label: "Резюме" },
        { href: "/candidate/profile", label: t("nav.profile") || "Профиль" },
      ]}
      cta={{ href: "/candidate/interview/start", label: "Новое интервью" }}
      userDisplayName={user?.full_name || user?.email || ""}
      userRoleLabel="Candidate"
      userInitials={getInitials(user?.full_name, user?.email)}
      signOutLabel={common("actions.signOut") || "Выйти"}
      onLogout={logout}
    >
      {children}
    </WorkspaceShell>
  );
}
