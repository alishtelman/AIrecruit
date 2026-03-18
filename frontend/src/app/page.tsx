import Link from "next/link";

export default function HomePage() {
  return (
    <main className="min-h-screen bg-slate-900 text-white">
      <Nav />
      <Hero />
      <Stats />
      <HowItWorks />
      <Features />
      <ForCompanies />
      <CTA />
      <Footer />
    </main>
  );
}

// ── Nav ───────────────────────────────────────────────────────────────────────

function Nav() {
  return (
    <nav className="border-b border-slate-800 px-6 py-4">
      <div className="max-w-6xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-bold text-xl">AI</span>
          <span className="text-white font-bold text-xl">Recruit</span>
        </div>
        <div className="flex items-center gap-6">
          <a href="#how-it-works" className="text-slate-400 hover:text-white text-sm transition-colors hidden sm:block">
            How it works
          </a>
          <a href="#features" className="text-slate-400 hover:text-white text-sm transition-colors hidden sm:block">
            Features
          </a>
          <Link
            href="/candidate/login"
            className="text-slate-400 hover:text-white text-sm transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/company/register"
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            For Companies
          </Link>
        </div>
      </div>
    </nav>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section className="px-6 py-24 text-center">
      <div className="max-w-4xl mx-auto">
        <span className="inline-block bg-blue-500/10 text-blue-400 text-sm font-medium px-4 py-1.5 rounded-full border border-blue-500/20 mb-6">
          AI-Powered Recruiting Platform
        </span>
        <h1 className="text-5xl sm:text-6xl font-bold leading-tight mb-6">
          Hire verified talent.
          <br />
          <span className="text-blue-400">Skip the noise.</span>
        </h1>
        <p className="text-slate-400 text-xl max-w-2xl mx-auto mb-10 leading-relaxed">
          Candidates complete structured AI interviews and receive scientific skill reports.
          Companies access a database of pre-assessed, AI-verified professionals — ready to hire.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link
            href="/candidate/register"
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-8 py-3.5 rounded-xl transition-colors text-lg"
          >
            Start as a Candidate →
          </Link>
          <Link
            href="/company/register"
            className="bg-slate-800 hover:bg-slate-700 text-white font-semibold px-8 py-3.5 rounded-xl border border-slate-700 transition-colors text-lg"
          >
            Hire as a Company
          </Link>
        </div>
        <p className="text-slate-500 text-sm mt-4">Free to start · No credit card required</p>
      </div>
    </section>
  );
}

// ── Stats ─────────────────────────────────────────────────────────────────────

