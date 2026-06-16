import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

export default async function NotFound() {
  const t = await getTranslations("systemPages.notFound");
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F4F5F7] px-4">
      <div className="w-full max-w-lg rounded-[2rem] border border-[#E9EAEE] bg-white p-8 text-center shadow-[0_24px_70px_rgba(20,22,30,0.08)]">
        <div className="mb-4 font-manrope text-6xl font-bold text-[#D6E0FD]">404</div>
        <h1 className="mb-2 font-manrope text-2xl font-bold text-[#1A1C22]">{t("title")}</h1>
        <p className="mb-8 text-[#56596a]">{t("description")}</p>
        <div className="flex gap-3 justify-center">
          <Link
            href="/candidate/dashboard"
            className="candidate-btn-primary rounded-xl px-5 py-2.5 font-bold"
          >
            {t("candidate")}
          </Link>
          <Link
            href="/company/dashboard"
            className="candidate-btn-secondary rounded-xl px-5 py-2.5 font-bold"
          >
            {t("company")}
          </Link>
        </div>
      </div>
    </div>
  );
}
