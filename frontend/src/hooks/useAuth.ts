"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { removeToken } from "@/lib/auth";
import { authApi } from "@/lib/api";
import type { User } from "@/lib/types";

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
          router.replace(unauthorizedRedirectTo);
          return;
        }
        setUser(nextUser);
      })
      .catch(() => {
        removeToken();
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
      removeToken();
      router.push("/");
    }
  }

  return { user, loading, logout };
}