function Stats() {
  const stats = [
    { value: "8", label: "Questions per interview" },
    { value: "15–20 min", label: "Average interview time" },
    { value: "5", label: "Score dimensions assessed" },
    { value: "8 roles", label: "Supported job roles" },
  ];
  return (
    <section className="border-y border-slate-800 bg-slate-800/30 px-6 py-12">
      <div className="max-w-5xl mx-auto grid grid-cols-2 sm:grid-cols-4 gap-8 text-center">
        {stats.map((s, i) => (
          <div key={i}>
            <div className="text-3xl font-bold text-white mb-1">{s.value}</div>
            <div className="text-slate-400 text-sm">{s.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── How it works ──────────────────────────────────────────────────────────────

function HowItWorks() {
  const candidateSteps = [
    { icon: "📄", title: "Upload your resume", desc: "PDF or DOCX — we extract skills and experience automatically." },
    { icon: "🎙", title: "Complete AI interview", desc: "8 adaptive questions tailored to your role. Answer by text or voice." },
    { icon: "📊", title: "Get your skill report", desc: "Scientific assessment across 5 dimensions: hard skills, problem solving, communication, soft skills, and consistency." },
    { icon: "✅", title: "Join the database", desc: "Verified professionals are visible to hiring companies." },
  ];

  const companySteps = [
    { icon: "🔍", title: "Browse verified candidates", desc: "Filter by role, score, and hiring recommendation." },
    { icon: "📋", title: "View detailed reports", desc: "Competency heatmaps, skill matrices, red flags — per-question analysis." },
    { icon: "👥", title: "Assess your employees", desc: "Send invite links for internal performance reviews and skill audits." },
    { icon: "🤝", title: "Make data-driven decisions", desc: "Hire based on verified evidence, not just CVs and gut feeling." },
  ];

  return (
    <section id="how-it-works" className="px-6 py-24">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">How it works</h2>
          <p className="text-slate-400 text-lg">Two sides of the same platform.</p>
        </div>

        <div className="grid sm:grid-cols-2 gap-16">
          {/* Candidates */}
          <div>
            <div className="flex items-center gap-3 mb-8">
              <span className="bg-blue-500/15 text-blue-400 text-sm font-semibold px-3 py-1.5 rounded-full border border-blue-500/30">
                For Candidates
              </span>
            </div>
            <div className="space-y-6">
              {candidateSteps.map((step, i) => (
                <div key={i} className="flex gap-4">
                  <div className="w-10 h-10 bg-slate-800 border border-slate-700 rounded-xl flex items-center justify-center text-xl shrink-0">
                    {step.icon}
                  </div>
                  <div>
                    <div className="text-white font-semibold mb-1">{step.title}</div>
                    <div className="text-slate-400 text-sm leading-relaxed">{step.desc}</div>
                  </div>
                </div>
              ))}
            </div>
            <Link
              href="/candidate/register"
              className="inline-block mt-8 bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-2.5 rounded-lg transition-colors"
            >
              Get verified →
            </Link>
          </div>

          {/* Companies */}
          <div>
            <div className="flex items-center gap-3 mb-8">
              <span className="bg-purple-500/15 text-purple-400 text-sm font-semibold px-3 py-1.5 rounded-full border border-purple-500/30">
                For Companies
              </span>
            </div>
            <div className="space-y-6">
              {companySteps.map((step, i) => (
                <div key={i} className="flex gap-4">
                  <div className="w-10 h-10 bg-slate-800 border border-slate-700 rounded-xl flex items-center justify-center text-xl shrink-0">
                    {step.icon}
                  </div>
                  <div>
                    <div className="text-white font-semibold mb-1">{step.title}</div>
                    <div className="text-slate-400 text-sm leading-relaxed">{step.desc}</div>
                  </div>
                </div>
              ))}
            </div>
            <Link
              href="/company/register"
              className="inline-block mt-8 bg-purple-600 hover:bg-purple-500 text-white font-semibold px-6 py-2.5 rounded-lg transition-colors"
            >
              Start hiring →
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Features ──────────────────────────────────────────────────────────────────

function Features() {
  const features = [
    {
      icon: "🧠",
      title: "Adaptive AI Interviewer",
      desc: "Questions adapt based on your resume and previous answers. The AI follows up on weak spots and digs deeper into strengths.",
    },
    {
      icon: "📐",
      title: "Scientific Assessment",
      desc: "Two-pass LLM pipeline: per-question evidence extraction followed by competency scoring with BARS calibration to eliminate rating bias.",
    },
    {
      icon: "🎯",
      title: "Competency Heatmaps",
      desc: "10 competencies per role scored individually. See exactly where a candidate excels and where they need growth.",
    },
    {
      icon: "🎙",
      title: "Voice Interviews",
      desc: "Candidates can answer by voice using Groq Whisper STT. Questions are read aloud via AI text-to-speech.",
    },
    {
      icon: "👥",
      title: "Multi-user Teams",
      desc: "Invite recruiters to your company account. Admins manage access; members can browse candidates and view reports.",
    },
    {
      icon: "🏢",
      title: "Employee Assessments",
      desc: "Send invite links to existing employees for performance review, promotion decisions, or skill audits.",
    },
    {
      icon: "🔴",
      title: "Red Flag Detection",
      desc: "Automatic detection of contradictions, fabricated experience, evasive answers, and inconsistencies across responses.",
    },
    {
      icon: "📊",
      title: "5 Score Dimensions",
      desc: "Overall score, hard skills, soft skills, communication, and problem solving — each backed by weighted competency aggregation.",
    },
  ];

  return (
    <section id="features" className="px-6 py-24 bg-slate-800/20">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">Everything you need</h2>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto">
            Built on industrial/organizational psychology research. Powered by state-of-the-art LLMs.
          </p>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {features.map((f, i) => (
            <div key={i} className="bg-slate-800 border border-slate-700 rounded-xl p-5 hover:border-slate-600 transition-colors">
              <div className="text-3xl mb-3">{f.icon}</div>
              <div className="text-white font-semibold mb-2">{f.title}</div>
              <div className="text-slate-400 text-sm leading-relaxed">{f.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── For Companies ─────────────────────────────────────────────────────────────

function ForCompanies() {
  const roles = [
    "Backend Engineer", "Frontend Engineer", "QA Engineer", "DevOps Engineer",
    "Data Scientist", "Product Manager", "Mobile Engineer", "UX/UI Designer",
  ];

  return (
    <section className="px-6 py-24">
      <div className="max-w-5xl mx-auto">
        <div className="grid sm:grid-cols-2 gap-16 items-center">
          <div>
            <span className="text-blue-400 text-sm font-semibold uppercase tracking-wide">Supported Roles</span>
            <h2 className="text-3xl font-bold text-white mt-2 mb-4">8 role-specific competency matrices</h2>
            <p className="text-slate-400 leading-relaxed mb-6">
              Each role has a unique competency matrix with 10 skills, category weights, and behaviorally anchored rating scales.
              No generic scoring — every assessment is tailored to the position.
            </p>
            <p className="text-slate-400 leading-relaxed">
              Create custom interview templates with your own question sets.
              Mark them public so candidates can self-select into your pipeline.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {roles.map((role, i) => (
              <div key={i} className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-slate-300 text-sm">
                {role}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── CTA ───────────────────────────────────────────────────────────────────────

function CTA() {
  return (
    <section className="px-6 py-24 bg-blue-600/10 border-y border-blue-500/20">
      <div className="max-w-3xl mx-auto text-center">
        <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4">
          Ready to hire smarter?
        </h2>
        <p className="text-slate-400 text-lg mb-10">
          Join candidates who&apos;ve completed AI interviews and companies who make data-driven hiring decisions.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link
            href="/candidate/register"
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-8 py-3.5 rounded-xl transition-colors text-lg"
          >
            I&apos;m a Candidate
          </Link>
          <Link
            href="/company/register"
            className="bg-slate-800 hover:bg-slate-700 text-white font-semibold px-8 py-3.5 rounded-xl border border-slate-700 transition-colors text-lg"
          >
            I&apos;m a Company
          </Link>
        </div>
      </div>
    </section>
  );
}

// ── Footer ────────────────────────────────────────────────────────────────────

function Footer() {
  return (
    <footer className="px-6 py-10 border-t border-slate-800">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-bold">AI</span>
          <span className="text-white font-bold">Recruit</span>
          <span className="text-slate-600 text-sm ml-2">© 2026</span>
        </div>
        <div className="flex items-center gap-6 text-sm text-slate-500">
          <Link href="/candidate/register" className="hover:text-slate-300 transition-colors">For Candidates</Link>
          <Link href="/company/register" className="hover:text-slate-300 transition-colors">For Companies</Link>
          <Link href="/candidate/login" className="hover:text-slate-300 transition-colors">Sign in</Link>
        </div>
      </div>
    </footer>
  );
}
