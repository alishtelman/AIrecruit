"use client";

type AdminWorkspaceHeaderProps = {
  onLogout?: () => void | Promise<void>;
};

export function AdminWorkspaceHeader({ onLogout }: AdminWorkspaceHeaderProps) {
  void onLogout;
  return null;
}
