import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import { LocaleSwitcher } from "@/components/locale-switcher";

export default async function HomePage() {
  const t = await getTranslations("home");

  return (
    <main className="min-h-screen bg-[#F4F5F7] text-[#1A1C22] font-sans antialiased selection:bg-[#2F5BEA]/10 selection:text-[#2F5BEA]">
      <Nav
        howItWorks={t("nav.howItWorks")}
        features={t("nav.features")}
        signIn={t("nav.signIn")}
        forCompanies={t("nav.forCompanies")}
      />
      <Hero
        badge={t("hero.badge")}
        title={t("hero.title")}
        highlight={t("hero.highlight")}
        description={t("hero.description")}
        candidateCta={t("hero.candidateCta")}
        companyCta={t("hero.companyCta")}
        note={t("hero.note")}
        panelTitle={t("heroPanel.title")}
        panelSubtitle={t("heroPanel.subtitle")}
        panelStatus={t("heroPanel.status")}
        summaryTitle={t("heroPanel.summaryTitle")}
        summaryText={t("heroPanel.summaryText")}
        benefit1Title={t("heroPanel.benefit1Title")}
        benefit1Text={t("heroPanel.benefit1Text")}
        benefit2Title={t("heroPanel.benefit2Title")}
        benefit2Text={t("heroPanel.benefit2Text")}
        benefit3Title={t("heroPanel.benefit3Title")}
        benefit3Text={t("heroPanel.benefit3Text")}
      />
      <Stats t={t} />
      <HowItWorks t={t} />
      <Features t={t} />
      <ForCompanies t={t} />
      <CTA t={t} />
      <Footer t={t} />
    </main>
  );
}

function Nav({
  howItWorks,
  features,
  signIn,
  forCompanies,
}: {
  howItWorks: string;
  features: string;
  signIn: string;
  forCompanies: string;
}) {
  return (
    <nav className="sticky top-0 z-30 border-b border-[#E9EAEE] bg-white/80 px-6 py-4 backdrop-blur-md">
      <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#14161B] text-sm font-bold tracking-[0.16em] text-[#7E9BFF] font-manrope shadow-[0_10px_28px_rgba(20,22,30,0.12)]">
            AR
          </div>
          <div>
            <div className="text-[#1A1C22] font-bold text-lg leading-none font-manrope">AI Recruit</div>
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-400 font-semibold mt-0.5">Verification Cloud</div>
          </div>
        </div>
        <div className="flex items-center gap-3 sm:gap-6">
          <a href="#how-it-works" className="hidden text-sm text-[#56596a] font-semibold transition-colors hover:text-[#1A1C22] sm:block">
            {howItWorks}
          </a>
          <a href="#features" className="hidden text-sm text-[#56596a] font-semibold transition-colors hover:text-[#1A1C22] sm:block">
            {features}
          </a>
          <LocaleSwitcher />
          <Link href="/candidate/login" className="text-sm text-[#56596a] font-semibold transition-colors hover:text-[#1A1C22]">
            {signIn}
          </Link>
          <Link href="/company/register" className="candidate-btn-primary rounded-xl px-4 py-2 text-sm font-bold shadow-[0_4px_12px_rgba(47,91,234,0.2)]">
            {forCompanies}
          </Link>
        </div>
      </div>
    </nav>
  );
}

