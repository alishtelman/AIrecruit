"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale } from "next-intl";
import { Link } from "@/i18n/navigation";
import { companyApi } from "@/lib/api";
import type { CandidateListItem } from "@/lib/types";

function formatDate(value: string | null, locale: string) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatScore(value: number | null) {
  return value == null ? "—" : value.toFixed(1);
}

export default function CompanyReportsPage() {
  const locale = useLocale();
  const [items, setItems] = useState<CandidateListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  async function loadReports() {
    setLoading(true);
    setError("");
    try {
      const payload = await companyApi.listCandidates({ page: 1, page_size: 100, sort: "latest" });
      setItems(payload.items.filter((item) => Boolean(item.report_id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить отчёты");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReports();
  }, []);

  const filteredItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return items;
    return items.filter((item) => {
      return [item.full_name, item.email, item.target_role, item.hiring_recommendation]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(normalizedQuery));
    });
  }, [items, query]);

  return (
    <div className="ai-shell min-h-screen">
      <div className="ai-section mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <section className="ai-panel-strong rounded-[2rem] p-7 sm:p-8">
          <span className="ai-kicker">Отчёты</span>
          <h1 className="mt-4 text-4xl font-semibold leading-tight text-white sm:text-5xl">
            Отчёты по кандидатам
          </h1>
          <p className="mt-4 max-w-3xl text-lg leading-8 text-slate-300">
            Быстрый список готовых оценок: откройте отчёт, сравните кандидатов или вернитесь к общей воронке.
          </p>
        </section>

        <section className="ai-panel mt-6 rounded-[1.75rem] p-6">
          <div className="grid gap-4 lg:grid-cols-[1fr_auto_auto]">
            <input
              className="ai-input min-h-12 rounded-2xl px-4"
              placeholder="Поиск по кандидату, email, роли или рекомендации"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button
              type="button"
              onClick={() => void loadReports()}
              className="ai-button-primary rounded-full px-5 py-3 text-sm font-semibold"
            >
              Обновить
            </button>
            <Link
              href="/company/dashboard"
              className="rounded-full border border-white/10 px-5 py-3 text-center text-sm font-semibold text-slate-200 transition hover:border-white/20 hover:text-white"
            >
              К кандидатам
            </Link>
          </div>
        </section>

        {error && (
          <div className="mt-6 rounded-2xl border border-red-500/25 bg-red-500/10 px-5 py-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-900/60 px-5 py-8 text-center text-slate-400">
            Загружаем отчёты...
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-900/60 px-5 py-10 text-center">
            <h2 className="text-xl font-semibold text-white">Пока нет готовых отчётов</h2>
            <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-slate-400">
              Когда кандидат завершит интервью и система сформирует оценку, отчёт появится здесь. Сейчас можно проверить список кандидатов или создать новое приглашение.
            </p>
            <div className="mt-6 flex justify-center">
              <Link href="/company/dashboard" className="ai-button-primary rounded-full px-5 py-3 text-sm font-semibold">
                Открыть кандидатов
              </Link>
            </div>
          </div>
        ) : (
          <section className="ai-panel mt-6 overflow-hidden rounded-[1.75rem]">
            <div className="grid grid-cols-[1.2fr_1fr_0.75fr_0.9fr_0.75fr] gap-4 border-b border-slate-800 px-6 py-4 text-xs uppercase tracking-[0.22em] text-slate-500">
              <div>Кандидат</div>
              <div>Роль</div>
              <div>Скор</div>
              <div>Рекомендация</div>
              <div />
            </div>
            <div className="divide-y divide-slate-800">
              {filteredItems.map((item) => (
                <div key={item.report_id} className="grid grid-cols-[1.2fr_1fr_0.75fr_0.9fr_0.75fr] gap-4 px-6 py-4 text-sm">
                  <div>
                    <p className="font-medium text-white">{item.full_name}</p>
                    <p className="mt-1 text-slate-500">{item.email}</p>
                    <p className="mt-1 text-xs text-slate-600">{formatDate(item.completed_at, locale)}</p>
                  </div>
                  <div className="text-slate-300">{item.target_role}</div>
                  <div className="text-white">{formatScore(item.overall_score)}</div>
                  <div className="text-slate-300">{item.hiring_recommendation}</div>
                  <div className="flex justify-end">
                    <Link
                      href={`/company/reports/${item.report_id}`}
                      className="rounded-full border border-white/10 px-4 py-2 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:text-white"
                    >
                      Открыть
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
