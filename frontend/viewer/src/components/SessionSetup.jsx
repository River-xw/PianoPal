import { useEffect, useRef, useState } from "react";

// Talks to edge/practice_server.py, running ON the Raspberry Pi -- this
// page is served BY that same server, so all API calls are same-origin
// relative paths (no host/CORS configuration needed).

export default function SessionSetup({ onStarted }) {
  const [songs, setSongs] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [speed, setSpeed] = useState(1.0);
  const [importing, setImporting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const loadSongs = () => {
    fetch("/api/songs")
      .then((res) => res.json())
      .then((data) => {
        setSongs(data.songs || []);
        setError(null);
        setSelectedId((prev) => prev || data.songs?.[0]?.id || "");
      })
      .catch(() => setError("連不上練習伺服器，確認樹莓派上的 edge/practice_server.py 有在跑"));
  };

  useEffect(loadSongs, []);

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
      if (!res.ok) throw new Error(data.error || "匯入失敗");
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
    setStarting(true);
    setError(null);
    try {
      const res = await fetch("/api/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ song_id: selectedId, speed }),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || "無法啟動");
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
          開始練習
        </h2>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          選一首歌、設定速度，開始後會在琴上點燈引導、同步錄音，結束後自動顯示評分結果。
        </p>
      </div>

      {error && (
        <div className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}>
          {error}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          曲目
        </span>
        <select
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)", background: "transparent" }}
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
        >
          {songs.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title} ({s.notes} 音{s.white_keys_only ? "" : "，含黑鍵/超出範圍"})
            </option>
          ))}
        </select>
        {selected && !selected.white_keys_only && (
          <span className="text-xs" style={{ color: "var(--status-timing-off)" }}>
            這首歌用到黑鍵或超出22白鍵範圍，燈光引導跟評分準確度會受影響。
          </span>
        )}

        <label
          className="cursor-pointer self-start rounded-lg border px-3 py-1.5 text-xs"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
        >
          {importing ? "匯入中..." : "自行匯入曲目 (MIDI)"}
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
          倍速：{speed.toFixed(2)}x
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

      <button
        className="self-start rounded-lg border px-4 py-2 text-sm font-medium disabled:opacity-50"
        style={{ borderColor: "var(--status-correct)", color: "var(--status-correct)" }}
        disabled={!selectedId || starting}
        onClick={handleStart}
      >
        {starting ? "啟動中..." : "開始練習"}
      </button>
    </div>
  );
}
