import { useEffect, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";
import { profileSummarySentence } from "../utils/profile";
import Doodles from "./Doodles.jsx";
import Mascot from "./Mascot.jsx";

const TAPE_COLORS = ["var(--sketch-sky)", "var(--sketch-teal)", "var(--sketch-indigo)"];
const CARD_TILT = [-2, 1.5, -1];

function NavCard({ title, description, onClick, index }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`sketch-card${index % 2 ? "" : "-alt"} relative flex flex-col gap-2 px-5 py-5 text-left transition-colors`}
      style={{
        borderColor: hovered ? "var(--accent)" : "var(--border)",
        background: hovered ? "var(--accent-light)" : "var(--surface)",
        transform: `rotate(${CARD_TILT[index % CARD_TILT.length]}deg)`,
      }}
    >
      <span
        className="washi-tape left-6"
        style={{ background: TAPE_COLORS[index % TAPE_COLORS.length], transform: "rotate(-4deg)" }}
      />
      <span className="text-lg" style={{ color: "var(--text-primary)", fontFamily: "var(--font-title)" }}>{title}</span>
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>{description}</span>
    </button>
  );
}

// Logo is a plain wordmark (no image assets in the project) -- a little
// hand-drawn pencil icon stands in for a mark.
function Logo({ title }) {
  return (
    <div className="flex items-center justify-center gap-2">
      <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7" style={{ transform: "rotate(-8deg)" }}>
        <path d="m14.5 3.5 6 6L8 22H2v-6z" />
        <path d="m13 5 6 6" />
      </svg>
      <h1 className="text-3xl" style={{ color: "var(--text-primary)" }}>{title}</h1>
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
      className="sketch-card tint-navy mx-auto flex w-full max-w-2xl flex-col gap-2 px-5 py-4"
      style={{ border: "none" }}
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
    <div className="relative flex flex-col gap-8 py-6">
      <Doodles />
      <div className="text-center">
        <Mascot className="mx-auto h-16 w-16" />
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

      <div className="mx-auto grid w-full max-w-2xl grid-cols-1 gap-6 pt-2 sm:grid-cols-3">
        <NavCard index={0} title={t("navLearnMode")} description={t("navLearnModeDesc")} onClick={() => onNavigate("learn")} />
        <NavCard index={1} title={t("navPerformMode")} description={t("navPerformModeDesc")} onClick={() => onNavigate("perform")} />
        <NavCard index={2} title={t("navMe")} description={t("navMeDesc")} onClick={() => onNavigate("me")} />
      </div>
    </div>
  );
}
