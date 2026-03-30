import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";
import { LocaleSwitcher } from "@/components/locale-switcher";

export default async function HomePage() {
  const t = await getTranslations("home");

  return (
    <main className="ai-shell min-h-screen text-white">
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
    <nav className="ai-section sticky top-0 z-30 border-b border-[color:var(--color-border)] bg-[rgba(5,12,24,0.72)] px-6 py-4 backdrop-blur-xl">
      <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-400/30 bg-blue-500/10 text-sm font-semibold tracking-[0.16em] text-blue-200 shadow-[0_16px_34px_rgba(47,115,255,0.24)]">
            AR
          </div>
          <div>
            <div className="text-white font-semibold text-lg leading-none">AI Recruit</div>
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Verification Cloud</div>
          </div>
        </div>
        <div className="flex items-center gap-3 sm:gap-6">
          <a href="#how-it-works" className="hidden text-sm text-slate-400 transition-colors hover:text-white sm:block">
            {howItWorks}
          </a>
          <a href="#features" className="hidden text-sm text-slate-400 transition-colors hover:text-white sm:block">
            {features}
          </a>
          <LocaleSwitcher />
          <Link href="/candidate/login" className="text-sm text-slate-400 transition-colors hover:text-white">
            {signIn}
          </Link>
          <Link href="/company/register" className="ai-button-secondary rounded-full px-4 py-2 text-sm font-semibold">
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
    <section className="ai-section px-6 pb-16 pt-20 sm:pt-24">
      <div className="max-w-6xl mx-auto grid gap-10 lg:grid-cols-[1.08fr_0.92fr] lg:items-center">
        <div>
          <span className="ai-kicker mb-6">{badge}</span>
          <h1 className="max-w-4xl text-5xl font-semibold leading-[1.02] tracking-[-0.05em] sm:text-[4.4rem] lg:text-[5.2rem]">
            {title}
            <br />
            <span className="bg-gradient-to-r from-blue-100 via-blue-300 to-cyan-300 bg-clip-text text-transparent">
              {highlight}
            </span>
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300 sm:text-xl">
            {description}
          </p>
          <div className="mt-10 flex flex-col gap-4 sm:flex-row">
            <Link href="/candidate/register" className="ai-button-primary rounded-2xl px-8 py-3.5 text-center text-lg font-semibold">
              {candidateCta}
            </Link>
            <Link href="/company/register" className="ai-button-secondary rounded-2xl px-8 py-3.5 text-center text-lg font-semibold">
              {companyCta}
            </Link>
          </div>
          <p className="mt-4 text-sm text-slate-500">{note}</p>
        </div>
        <div className="ai-panel-strong rounded-[2rem] p-6 sm:p-7">
          <div className="flex items-center justify-between gap-4 border-b border-white/5 pb-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{panelTitle}</p>
              <h2 className="mt-2 text-lg font-semibold text-white sm:text-xl">{panelSubtitle}</h2>
            </div>
            <div className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold text-cyan-300">
              {panelStatus}
            </div>
          </div>
          <div className="mt-5 rounded-2xl border border-blue-500/20 bg-blue-500/5 p-4">
            <p className="text-sm font-semibold text-white">{summaryTitle}</p>
            <p className="mt-2 text-sm leading-6 text-slate-300">{summaryText}</p>
          </div>
          <div className="mt-4 space-y-3">
            {[
              [benefit1Title, benefit1Text],
              [benefit2Title, benefit2Text],
              [benefit3Title, benefit3Text],
            ].map(([label, text]) => (
              <div key={label} className="rounded-2xl border border-white/6 bg-white/[0.03] px-4 py-4">
                <div className="flex items-start gap-3">
                  <div className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-cyan-400 shadow-[0_0_14px_rgba(61,217,200,0.7)]" />
                  <div>
                    <p className="text-sm font-semibold text-slate-100">{label}</p>
                    <p className="mt-1 text-sm leading-6 text-slate-400">{text}</p>
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
    <section className="ai-section px-6 pb-10">
      <div className="max-w-6xl mx-auto grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((s, i) => (
          <div key={i} className="ai-stat rounded-[1.6rem] px-5 py-5">
            <div className="mt-2 text-4xl font-semibold tracking-[-0.04em] text-white">{s.value}</div>
            <div className="mt-2 text-sm text-slate-400">{s.label}</div>
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
    <section id="how-it-works" className="ai-section px-6 py-24">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <span className="ai-kicker mb-5">{t("how.title")}</span>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-[-0.03em] text-white mb-4">{t("how.title")}</h2>
          <p className="text-slate-400 text-lg">{t("how.subtitle")}</p>
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
    ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
    : "border-cyan-500/30 bg-cyan-500/10 text-cyan-300";
  const iconClass = accent === "blue"
    ? "border-blue-500/20 bg-blue-500/10 text-blue-200"
    : "border-cyan-500/20 bg-cyan-500/10 text-cyan-200";
  const buttonClass = accent === "blue" ? "ai-button-primary" : "ai-button-secondary";

  return (
    <div className="ai-panel-strong rounded-[2rem] p-8">
      <div className="flex items-center gap-3 mb-8">
        <span className={`rounded-full border px-3 py-1.5 text-sm font-semibold ${badgeClass}`}>
          {title}
        </span>
      </div>
      <div className="space-y-6">
        {steps.map((step, i) => (
          <div key={i} className="flex gap-4">
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border text-xs font-semibold tracking-[0.2em] ${iconClass}`}>
              {step.icon}
            </div>
            <div>
              <div className="text-white font-semibold mb-1">{step.title}</div>
              <div className="text-slate-400 text-sm leading-relaxed">{step.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <Link href={ctaHref} className={`${buttonClass} inline-block mt-8 rounded-2xl px-6 py-3 text-sm font-semibold`}>
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
    <section id="features" className="ai-section px-6 py-24">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <span className="ai-kicker mb-5">{t("features.title")}</span>
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-[-0.03em] text-white mb-4">{t("features.title")}</h2>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto">{t("features.subtitle")}</p>
        </div>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((feature, i) => (
            <div key={i} className="ai-panel rounded-[1.6rem] p-5 transition-transform duration-200 hover:-translate-y-1">
              <div className="mb-4 inline-flex rounded-xl border border-white/8 bg-slate-950/60 px-3 py-2 text-xs font-semibold tracking-[0.22em] text-slate-300">
                {feature.icon}
              </div>
              <div className="text-white font-semibold mb-2">{feature.title}</div>
              <div className="text-slate-400 text-sm leading-relaxed">{feature.desc}</div>
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
    <section className="ai-section px-6 py-24">
      <div className="max-w-6xl mx-auto grid gap-8 lg:grid-cols-[1fr_1.05fr] lg:items-center">
        <div className="ai-panel-strong rounded-[2rem] p-8">
          <span className="ai-kicker mb-5">{t("companies.kicker")}</span>
          <h2 className="text-3xl font-semibold tracking-[-0.03em] text-white mt-2 mb-4">{t("companies.title")}</h2>
          <p className="text-slate-400 leading-8 mb-6">{t("companies.description1")}</p>
          <p className="text-slate-400 leading-8">{t("companies.description2")}</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {roles.map((role, i) => (
            <div key={i} className="ai-panel rounded-[1.4rem] px-4 py-4 text-sm text-slate-200">
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
    <section className="ai-section px-6 py-24">
      <div className="ai-panel-strong max-w-4xl mx-auto rounded-[2rem] p-10 text-center">
        <h2 className="text-3xl sm:text-4xl font-semibold tracking-[-0.03em] text-white mb-4">{t("cta.title")}</h2>
        <p className="text-slate-400 text-lg mb-10 max-w-2xl mx-auto">{t("cta.subtitle")}</p>
        <div className="flex flex-col justify-center gap-4 sm:flex-row">
          <Link href="/candidate/register" className="ai-button-primary rounded-2xl px-8 py-3.5 text-lg font-semibold">
            {t("cta.candidate")}
          </Link>
          <Link href="/company/register" className="ai-button-secondary rounded-2xl px-8 py-3.5 text-lg font-semibold">
            {t("cta.company")}
          </Link>
        </div>
      </div>
    </section>
  );
}

function Footer({ t }: { t: (key: string, values?: Record<string, string | number>) => string }) {
  return (
    <footer className="ai-section px-6 py-10 border-t border-slate-800/80">
      <div className="max-w-6xl mx-auto flex flex-col items-center justify-between gap-4 sm:flex-row">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-400/20 bg-blue-500/10 text-sm font-semibold tracking-[0.16em] text-blue-200">
            AR
          </div>
          <div>
            <div className="text-white font-semibold">AI Recruit</div>
            <div className="text-slate-600 text-[10px] uppercase tracking-[0.16em]">Verification Cloud</div>
          </div>
        </div>
        <div className="flex items-center gap-6 text-sm text-slate-500">
          <Link href="/candidate/register" className="transition-colors hover:text-slate-300">{t("footer.candidates")}</Link>
          <Link href="/company/register" className="transition-colors hover:text-slate-300">{t("footer.companies")}</Link>
          <Link href="/candidate/login" className="transition-colors hover:text-slate-300">{t("footer.signIn")}</Link>
        </div>
      </div>
    </footer>
  );
}
