import { useCallback, useState } from "react";
import SummaryPanel from "./components/SummaryPanel";
import NotationView from "./components/NotationView";
import FeedbackPanel from "./components/FeedbackPanel";
import PianoRoll from "./components/PianoRoll";
import TimingStrip from "./components/TimingStrip";
import SessionSetup from "./components/SessionSetup";
import LiveSession from "./components/LiveSession";

// Home screen is the practice-session flow: pick a song + speed
// (SessionSetup) -> guide+record runs on the Pi (LiveSession) -> the
// orchestrator (scripts/session_server.py) grades the recording and writes
// result.json, which we then load automatically -- "view" tracks exactly
// where in that flow we are. Manually loading a past result.json (the
// header button) jumps straight to "result" regardless of session state.
export default function App() {
  const [view, setView] = useState("setup"); // setup | live | result
  const [liveInfo, setLiveInfo] = useState(null); // { songTitle }
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const loadResult = useCallback(() => {
    fetch(`/result.json?t=${Date.now()}`)
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
          throw new Error("Not a scoring result.json (missing summary/notes).");
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
            PianoPal
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
              回到選歌
            </button>
          )}
          <label
            className="cursor-pointer rounded-lg border px-3 py-1.5 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          >
            Load result.json
            <input
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
          </label>
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

      {view === "setup" && <SessionSetup onStarted={handleStarted} />}

      {view === "live" && liveInfo && (
        <LiveSession
          songTitle={liveInfo.songTitle}
          onDone={loadResult}
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
