export default function CompanyDashboardPage() {
  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-white">Candidate Database</h1>
          <span className="bg-blue-500/10 text-blue-400 text-sm px-3 py-1 rounded-full border border-blue-500/20">
            0 candidates
          </span>
        </div>

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center">
          <div className="text-4xl mb-4">🔍</div>
          <h2 className="text-white font-semibold text-lg mb-2">No candidates yet</h2>
          <p className="text-slate-400 text-sm max-w-sm mx-auto">
            Verified candidates will appear here once they complete their AI interviews.
          </p>
        </div>
      </div>
    </div>
  );
}