function Hero({
  badge,
  title,
  highlight,
  description,
  candidateCta,
  companyCta,
  note,
  panelTitle,
  panelSubtitle,
  panelStatus,
  summaryTitle,
  summaryText,
  benefit1Title,
  benefit1Text,
  benefit2Title,
  benefit2Text,
  benefit3Title,
  benefit3Text,
}: {
  badge: string;
  title: string;
  highlight: string;
  description: string;
  candidateCta: string;
  companyCta: string;
  note: string;
  panelTitle: string;
  panelSubtitle: string;
  panelStatus: string;
  summaryTitle: string;
  summaryText: string;
  benefit1Title: string;
  benefit1Text: string;
  benefit2Title: string;
  benefit2Text: string;
  benefit3Title: string;
  benefit3Text: string;
}) {
  return (
    <section className="px-6 pb-16 pt-20 sm:pt-24 relative overflow-hidden">
      {/* Background radial accents */}
      <div className="absolute top-[10%] left-[-10%] w-[400px] h-[400px] rounded-full bg-[#2F5BEA]/5 blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[10%] right-[-10%] w-[400px] h-[400px] rounded-full bg-[#2F5BEA]/[0.04] blur-[120px] pointer-events-none"></div>

      <div className="max-w-6xl mx-auto grid gap-12 lg:grid-cols-[1.08fr_0.92fr] lg:items-center relative z-1">
        <div>
          <span className="inline-flex items-center gap-2 bg-[#EEF2FF] border border-[#2F5BEA]/20 text-[#2F5BEA] px-3.5 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-wider mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-[#2F5BEA]"></span>
            {badge}
          </span>
          <h1 className="max-w-4xl text-5xl font-bold font-manrope leading-[1.05] tracking-tight text-[#1A1C22] sm:text-[4.2rem] lg:text-[4.8rem]">
            {title}
            <br />
            <span className="bg-gradient-to-r from-[#2F5BEA] to-cyan-500 bg-clip-text text-transparent">
              {highlight}
            </span>
          </h1>
          <p className="mt-6 max-w-2xl text-base leading-relaxed text-[#56596a] sm:text-[17.5px]">
            {description}
          </p>
          <div className="mt-10 flex flex-col gap-4 sm:flex-row">
            <Link href="/candidate/register" className="candidate-btn-primary rounded-xl px-8 py-4 text-center text-[16px] font-bold shadow-[0_8px_20px_rgba(47,91,234,0.3)]">
              {candidateCta}
            </Link>
            <Link href="/company/register" className="candidate-btn-secondary rounded-xl px-8 py-4 text-center text-[16px] font-bold shadow-[0_1px_2px_rgba(20,22,30,0.04)]">
              {companyCta}
            </Link>
          </div>
          <p className="mt-4 text-[13px] text-slate-400 font-semibold">{note}</p>
        </div>

        {/* Right mockup panel */}
        <div className="bg-white border border-[#E9EAEE] rounded-3xl p-6 sm:p-8 shadow-[0_20px_50px_rgba(20,22,30,0.06)]">
          <div className="flex items-center justify-between gap-4 border-b border-slate-100 pb-5">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{panelTitle}</p>
              <h2 className="mt-1 text-lg font-bold font-manrope text-[#1A1C22] sm:text-xl">{panelSubtitle}</h2>
            </div>
            <div className="rounded-full border border-[#D6E0FD] bg-[#ECF0FE] px-3 py-1.5 text-xs font-bold text-[#2348C8]">
              {panelStatus}
            </div>
          </div>
          <div className="mt-5 rounded-2xl border border-[#2F5BEA]/10 bg-[#EEF2FF]/60 p-5">
            <p className="text-xs font-bold uppercase tracking-wider text-[#2F5BEA]">{summaryTitle}</p>
            <p className="mt-2 text-sm leading-relaxed text-[#374151]">{summaryText}</p>
          </div>
          <div className="mt-5 space-y-4">
            {[
              [benefit1Title, benefit1Text],
              [benefit2Title, benefit2Text],
              [benefit3Title, benefit3Text],
            ].map(([label, text]) => (
              <div key={label} className="rounded-2xl border border-[#E9EAEE] bg-[#FAFBFC] px-5 py-4">
                <div className="flex items-start gap-3.5">
                  <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#2F5BEA] shadow-[0_0_10px_rgba(47,91,234,0.6)]" />
                  <div>
                    <p className="text-sm font-bold text-[#1A1C22]">{label}</p>
                    <p className="mt-1 text-xs leading-relaxed text-[#56596a]">{text}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Stats({ t }: { t: (key: string, values?: Record<string, string | number>) => string }) {
  const stats = [
    { value: "8", label: t("stats.questions") },
    { value: t("stats.durationValue"), label: t("stats.duration") },
    { value: "5", label: t("stats.dimensions") },
    { value: "8", label: t("stats.roles") },
  ];

  return (
    <section className="px-6 pb-10">
      <div className="max-w-6xl mx-auto grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((s, i) => (
          <div key={i} className="bg-white border border-[#E9EAEE] rounded-2xl px-6 py-6 text-center shadow-[0_1px_2px_rgba(20,22,30,0.03)]">
            <div className="text-4xl font-bold font-manrope tracking-tight text-[#2F5BEA]">{s.value}</div>
            <div className="mt-2 text-[13.5px] font-bold text-[#56596a]">{s.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function HowItWorks({ t }: { t: (key: string, values?: Record<string, string | number>) => string }) {
  const candidateSteps = [
    { icon: "01", title: t("how.candidate.step1.title"), desc: t("how.candidate.step1.desc") },
    { icon: "02", title: t("how.candidate.step2.title"), desc: t("how.candidate.step2.desc") },
    { icon: "03", title: t("how.candidate.step3.title"), desc: t("how.candidate.step3.desc") },
    { icon: "04", title: t("how.candidate.step4.title"), desc: t("how.candidate.step4.desc") },
  ];
  const companySteps = [
    { icon: "01", title: t("how.company.step1.title"), desc: t("how.company.step1.desc") },
    { icon: "02", title: t("how.company.step2.title"), desc: t("how.company.step2.desc") },
    { icon: "03", title: t("how.company.step3.title"), desc: t("how.company.step3.desc") },
    { icon: "04", title: t("how.company.step4.title"), desc: t("how.company.step4.desc") },
  ];

  return (
    <section id="how-it-works" className="px-6 py-24 relative">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <span className="inline-flex items-center gap-2 bg-[#EEF2FF] border border-[#2F5BEA]/20 text-[#2F5BEA] px-3.5 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-wider mb-4">
            {t("how.title")}
          </span>
          <h2 className="text-3xl sm:text-4xl font-bold font-manrope tracking-tight text-[#1A1C22] mb-3">{t("how.title")}</h2>
          <p className="text-[#56596a] text-base sm:text-lg max-w-2xl mx-auto">{t("how.subtitle")}</p>
        </div>

        <div className="grid gap-8 sm:grid-cols-2">
          <JourneyCard
            title={t("how.forCandidates")}
            accent="blue"
            steps={candidateSteps}
            ctaHref="/candidate/register"
            ctaLabel={t("how.candidate.cta")}
          />
          <JourneyCard
            title={t("how.forCompanies")}
            accent="cyan"
            steps={companySteps}
            ctaHref="/company/register"
            ctaLabel={t("how.company.cta")}
          />
        </div>
      </div>
    </section>
  );
}

function JourneyCard({
  title,
  accent,
  steps,
  ctaHref,
  ctaLabel,
}: {
  title: string;
  accent: "blue" | "cyan";
  steps: { icon: string; title: string; desc: string }[];
  ctaHref: string;
  ctaLabel: string;
}) {
  const badgeClass = accent === "blue"
    ? "border-[#2F5BEA]/20 bg-[#EEF2FF] text-[#2F5BEA]"
    : "border-sky-200 bg-sky-50 text-sky-800";
  const iconClass = accent === "blue"
    ? "border-[#2F5BEA]/10 bg-[#EEF2FF]/80 text-[#2F5BEA]"
    : "border-sky-100 bg-sky-50 text-sky-700";
  const buttonClass = accent === "blue" ? "candidate-btn-primary" : "candidate-btn-secondary";

  return (
    <div className="bg-white border border-[#E9EAEE] rounded-3xl p-6 sm:p-8 shadow-[0_1px_3px_rgba(20,22,30,0.02),0_16px_32px_-4px_rgba(20,22,30,0.03)]">
      <div className="flex items-center gap-3 mb-8">
        <span className={`rounded-full border px-3.5 py-1.5 text-xs font-bold ${badgeClass}`}>
          {title}
        </span>
      </div>
      <div className="space-y-6">
        {steps.map((step, i) => (
          <div key={i} className="flex gap-4">
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border text-xs font-bold font-manrope ${iconClass}`}>
              {step.icon}
            </div>
            <div>
              <div className="text-[#1A1C22] font-bold mb-1">{step.title}</div>
              <div className="text-[#56596a] text-sm leading-relaxed">{step.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <Link href={ctaHref} className={`${buttonClass} inline-block mt-8 rounded-xl px-6 py-3.5 text-sm font-bold text-center`}>
        {ctaLabel}
      </Link>
    </div>
  );
}

function Features({ t }: { t: (key: string, values?: Record<string, string | number>) => string }) {
  const features = [
    { icon: "AD", title: t("features.items.ai.title"), desc: t("features.items.ai.desc") },
    { icon: "SC", title: t("features.items.science.title"), desc: t("features.items.science.desc") },
    { icon: "HM", title: t("features.items.heatmap.title"), desc: t("features.items.heatmap.desc") },
    { icon: "VX", title: t("features.items.voice.title"), desc: t("features.items.voice.desc") },
    { icon: "TM", title: t("features.items.team.title"), desc: t("features.items.team.desc") },
    { icon: "HR", title: t("features.items.employee.title"), desc: t("features.items.employee.desc") },
    { icon: "RF", title: t("features.items.flags.title"), desc: t("features.items.flags.desc") },
    { icon: "5D", title: t("features.items.dimensions.title"), desc: t("features.items.dimensions.desc") },
  ];

  return (
    <section id="features" className="px-6 py-24 relative bg-white border-y border-[#E9EAEE]">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <span className="inline-flex items-center gap-2 bg-[#EEF2FF] border border-[#2F5BEA]/20 text-[#2F5BEA] px-3.5 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-wider mb-4">
            {t("features.title")}
          </span>
          <h2 className="text-3xl sm:text-4xl font-bold font-manrope tracking-tight text-[#1A1C22] mb-3">{t("features.title")}</h2>
          <p className="text-[#56596a] text-base sm:text-lg max-w-2xl mx-auto">{t("features.subtitle")}</p>
        </div>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((feature, i) => (
            <div key={i} className="bg-[#FAFBFC] border border-[#E9EAEE] rounded-3xl p-6 transition-all duration-300 hover:shadow-lg hover:-translate-y-0.5">
              <div className="mb-4 inline-flex rounded-xl border border-[#2F5BEA]/20 bg-[#EEF2FF] px-3 py-1.5 text-xs font-bold tracking-[0.22em] text-[#2F5BEA]">
                {feature.icon}
              </div>
              <div className="text-[#1A1C22] font-bold mb-2 font-manrope">{feature.title}</div>
              <div className="text-[#56596a] text-xs sm:text-sm leading-relaxed">{feature.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ForCompanies({ t }: { t: (key: string, values?: Record<string, string | number>) => string }) {
  const roles = [
    t("roles.backend_engineer"),
    t("roles.frontend_engineer"),
    t("roles.qa_engineer"),
    t("roles.devops_engineer"),
    t("roles.data_scientist"),
    t("roles.product_manager"),
    t("roles.mobile_engineer"),
    t("roles.designer"),
  ];

  return (
    <section className="px-6 py-24 relative">
      <div className="max-w-6xl mx-auto grid gap-10 lg:grid-cols-[1fr_1.05fr] lg:items-center">
        <div className="bg-white border border-[#E9EAEE] rounded-3xl p-6 sm:p-8 shadow-[0_1px_2px_rgba(20,22,30,0.03)]">
          <span className="inline-flex items-center gap-2 bg-[#EEF2FF] border border-[#2F5BEA]/20 text-[#2F5BEA] px-3 py-1.5 rounded-full text-[10.5px] font-bold uppercase tracking-wider mb-4">
            {t("companies.kicker")}
          </span>
          <h2 className="text-3xl font-bold font-manrope tracking-tight text-[#1A1C22] mt-2 mb-4">{t("companies.title")}</h2>
          <p className="text-[#56596a] text-sm sm:text-base leading-relaxed mb-5">{t("companies.description1")}</p>
          <p className="text-[#56596a] text-sm sm:text-base leading-relaxed">{t("companies.description2")}</p>
        </div>
        <div className="grid grid-cols-2 gap-3.5">
          {roles.map((role, i) => (
            <div key={i} className="bg-white border border-[#E9EAEE] rounded-2xl px-5 py-4 text-sm font-bold text-[#1A1C22] shadow-[0_1px_2px_rgba(20,22,30,0.02)]">
              {role}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CTA({ t }: { t: (key: string, values?: Record<string, string | number>) => string }) {
  return (
    <section className="px-6 py-24">
      <div className="mx-auto max-w-5xl overflow-hidden rounded-[2rem] border border-[#D6E0FD] bg-[linear-gradient(135deg,#FFFFFF_0%,#EEF2FF_58%,#EAF8FF_100%)] p-8 text-center shadow-[0_24px_60px_rgba(47,91,234,0.12)] sm:p-12 relative">
        <div className="pointer-events-none absolute left-[-12%] top-[-40%] h-[320px] w-[320px] rounded-full bg-[#2F5BEA]/10 blur-[90px]" />
        <div className="pointer-events-none absolute bottom-[-45%] right-[-8%] h-[280px] w-[280px] rounded-full bg-sky-300/20 blur-[90px]" />
        <div className="relative z-1">
          <span className="mb-5 inline-flex rounded-full border border-[#2F5BEA]/20 bg-white/70 px-3.5 py-1.5 text-[11px] font-bold uppercase tracking-[0.18em] text-[#2F5BEA]">
            AI Recruit
          </span>
          <h2 className="text-3xl sm:text-4xl font-bold font-manrope tracking-tight text-[#1A1C22] mb-4">{t("cta.title")}</h2>
          <p className="text-[#56596a] text-base sm:text-lg mb-10 max-w-2xl mx-auto leading-relaxed">{t("cta.subtitle")}</p>
          <div className="flex flex-col justify-center gap-4 sm:flex-row">
            <Link href="/candidate/register" className="candidate-btn-primary rounded-xl px-8 py-4 text-base font-bold shadow-[0_4px_16px_rgba(47,91,234,0.3)]">
              {t("cta.candidate")}
            </Link>
            <Link href="/company/register" className="candidate-btn-secondary rounded-xl px-8 py-4 text-base font-bold shadow-[0_1px_2px_rgba(20,22,30,0.04)]">
              {t("cta.company")}
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

function Footer({ t }: { t: (key: string, values?: Record<string, string | number>) => string }) {
  return (
    <footer className="px-6 py-12 border-t border-[#E9EAEE] bg-white">
      <div className="max-w-6xl mx-auto flex flex-col items-center justify-between gap-6 sm:flex-row">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#14161B] text-sm font-bold tracking-[0.16em] text-[#7E9BFF]">
            AR
          </div>
          <div>
            <div className="text-[#1A1C22] font-bold font-manrope">AI Recruit</div>
            <div className="text-slate-400 text-[10px] uppercase tracking-[0.16em] font-semibold mt-0.5">Verification Cloud</div>
          </div>
        </div>
        <div className="flex items-center gap-6 text-sm text-slate-500 font-semibold">
          <Link href="/candidate/register" className="transition-colors hover:text-[#2F5BEA]">{t("footer.candidates")}</Link>
          <Link href="/company/register" className="transition-colors hover:text-[#2F5BEA]">{t("footer.companies")}</Link>
          <Link href="/candidate/login" className="transition-colors hover:text-[#2F5BEA]">{t("footer.signIn")}</Link>
        </div>
      </div>
    </footer>
  );
}
