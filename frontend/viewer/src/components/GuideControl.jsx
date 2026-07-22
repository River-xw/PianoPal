import { useEffect, useRef, useState } from "react";

// Talks to edge/ws2812_guide_song.py's --http-port control server on the
// Raspberry Pi (GET /status, POST /control) -- see that file's docstring for
// the wire format. This panel is independent of the result.json viewer above:
// it controls the LIVE LED guidance running on the Pi, not a past recording.
const POLL_MS = 500;
const STORAGE_KEY = "pianopal_guide_host";

async function postControl(host, action, value) {
  const res = await fetch(`http://${host}/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value === undefined ? { action } : { action, value }),
  });
  if (!res.ok) throw new Error(`control request failed (${res.status})`);
  return res.json();
}

export default function GuideControl() {
  const [host, setHost] = useState(() => localStorage.getItem(STORAGE_KEY) || "192.168.137.87:8765");
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, host);
  }, [host]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(`http://${host}/status`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (!cancelled) {
          setStatus(data);
          setConnected(true);
        }
      } catch {
        if (!cancelled) setConnected(false);
      }
    };
    poll();
    pollRef.current = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(pollRef.current);
    };
  }, [host]);

  const send = (action, value) => postControl(host, action, value).catch(() => setConnected(false));

  const progress = status && status.song_end > 0 ? Math.min(1, status.song_pos / status.song_end) : 0;

  return (
    <div className="flex flex-col gap-3 rounded-lg border px-4 py-3" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          LED Guide Control
        </span>
        <span
          className="flex items-center gap-1.5 text-xs"
          style={{ color: connected ? "var(--status-correct)" : "var(--status-missed)" }}
        >
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: connected ? "var(--status-correct)" : "var(--status-missed)" }}
          />
          {connected ? "connected" : "not connected"}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          Pi host:port
        </span>
        <input
          className="flex-1 rounded border px-2 py-1 text-xs"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)", background: "transparent" }}
          value={host}
          onChange={(e) => setHost(e.target.value.trim())}
          placeholder="192.168.137.87:8765"
        />
      </div>

      {status && (
        <>
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {status.title} &middot; {status.song_pos.toFixed(1)}s / {status.song_end.toFixed(1)}s
            {status.paused && <span style={{ color: "var(--status-timing-off)" }}> &middot; paused</span>}
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--border)" }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${progress * 100}%`, background: "var(--status-correct)" }}
            />
          </div>
        </>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          className="rounded-lg border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          onClick={() => send("speed_delta", -0.1)}
        >
          − Slower
        </button>
        <span className="min-w-[3.5rem] text-center text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          {status ? `${status.speed.toFixed(1)}x` : "--"}
        </span>
        <button
          className="rounded-lg border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          onClick={() => send("speed_delta", 0.1)}
        >
          + Faster
        </button>
        <button
          className="rounded-lg border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          onClick={() => send("pause_toggle")}
        >
          {status?.paused ? "Resume" : "Pause"}
        </button>
        <button
          className="rounded-lg border px-3 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          onClick={() => send("restart")}
        >
          Restart
        </button>
      </div>
    </div>
  );
}
