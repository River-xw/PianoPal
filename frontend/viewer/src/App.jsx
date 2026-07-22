import { useEffect, useState } from "react";
import SummaryPanel from "./components/SummaryPanel";
import NotationView from "./components/NotationView";
import FeedbackPanel from "./components/FeedbackPanel";
import PianoRoll from "./components/PianoRoll";
import TimingStrip from "./components/TimingStrip";
import GuideControl from "./components/GuideControl";

export default function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [checkedAutoLoad, setCheckedAutoLoad] = useState(false);

  // scripts/grade.py drops its output at frontend/viewer/public/result.json -- if it's there,
  // load it automatically so opening the browser shows the result right away.
  useEffect(() => {
    fetch(`/result.json?t=${Date.now()}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((parsed) => {
        if (parsed && parsed.summary && parsed.notes) setResult(parsed);
      })
      .catch(() => {})
      .finally(() => setCheckedAutoLoad(true));
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
      } catch (e) {
        setError(e.message);
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>
            Performance Viewer
          </h1>
          {result?.song_name && (
            <div className="text-sm" style={{ color: "var(--text-muted)" }}>
              {result.song_name}
            </div>
          )}
        </div>
        <label
          className="cursor-pointer rounded-lg border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
        >
          {result ? "Load another result.json" : "Load result.json"}
          <input
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </label>
      </header>

      <div className="mb-4">
        <GuideControl />
      </div>

      {error && (
        <div
          className="mb-4 rounded-lg border px-4 py-2 text-sm"
          style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}
        >
          {error}
        </div>
      )}

      {!result && !error && checkedAutoLoad && (
        <div
          className="flex h-64 flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-center px-6"
          style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          <span>No result loaded yet.</span>
          <span>
            Click "Load result.json" above to pick a file produced by <code>python -m backend.scoring</code>.
          </span>
        </div>
      )}

      {result && (
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
