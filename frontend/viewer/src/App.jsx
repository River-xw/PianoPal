import { useCallback, useState } from "react";
import SummaryPanel from "./components/SummaryPanel";
import NotationView from "./components/NotationView";
import FeedbackPanel from "./components/FeedbackPanel";
import PianoRoll from "./components/PianoRoll";
import TimingStrip from "./components/TimingStrip";
import SessionSetup from "./components/SessionSetup";
import LiveSession from "./components/LiveSession";
import OnboardingPage from "./components/OnboardingPage";
import HomePage from "./components/HomePage";
import MyPage from "./components/MyPage";
import { useTranslation } from "./LanguageContext.jsx";
import { LANGUAGES } from "./i18n";

const USERNAME_STORAGE_KEY = "pianopal_username";
// Short, single-card "hero" pages -- vertically centered in whatever's left
// of the viewport below the header, so a wide/short 16:9 window doesn't just
// pin them to the top with a big dead gap underneath. "me" and the result
// view are excluded: their content is naturally long/scrollable and
// shouldn't be squeezed into one screen's worth of height.
const CENTERED_PAGES = new Set(["onboarding", "home", "learn", "perform"]);

function readStoredUsername() {
  try {
    return localStorage.getItem(USERNAME_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

// Top-level page state machine: "onboarding" (name + slogan, first run or
// switching identity) | "home" (nav hub, logo + recent summary) | "learn" |
// "perform" (each with its own setup -> live -> result sub-flow, sharing
// SessionSetup/LiveSession/the result-view component set, parameterized by
// `mode`) | "me" (past practice_sessions rows + profile, backend.db.sqlite
// via GET /api/history). Username persists in localStorage; a returning
// user (non-empty cached name) skips onboarding and boots straight to home.
export default function App() {
  const { t, lang, setLang } = useTranslation();
  const [page, setPage] = useState(() => (readStoredUsername() ? "home" : "onboarding"));
  const [view, setView] = useState("setup"); // setup | live | result -- only meaningful within learn/perform
  const [liveInfo, setLiveInfo] = useState(null); // { songTitle, sessionId, practiceOnly }
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [username, setUsername] = useState(readStoredUsername);

  const handleUsernameChange = (next) => {
    setUsername(next);
    try {
      localStorage.setItem(USERNAME_STORAGE_KEY, next);
    } catch {
      // localStorage unavailable -- username just won't persist across reloads
    }
  };

  const loadResult = useCallback((sessionId) => {
    if (!sessionId) return;
    // No ?t= cache-buster: a query string doesn't match Vite's dev proxy
    // rule (it falls through to the SPA index.html instead of forwarding to
    // the orchestrator), so use cache:"no-store" for freshness instead -- the
    // server also sends Cache-Control: no-cache.
    fetch(`/api/history/${sessionId}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((parsed) => {
        if (parsed && parsed.summary && parsed.notes) {
          setResult(parsed);
          setError(null);
          setView("result");
        }
      })
      .catch(() => {});
  }, []);

  const handleFile = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(reader.result);
        if (!parsed.summary || !parsed.notes) {
          throw new Error(t("errorNotAResultFile"));
        }
        setResult(parsed);
        setError(null);
        setView("result");
      } catch (e) {
        setError(e.message);
      }
    };
    reader.readAsText(file);
  };

  const handleStarted = ({ songId, songs, sessionId, practiceOnly }) => {
    setLiveInfo({ songTitle: songs.find((s) => s.id === songId)?.title || songId, sessionId, practiceOnly });
    setError(null);
    setView("live");
  };

  const handleLiveError = (message) => {
    setError(message);
    setView("setup");
  };

  const handleLiveDone = () => {
    // 分段循環練習 (practiceOnly) never gets graded/saved -- there's no
    // result to show, just go back to picking a song/segment again.
    if (liveInfo?.practiceOnly) {
      setView("setup");
      return;
    }
    loadResult(liveInfo?.sessionId);
  };

  const goHome = () => {
    setPage("home");
    setView("setup");
    setLiveInfo(null);
    setResult(null);
    setError(null);
  };

  const navigate = (nextPage) => {
    setPage(nextPage);
    setView("setup");
    setError(null);
  };

  const handleOnboardingEnter = () => {
    setPage("home");
  };

  const handleSwitchUser = () => {
    setPage("onboarding");
  };

  const isCentered = view !== "result" && CENTERED_PAGES.has(page);

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-6 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
            {t("appTitle")}
          </h1>
          {result?.song_name && view === "result" && (
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>
              {result.song_name}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {page !== "onboarding" && (page !== "home" || view === "result") && (
            <button
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
              onClick={goHome}
            >
              {t("backToHome")}
            </button>
          )}
          {page !== "onboarding" && (
            <label
              className="cursor-pointer rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            >
              {t("loadResultJson")}
              <input
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(e) => handleFile(e.target.files?.[0])}
              />
            </label>
          )}
          <button
            className="rounded-lg border px-3 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            onClick={() => setLang(lang === LANGUAGES.ZH ? LANGUAGES.EN : LANGUAGES.ZH)}
            title="简体中文 / English"
          >
            {lang === LANGUAGES.ZH ? "EN" : "中文"}
          </button>
        </div>
      </header>

      {error && (
        <div
          className="mb-4 rounded-lg border px-4 py-2 text-sm"
          style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}
        >
          {error}
        </div>
      )}

      {/* A loaded/graded result takes priority over whatever `page` is --
          "Load result.json" is available from any page (including home),
          so it must be able to display regardless of which page was active
          when it was triggered, not just from within learn/perform. Short
          "hero" pages (onboarding/home/learn/perform) get centered in
          whatever height is left below the header; "me" and the result view
          scroll from the top since their content length varies. */}
      <div className={isCentered ? "flex flex-1 flex-col justify-center" : "flex-1"}>
      {view === "result" && result ? (
        <div className="flex flex-col gap-4">
          <SummaryPanel summary={result.summary} />
          <NotationView notes={result.notes} />
          <FeedbackPanel notes={result.notes} summary={result.summary} />
          <PianoRoll notes={result.notes} />
          <TimingStrip notes={result.notes} />
        </div>
      ) : page === "onboarding" ? (
        <OnboardingPage username={username} onUsernameChange={handleUsernameChange} onEnter={handleOnboardingEnter} />
      ) : page === "home" ? (
        <HomePage username={username} onNavigate={navigate} onSwitchUser={handleSwitchUser} />
      ) : page === "me" ? (
        <MyPage username={username} />
      ) : page === "learn" || page === "perform" ? (
        view === "live" && liveInfo ? (
          <LiveSession
            mode={page}
            songTitle={liveInfo.songTitle}
            onDone={handleLiveDone}
            onError={handleLiveError}
          />
        ) : (
          <SessionSetup
            mode={page}
            username={username}
            onUsernameChange={handleUsernameChange}
            onStarted={handleStarted}
          />
        )
      ) : null}
      </div>
    </div>
  );
}
