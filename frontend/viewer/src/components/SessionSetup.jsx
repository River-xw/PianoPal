import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";
import { IconChevronDown, IconLightbulb, IconRepeat, IconTarget } from "./icons.jsx";
import NotationView from "./NotationView.jsx";

const FIELD_CLASS = "rounded-lg border px-3 py-2 text-sm transition-shadow focus:outline-none focus:ring-2 focus:ring-[var(--accent)]";

// Talks to edge/practice_server.py, running ON the Raspberry Pi -- this
// page is served BY that same server, so all API calls are same-origin
// relative paths (no host/CORS configuration needed).
//
// Shared by both 学习模式 (mode="learn", LED-guided) and 演奏模式
// (mode="perform", no LED guidance) -- same component, same API, just a
// different `mode` sent to POST /api/session/start (which picks the
// matching ScoringConfig weight preset -- see edge/practice_server.py's
// MODE_SCORE_WEIGHTS) and different copy/labels.
export default function SessionSetup({ mode, username, onUsernameChange, onStarted }) {
  const { t } = useTranslation();
  const [songs, setSongs] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [speed, setSpeed] = useState(1.0);
  const [brightness, setBrightness] = useState(0.25);
  const [fullRange, setFullRange] = useState(false);
  const [loopStart, setLoopStart] = useState("");
  const [loopEnd, setLoopEnd] = useState("");
  const [loopExpanded, setLoopExpanded] = useState(false);
  const [refNotes, setRefNotes] = useState([]);
  const [importing, setImporting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  // 曲目記憶: pass username+mode so the backend can tell us this user's most
  // recently played song in this mode (GET /api/songs?username=&mode=), and
  // default the picker to it instead of always the library's first song.
  const loadSongs = () => {
    const params = new URLSearchParams({ mode });
    if (username.trim()) params.set("username", username.trim());
    fetch(`/api/songs?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => {
        setSongs(data.songs || []);
        setError(null);
        setSelectedId((prev) => prev || data.last_song_id || data.songs?.[0]?.id || "");
      })
      .catch(() => setError(t("connectFailed")));
  };

  useEffect(loadSongs, []);

  // 分段循環練習的琴譜預覽: only fetch once the picker is actually open (and
  // a song is chosen) -- no point loading notation nobody's looking at.
  useEffect(() => {
    if (!loopExpanded || !selectedId) return;
    fetch(`/api/songs/${encodeURIComponent(selectedId)}/reference`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setRefNotes(data?.notes || []))
      .catch(() => setRefNotes([]));
  }, [loopExpanded, selectedId]);

  const handleImport = async (file) => {
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      const bytes = await file.arrayBuffer();
      const res = await fetch("/api/songs/import", {
        method: "POST",
        headers: { "X-Song-Title": encodeURIComponent(file.name.replace(/\.mid$/i, "")) },
        body: bytes,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || t("importFailed"));
      loadSongs();
      setSelectedId(data.id);
    } catch (e) {
      setError(e.message);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  // loopParams (learn mode only): {start, end} -> 分段循環練習, a practice
  // aid that never gets graded/saved (see edge/practice_server.py's
  // Session.practice_only); undefined -> a normal graded attempt.
  const handleStart = async (loopParams) => {
    if (!selectedId) return;
    if (!username.trim()) {
      setError(t("yourNameRequired"));
      return;
    }
    setStarting(true);
    setError(null);
    try {
      const body = { song_id: selectedId, speed, username: username.trim(), mode };
      if (mode === "learn") {
        body.brightness = brightness;
        body.full_range = fullRange;
        if (loopParams) {
          body.loop_start_measure = loopParams.start;
          body.loop_end_measure = loopParams.end;
        }
      }
      const res = await fetch("/api/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || t("cannotStart"));
      onStarted({ songId: selectedId, songs, sessionId: data.session_id, practiceOnly: !!loopParams });
    } catch (e) {
      setError(e.message);
      setStarting(false);
    }
  };

  const selected = songs.find((s) => s.id === selectedId);
  const loopStartNum = parseInt(loopStart, 10);
  const loopEndNum = parseInt(loopEnd, 10);
  const loopValid = Number.isInteger(loopStartNum) && Number.isInteger(loopEndNum) && loopStartNum > 0 && loopEndNum >= loopStartNum;
  // Highlight as much of the range as is valid so far while typing -- just
  // the start measure once that alone is a valid number, expanding to the
  // full range once the end measure is also valid and in order.
  const previewRange = Number.isInteger(loopStartNum) && loopStartNum > 0
    ? { start: loopStartNum, end: Number.isInteger(loopEndNum) && loopEndNum >= loopStartNum ? loopEndNum : loopStartNum }
    : null;

  const ModeIcon = mode === "perform" ? IconTarget : IconLightbulb;

  return (
    <div className="sketch-card flex flex-col gap-6 px-6 py-6">
      <div className="flex items-center gap-3 pb-5" style={{ borderBottom: "2px dashed var(--border)" }}>
        <div
          className="sketch-btn flex h-11 w-11 shrink-0 items-center justify-center"
          style={{ background: "var(--accent-light)", color: "var(--accent)", border: "none" }}
        >
          <ModeIcon className="h-6 w-6" />
        </div>
        <div>
          <h2 className="text-2xl" style={{ color: "var(--text-primary)" }}>
            {mode === "perform" ? t("navPerformMode") : t("navLearnMode")}
          </h2>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            {mode === "perform" ? t("startPerformDescription") : t("startPracticeDescription")}
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}>
          {error}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-base" style={{ color: "var(--text-primary)", fontFamily: "var(--font-title)" }}>
          {t("yourName")}
        </span>
        <input
          type="text"
          className={FIELD_CLASS}
          style={{ borderColor: "var(--border)", color: "var(--text-primary)", background: "transparent" }}
          value={username}
          onChange={(e) => onUsernameChange(e.target.value)}
          placeholder={t("yourNamePlaceholder")}
        />
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-base" style={{ color: "var(--text-primary)", fontFamily: "var(--font-title)" }}>
          {t("song")}
        </span>
        <select
          className={FIELD_CLASS}
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)", background: "transparent" }}
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
        >
          {songs.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </select>
        {selected && !selected.white_keys_only && (
          <span className="text-xs" style={{ color: "var(--status-timing-off)" }}>
            {t("blackKeyWarning")}
          </span>
        )}

        <label
          className="cursor-pointer self-start rounded-lg border px-3 py-1.5 text-xs transition-colors hover:border-[var(--accent)]"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
        >
          {importing ? t("importing") : t("importSong")}
          <input
            ref={fileInputRef}
            type="file"
            accept=".mid,.midi"
            className="hidden"
            onChange={(e) => handleImport(e.target.files?.[0])}
          />
        </label>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-base" style={{ color: "var(--text-primary)", fontFamily: "var(--font-title)" }}>
          {t(mode === "perform" ? "targetSpeedLabel" : "speedLabel", { speed: speed.toFixed(2) })}
        </span>
        <input
          type="range"
          min="0.3"
          max="1.5"
          step="0.05"
          value={speed}
          onChange={(e) => setSpeed(parseFloat(e.target.value))}
        />
      </div>

      {mode === "learn" && (
        <div className="sketch-card-alt tint-teal flex flex-col gap-3 px-4 py-4" style={{ border: "none" }}>
          <span className="flex items-center gap-2 text-base" style={{ color: "var(--text-primary)", fontFamily: "var(--font-title)" }}>
            <IconLightbulb className="h-4 w-4" style={{ color: "var(--sketch-teal)" }} />
            {t("ledConfigLabel")}
          </span>
          <div className="flex flex-col gap-1">
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              {t("brightnessLabel", { pct: Math.round(brightness * 100) })}
            </span>
            <input
              type="range"
              min="0.05"
              max="1.0"
              step="0.05"
              value={brightness}
              onChange={(e) => setBrightness(parseFloat(e.target.value))}
            />
          </div>
          <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
            <input type="checkbox" checked={fullRange} onChange={(e) => setFullRange(e.target.checked)} />
            {t("fullRangeLabel")}
          </label>
        </div>
      )}

      {mode === "learn" && (
        <div className="sketch-card-alt tint-indigo overflow-hidden" style={{ border: "none" }}>
          <button
            className="flex w-full items-center justify-between px-4 py-3 text-left"
            onClick={() => setLoopExpanded((v) => !v)}
          >
            <span className="flex items-center gap-2 text-base" style={{ color: "var(--text-primary)", fontFamily: "var(--font-title)" }}>
              <IconRepeat className="h-4 w-4" style={{ color: "var(--sketch-indigo)" }} />
              {t("segmentLoopLabel")}
            </span>
            <IconChevronDown
              className="h-4 w-4 transition-transform"
              style={{ color: "var(--text-muted)", transform: loopExpanded ? "rotate(180deg)" : "none" }}
            />
          </button>
          {loopExpanded && (
            <div className="flex flex-col gap-2 px-4 py-3" style={{ borderTop: "2px dashed var(--border)" }}>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>{t("segmentLoopHint")}</span>
              {refNotes.length > 0 && <NotationView notes={refNotes} preview highlightRange={previewRange} />}
              <div className="flex items-end gap-2">
                <div className="flex flex-col gap-1">
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>{t("segmentLoopStart")}</span>
                  <input
                    type="number"
                    min="1"
                    className={`w-16 ${FIELD_CLASS}`}
                    style={{ borderColor: "var(--border)", color: "var(--text-primary)", background: "transparent" }}
                    value={loopStart}
                    onChange={(e) => setLoopStart(e.target.value)}
                  />
                </div>
                <span className="pb-1.5" style={{ color: "var(--text-muted)" }}>-</span>
                <div className="flex flex-col gap-1">
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>{t("segmentLoopEnd")}</span>
                  <input
                    type="number"
                    min="1"
                    className={`w-16 ${FIELD_CLASS}`}
                    style={{ borderColor: "var(--border)", color: "var(--text-primary)", background: "transparent" }}
                    value={loopEnd}
                    onChange={(e) => setLoopEnd(e.target.value)}
                  />
                </div>
                <button
                  className="rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors hover:border-[var(--accent)] disabled:opacity-50 disabled:hover:border-[var(--border)]"
                  style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                  disabled={!selectedId || !loopValid || starting}
                  onClick={() => handleStart({ start: loopStartNum, end: loopEndNum })}
                >
                  {t("startSegmentLoop")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <button
        className="sketch-btn wiggle-hover px-4 py-3 text-base transition-opacity hover:opacity-90 disabled:opacity-50"
        style={{ background: "var(--accent)", color: "var(--accent-contrast)", border: "none", fontFamily: "var(--font-title)" }}
        disabled={!selectedId || starting}
        onClick={() => handleStart()}
      >
        {starting ? t("starting") : t("startPractice")}
      </button>
    </div>
  );
}
