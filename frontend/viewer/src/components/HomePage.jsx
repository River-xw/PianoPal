import { useEffect, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";
import { profileSummarySentence } from "../utils/profile";

function NavCard({ title, description, onClick }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="flex flex-col gap-2 rounded-xl border px-5 py-5 text-left transition-colors"
      style={{
        borderColor: hovered ? "var(--accent)" : "var(--border)",
        background: hovered ? "var(--accent-light)" : "var(--surface)",
      }}
    >
      <span className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>{title}</span>
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>{description}</span>
    </button>
  );
}

// Logo is a plain wordmark (no image assets in the project) -- the accent
// square stands in for a mark/icon.
function Logo({ title }) {
  return (
    <div className="flex items-center justify-center gap-2">
      <span className="inline-block h-6 w-6 rounded-md" style={{ background: "var(--accent)" }} />
      <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>{title}</h1>
    </div>
  );
}

// Recent-summary card ("交互，近期总结" in the product spec): total practice
// count, recent average score, last-played piece, and a one-line "画像"
// sentence derived client-side (see utils/profile.js) -- all sourced from
// the same GET /api/history?limit=1 call MyPage.jsx uses, so a brand-new
// user with no history yet just sees the empty-state copy.
function RecentSummary({ username }) {
  const { t, lang } = useTranslation();
  const [data, setData] = useState(null);

  useEffect(() => {
    const name = (username || "").trim();
    if (!name) return;
    fetch(`/api/history?${new URLSearchParams({ username: name, limit: "1" })}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((parsed) => parsed && setData(parsed))
      .catch(() => {});
  }, [username]);

  if (!data) return null;
  const { profile, sessions } = data;
  const latest = sessions && sessions[0];

  return (
    <div
      className="mx-auto flex w-full max-w-2xl flex-col gap-2 rounded-xl border px-5 py-4"
      style={{ borderColor: "var(--border)", background: "var(--accent-light)" }}
    >
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm" style={{ color: "var(--text-secondary)" }}>
        <span>{t("recentSummaryTotal", { count: profile?.total_sessions ?? 0 })}</span>
        {profile?.recent_avg_score != null && (
          <span>{t("recentSummaryAvg", { score: profile.recent_avg_score.toFixed(1) })}</span>
        )}
        {latest && (
          <span>{t("recentSummaryLast", { title: latest.piece_title, date: new Date(latest.started_at).toLocaleDateString() })}</span>
        )}
      </div>
      <div className="text-sm" style={{ color: "var(--text-muted)" }}>{profileSummarySentence(profile, lang)}</div>
    </div>
  );
}

export default function HomePage({ username, onNavigate, onSwitchUser }) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-8 py-6">
      <div className="text-center">
        <Logo title={t("appTitle")} />
        <p className="mt-2 text-base" style={{ color: "var(--text-muted)" }}>{t("appSlogan")}</p>
        <button
          className="mt-2 text-xs underline"
          style={{ color: "var(--text-muted)" }}
          onClick={onSwitchUser}
        >
          {t("currentUserLabel", { username })}
        </button>
      </div>

      <RecentSummary username={username} />

      <div className="mx-auto grid w-full max-w-2xl grid-cols-1 gap-4 sm:grid-cols-3">
        <NavCard title={t("navLearnMode")} description={t("navLearnModeDesc")} onClick={() => onNavigate("learn")} />
        <NavCard title={t("navPerformMode")} description={t("navPerformModeDesc")} onClick={() => onNavigate("perform")} />
        <NavCard title={t("navMe")} description={t("navMeDesc")} onClick={() => onNavigate("me")} />
      </div>
    </div>
  );
}
