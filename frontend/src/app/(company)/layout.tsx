"use client";

import { CompanyShell } from "@/components/company-shell";
import { usePathname } from "@/i18n/navigation";

export default function CompanyLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAuthPage = pathname === "/company/login" || pathname === "/company/register";

  if (isAuthPage) {
    return <>{children}</>;
  }

  return <CompanyShell>{children}</CompanyShell>;
}
