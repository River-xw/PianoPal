import { useEffect, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";
import { profileSummarySentence } from "../utils/profile";
import Doodles from "./Doodles.jsx";
import BrandLogo from "./BrandLogo.jsx";

const TAPE_COLORS = ["var(--sketch-sky)", "var(--sketch-teal)", "var(--sketch-indigo)"];
const CARD_TILT = [-2, 1.5, -1];

function ModeIllustration({ name }) {
  return (
    <span className="mode-illustration" aria-hidden="true">
      <img
        className="mode-illustration__frame mode-illustration__frame--idle"
        src={`/illustrations/${name}-idle.svg`}
        alt=""
      />
      <img
        className="mode-illustration__frame mode-illustration__frame--active"
        src={`/illustrations/${name}-active.svg`}
        alt=""
      />
    </span>
  );
}

function NavCard({ title, description, onClick, index, illustration }) {
  return (
    <div
      className="mode-card flex min-w-0 flex-col items-stretch"
      style={{
        "--card-tilt": `${CARD_TILT[index % CARD_TILT.length]}deg`,
      }}
    >
      <ModeIllustration name={illustration} />
      <button
        onClick={onClick}
        className={`home-nav-card sketch-card${index % 2 ? "" : "-alt"} relative flex flex-1 flex-col gap-2 px-5 py-5 text-left`}
      >
        <span
          className="washi-tape left-6"
          style={{ background: TAPE_COLORS[index % TAPE_COLORS.length], transform: "rotate(-4deg)" }}
        />
        <span className="text-xl" style={{ color: "var(--text-primary)" }}>{title}</span>
        <span className="text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>{description}</span>
      </button>
    </div>
  );
}

function HomeGreeting() {
  const { t } = useTranslation();
  const [quoteIndex] = useState(() => Math.floor(Math.random() * 5));

  return (
    <div className="home-greeting mx-auto">
      <div className="sprite-paper sprite-paper--greeting">
        <img src="/assets/spirit-greeting.png" alt="" className="home-greeting__spirit" aria-hidden="true" />
      </div>
      <div className="doodle-speech-bubble" role="note">
        {t(`practiceQuote${quoteIndex + 1}`)}
      </div>
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
        <BrandLogo className="home-logo mx-auto" animated />
        <p className="mt-2 text-base" style={{ color: "var(--text-muted)" }}>{t("appSlogan")}</p>
        <button
          className="mt-2 text-xs underline"
          style={{ color: "var(--text-muted)" }}
          onClick={onSwitchUser}
        >
          {t("currentUserLabel", { username })}
        </button>
      </div>

      <HomeGreeting />

      <RecentSummary username={username} />

      <div className="mx-auto grid w-full max-w-3xl grid-cols-1 gap-8 pt-1 sm:grid-cols-3 sm:gap-6">
        <NavCard index={0} illustration="learn" title={t("navLearnMode")} description={t("navLearnModeDesc")} onClick={() => onNavigate("learn")} />
        <NavCard index={1} illustration="perform" title={t("navPerformMode")} description={t("navPerformModeDesc")} onClick={() => onNavigate("perform")} />
        <NavCard index={2} illustration="profile" title={t("navMe")} description={t("navMeDesc")} onClick={() => onNavigate("me")} />
      </div>
    </div>
  );
}
