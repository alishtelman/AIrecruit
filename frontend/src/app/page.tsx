import Link from "next/link";

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-800 flex items-center justify-center px-4">
      <div className="max-w-2xl w-full text-center">
        <div className="mb-8">
          <span className="inline-block bg-blue-500/10 text-blue-400 text-sm font-medium px-3 py-1 rounded-full border border-blue-500/20 mb-6">
            AI-Powered Recruiting
          </span>
          <h1 className="text-5xl font-bold text-white mb-4 leading-tight">
            Find Pre-Verified
            <br />
            <span className="text-blue-400">AI-Interviewed</span> Talent
          </h1>
          <p className="text-slate-400 text-lg max-w-lg mx-auto">
            Candidates complete structured AI interviews and receive detailed skill reports.
            Companies access a database of verified, assessed professionals.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link
            href="/candidate/register"
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-8 py-3 rounded-lg transition-colors"
          >
            I&apos;m a Candidate
          </Link>
          <Link
            href="/company/login"
            className="bg-white/10 hover:bg-white/20 text-white font-semibold px-8 py-3 rounded-lg border border-white/20 transition-colors"
          >
            I&apos;m a Company
          </Link>
        </div>

        <div className="mt-16 grid grid-cols-3 gap-8 text-left">
          {[
            { title: "Register", desc: "Create your profile and upload your resume" },
            { title: "Interview", desc: "Complete a structured AI interview for your role" },
            { title: "Get Verified", desc: "Receive a detailed skill report and join the database" },
          ].map((step, i) => (
            <div key={i} className="bg-white/5 rounded-xl p-5 border border-white/10">
              <div className="text-blue-400 font-bold text-sm mb-2">0{i + 1}</div>
              <div className="text-white font-semibold mb-1">{step.title}</div>
              <div className="text-slate-400 text-sm">{step.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
