"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { removeToken } from "@/lib/auth";
import { authApi } from "@/lib/api";
import type { User } from "@/lib/types";

export function useAuth(redirectTo = "/candidate/login") {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((nextUser) => {
        if (!cancelled) setUser(nextUser);
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
  }, [router, redirectTo]);

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
