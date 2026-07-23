import { useCallback, useEffect, useState } from "react";
import SummaryPanel from "./components/SummaryPanel";
import NotationView from "./components/NotationView";
import FeedbackPanel from "./components/FeedbackPanel";
import PianoRoll from "./components/PianoRoll";
import TimingStrip from "./components/TimingStrip";
import SessionSetup from "./components/SessionSetup";
import LiveSession from "./components/LiveSession";
import { useTranslation } from "./LanguageContext.jsx";
import { LANGUAGES } from "./i18n";

const USERNAME_STORAGE_KEY = "pianopal_username";

// Home screen is the practice-session flow: enter a name, pick a song +
// speed (SessionSetup) -> guide+record runs on the Pi (LiveSession) -> the
// orchestrator grades the recording and writes a per-user result file
// (data/session_scratch/results/<name>.json), which we then load -- "view"
// tracks exactly where in that flow we are. Results are scoped by username
// (GET /api/results/<username>) so two people's scores never overwrite each
// other; the username itself persists in localStorage so a page reload
// remembers who you are and re-shows your own last result, not whoever ran
// the session before you.
export default function App() {
  const { t, lang, setLang } = useTranslation();
  const [view, setView] = useState("setup"); // setup | live | result
  const [liveInfo, setLiveInfo] = useState(null); // { songTitle }
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [username, setUsername] = useState(() => {
    try {
      return localStorage.getItem(USERNAME_STORAGE_KEY) || "";
    } catch {
      return "";
    }
  });

  const handleUsernameChange = (next) => {
    setUsername(next);
    try {
      localStorage.setItem(USERNAME_STORAGE_KEY, next);
    } catch {
      // localStorage unavailable -- username just won't persist across reloads
    }
  };

  const loadResult = useCallback((forUsername) => {
    const name = (forUsername ?? "").trim();
    if (!name) return;
    // No ?t= cache-buster: a query string doesn't match Vite's dev proxy
    // rule (it falls through to the SPA index.html instead of forwarding to
    // the orchestrator), so use cache:"no-store" for freshness instead -- the
    // server also sends Cache-Control: no-cache.
    fetch(`/api/results/${encodeURIComponent(name)}`, { cache: "no-store" })
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

  // Auto-show this (remembered) user's latest graded result on first open.
  useEffect(() => {
    if (username) loadResult(username);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const handleStarted = ({ songId, songs }) => {
    setLiveInfo({ songTitle: songs.find((s) => s.id === songId)?.title || songId });
    setError(null);
    setView("live");
  };

  const handleLiveError = (message) => {
    setError(message);
    setView("setup");
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
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
          {view !== "setup" && (
            <button
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
              onClick={() => setView("setup")}
            >
              {t("backToSongs")}
            </button>
          )}
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

      {view === "setup" && (
        <SessionSetup
          username={username}
          onUsernameChange={handleUsernameChange}
          onStarted={handleStarted}
          onViewLastResult={() => loadResult(username)}
        />
      )}

      {view === "live" && liveInfo && (
        <LiveSession
          songTitle={liveInfo.songTitle}
          onDone={() => loadResult(username)}
          onError={handleLiveError}
        />
      )}

      {view === "result" && result && (
        <div className="flex flex-col gap-4">
          <SummaryPanel summary={result.summary} />
          <NotationView notes={result.notes} />
          <FeedbackPanel notes={result.notes} summary={result.summary} />
          <PianoRoll notes={result.notes} />
          <TimingStrip notes={result.notes} />
        </div>
      )}
    </div>
  );
}
