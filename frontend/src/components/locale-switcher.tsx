"use client";

import {useLocale, useTranslations} from "next-intl";
import {usePathname, useRouter} from "@/i18n/navigation";
import type {AppLocale} from "@/i18n/routing";

export function LocaleSwitcher() {
  const t = useTranslations("common.locale");
  const locale = useLocale() as AppLocale;
  const pathname = usePathname();
  const router = useRouter();

  function setLocale(nextLocale: AppLocale) {
    document.cookie = `NEXT_LOCALE=${nextLocale}; path=/; max-age=31536000; samesite=lax`;
    router.replace(pathname, {locale: nextLocale});
    router.refresh();
  }

  return (
    <div
      className="inline-flex items-center gap-1 rounded-full border border-[color:var(--color-border-strong)] bg-[color:var(--color-surface-elevated)]/80 p-1 shadow-[0_12px_32px_rgba(4,12,24,0.34)] backdrop-blur-xl"
      aria-label={t("label")}
    >
      {(["en", "ru"] as AppLocale[]).map((value) => {
        const active = locale === value;
        return (
          <button
            key={value}
            type="button"
            onClick={() => setLocale(value)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] transition-all ${
              active
                ? "bg-[color:var(--color-accent)] text-white shadow-[0_8px_18px_rgba(47,115,255,0.38)]"
                : "text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]"
            }`}
            aria-pressed={active}
          >
            {value}
          </button>
        );
      })}
    </div>
  );
}
