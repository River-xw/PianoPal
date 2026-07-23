import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";

// Talks to edge/practice_server.py, running ON the Raspberry Pi -- this
// page is served BY that same server, so all API calls are same-origin
// relative paths (no host/CORS configuration needed).

export default function SessionSetup({ username, onUsernameChange, onStarted, onViewLastResult }) {
  const { t } = useTranslation();
  const [songs, setSongs] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [speed, setSpeed] = useState(1.0);
  const [importing, setImporting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);
  const [hasLastResult, setHasLastResult] = useState(false);
  const fileInputRef = useRef(null);

  const loadSongs = () => {
    fetch("/api/songs")
      .then((res) => res.json())
      .then((data) => {
        setSongs(data.songs || []);
        setError(null);
        setSelectedId((prev) => prev || data.songs?.[0]?.id || "");
      })
      .catch(() => setError(t("connectFailed")));
  };

  useEffect(loadSongs, []);

  // Is there an already-graded result for THIS username? Re-checked whenever
  // the name changes, so switching users updates the shortcut accordingly.
  useEffect(() => {
    const name = username.trim();
    if (!name) {
      setHasLastResult(false);
      return;
    }
    let cancelled = false;
    fetch(`/api/results/${encodeURIComponent(name)}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((r) => {
        if (!cancelled) setHasLastResult(!!(r && r.summary && r.notes));
      })
      .catch(() => {
        if (!cancelled) setHasLastResult(false);
      });
    return () => {
      cancelled = true;
    };
  }, [username]);

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

  const handleStart = async () => {
    if (!selectedId) return;
    if (!username.trim()) {
      setError(t("yourNameRequired"));
      return;
    }
    setStarting(true);
    setError(null);
    try {
      const res = await fetch("/api/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ song_id: selectedId, speed, username: username.trim() }),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || t("cannotStart"));
      onStarted({ songId: selectedId, songs });
    } catch (e) {
      setError(e.message);
      setStarting(false);
    }
  };

  const selected = songs.find((s) => s.id === selectedId);

  return (
    <div className="flex flex-col gap-5 rounded-xl border px-6 py-6" style={{ borderColor: "var(--border)" }}>
      <div>
        <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
          {t("startPractice")}
        </h2>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          {t("startPracticeDescription")}
        </p>
      </div>

      {error && (
        <div className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}>
          {error}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          {t("yourName")}
        </span>
        <input
          type="text"
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-primary)", background: "transparent" }}
          value={username}
          onChange={(e) => onUsernameChange(e.target.value)}
          placeholder={t("yourNamePlaceholder")}
        />
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          {t("song")}
        </span>
        <select
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)", background: "transparent" }}
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
        >
          {songs.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title} ({s.notes} {t("songNotesSuffix")}{s.white_keys_only ? "" : t("songHasBlackKeysSuffix")})
            </option>
          ))}
        </select>
        {selected && !selected.white_keys_only && (
          <span className="text-xs" style={{ color: "var(--status-timing-off)" }}>
            {t("blackKeyWarning")}
          </span>
        )}

        <label
          className="cursor-pointer self-start rounded-lg border px-3 py-1.5 text-xs"
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
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          {t("speedLabel", { speed: speed.toFixed(2) })}
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

      <div className="flex items-center gap-3">
        <button
          className="rounded-lg border px-4 py-2 text-sm font-medium disabled:opacity-50"
          style={{ borderColor: "var(--status-correct)", color: "var(--status-correct)" }}
          disabled={!selectedId || starting}
          onClick={handleStart}
        >
          {starting ? t("starting") : t("startPractice")}
        </button>
        {hasLastResult && (
          <button
            className="rounded-lg border px-4 py-2 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            onClick={onViewLastResult}
          >
            {t("viewLastResult")}
          </button>
        )}
      </div>
    </div>
  );
}
