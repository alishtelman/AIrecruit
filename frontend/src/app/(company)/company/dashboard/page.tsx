"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { companyApi } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import type { CandidateListItem, HiringRecommendation } from "@/lib/types";

const ROLE_LABELS: Record<string, string> = {
  backend_engineer: "Backend Engineer",
  frontend_engineer: "Frontend Engineer",
  qa_engineer: "QA Engineer",
  devops_engineer: "DevOps Engineer",
  data_scientist: "Data Scientist",
  product_manager: "Product Manager",
  mobile_engineer: "Mobile Engineer",
  designer: "UX/UI Designer",
};

const REC_STYLES: Record<HiringRecommendation, { label: string; className: string }> = {
  strong_yes: { label: "Strong Yes", className: "bg-green-500/15 text-green-400 border-green-500/30" },
  yes:        { label: "Yes",         className: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
  maybe:      { label: "Maybe",       className: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" },
  no:         { label: "No",          className: "bg-red-500/15 text-red-400 border-red-500/30" },
};

const PAGE_SIZE = 10;

export default function CompanyDashboardPage() {
  const router = useRouter();
  const { loading: authLoading, logout } = useAuth("/company/login");
  const [candidates, setCandidates] = useState<CandidateListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [page, setPage] = useState(0);

  useEffect(() => {
    if (authLoading) return;
    companyApi.listCandidates()
      .then(setCandidates)
      .catch((err) => setError(err.message ?? "Failed to load candidates"))
      .finally(() => setLoading(false));
  }, [authLoading, router]);

  const filtered = candidates.filter((c) => {
    const matchSearch =
      !search ||
      c.full_name.toLowerCase().includes(search.toLowerCase()) ||
      c.email.toLowerCase().includes(search.toLowerCase());
    const matchRole = !roleFilter || c.target_role === roleFilter;
    return matchSearch && matchRole;
  });

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function handleFilterChange(fn: () => void) {
    fn();
    setPage(0);
  }

  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Candidate Database</h1>
            <p className="text-slate-400 text-sm mt-1">AI-verified professionals</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="bg-blue-500/10 text-blue-400 text-sm px-3 py-1 rounded-full border border-blue-500/20">
              {candidates.length} candidate{candidates.length !== 1 ? "s" : ""}
            </span>
            <Link
              href="/company/templates"
              className="text-slate-400 hover:text-white text-sm transition-colors"
            >
              Templates
            </Link>
            <button
              onClick={logout}
              className="text-slate-400 hover:text-white text-sm transition-colors"
            >
              Sign out
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-3 mb-6">
          <input
            type="text"
            placeholder="Search by name or email…"
            value={search}
            onChange={(e) => handleFilterChange(() => setSearch(e.target.value))}
            className="flex-1 bg-slate-800 border border-slate-700 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-500"
          />
          <select
            value={roleFilter}
            onChange={(e) => handleFilterChange(() => setRoleFilter(e.target.value))}
            className="bg-slate-800 border border-slate-700 text-white rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All roles</option>
            {Object.entries(ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        {/* Content */}
        {loading && (
          <div className="text-center py-16 text-slate-400">Loading candidates…</div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-4">
            {error}
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
            <div className="text-4xl mb-4">🔍</div>
            <h2 className="text-white font-semibold text-lg mb-2">
              {candidates.length === 0 ? "No candidates yet" : "No matches found"}
            </h2>
            <p className="text-slate-400 text-sm max-w-sm mx-auto">
              {candidates.length === 0
                ? "Verified candidates will appear here once they complete their AI interviews."
                : "Try adjusting your search or filter."}
            </p>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-3">
            {paginated.map((c) => {
              const rec = REC_STYLES[c.hiring_recommendation] ?? REC_STYLES.maybe;
              return (
                <Link
                  key={c.candidate_id}
                  href={`/company/candidates/${c.candidate_id}`}
                  className="block bg-slate-800 border border-slate-700 rounded-xl p-5 hover:border-slate-500 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <span className="text-white font-semibold truncate">{c.full_name}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full border ${rec.className}`}>
                          {rec.label}
                        </span>
                      </div>
                      <p className="text-slate-400 text-sm truncate">{c.email}</p>
                      <p className="text-slate-500 text-xs mt-1">
                        {ROLE_LABELS[c.target_role] ?? c.target_role}
                      </p>
                      {c.interview_summary && (
                        <p className="text-slate-400 text-sm mt-2 line-clamp-2">{c.interview_summary}</p>
                      )}
                    </div>
                    <div className="flex-shrink-0 text-right">
                      <div className="text-2xl font-bold text-white">
                        {c.overall_score != null ? c.overall_score.toFixed(1) : "—"}
                      </div>
                      <div className="text-slate-500 text-xs">/ 10</div>
                    </div>
                  </div>
                </Link>
              );
            })}

            {totalPages > 1 && (
              <div className="flex items-center justify-between pt-4">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="px-4 py-2 text-sm bg-slate-800 border border-slate-700 text-slate-300 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:border-slate-500 transition-colors"
                >
                  ← Previous
                </button>
                <span className="text-slate-400 text-sm">
                  Page {page + 1} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="px-4 py-2 text-sm bg-slate-800 border border-slate-700 text-slate-300 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:border-slate-500 transition-colors"
                >
                  Next →
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
