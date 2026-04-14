"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/api";
import type { User } from "@/lib/types";
import { getDefaultRouteForRole } from "@/lib/roleRedirect";

type UseAuthOptions = {
  redirectTo?: string;
  allowedRoles?: User["role"][];
  unauthorizedRedirectTo?: string;
};

export function useAuth(options: string | UseAuthOptions = "/candidate/login") {
  const config = typeof options === "string" ? { redirectTo: options } : options;
  const redirectTo = config.redirectTo ?? "/candidate/login";
  const allowedRoles = config.allowedRoles;
  const unauthorizedRedirectTo = config.unauthorizedRedirectTo ?? "/";
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((nextUser) => {
        if (cancelled) return;
        if (allowedRoles && !allowedRoles.includes(nextUser.role)) {
          router.replace(nextUser.role === "platform_admin" ? getDefaultRouteForRole(nextUser.role) : unauthorizedRedirectTo);
          return;
        }
        setUser(nextUser);
      })
      .catch(() => {
        if (!cancelled) router.replace(redirectTo);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [allowedRoles, redirectTo, router, unauthorizedRedirectTo]);

  async function logout() {
    try {
      await authApi.logout();
    } catch {
      // ignore
    } finally {
      router.push("/");
    }
  }

  return { user, loading, logout };
}
