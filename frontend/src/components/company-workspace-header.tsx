"use client";

type CompanyWorkspaceHeaderProps = {
  onLogout?: () => void | Promise<void>;
};

export function CompanyWorkspaceHeader({ onLogout }: CompanyWorkspaceHeaderProps) {
  void onLogout;
  return null;
}
