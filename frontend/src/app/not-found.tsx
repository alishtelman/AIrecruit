import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

export default async function NotFound() {
  const t = await getTranslations("systemPages.notFound");
  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center px-4">
      <div className="text-center">
        <div className="text-6xl font-bold text-slate-700 mb-4">404</div>
        <h1 className="text-2xl font-bold text-white mb-2">{t("title")}</h1>
        <p className="text-slate-400 mb-8">{t("description")}</p>
        <div className="flex gap-3 justify-center">
          <Link
            href="/candidate/dashboard"
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-5 py-2.5 rounded-lg transition-colors"
          >
            {t("candidate")}
          </Link>
          <Link
            href="/company/dashboard"
            className="bg-slate-700 hover:bg-slate-600 text-white font-semibold px-5 py-2.5 rounded-lg transition-colors"
          >
            {t("company")}
          </Link>
        </div>
      </div>
    </div>
  );
}
