"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken, removeToken } from "@/lib/auth";
import { authApi } from "@/lib/api";
import type { User } from "@/lib/types";

export function useAuth(redirectTo = "/candidate/login") {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace(redirectTo);
      return;
    }
    authApi
      .me()
      .then(setUser)
      .catch(() => {
        removeToken();
        router.replace(redirectTo);
      })
      .finally(() => setLoading(false));
  }, [router, redirectTo]);

  function logout() {
    removeToken();
    router.push("/");
  }

  return { user, loading, logout };
}
