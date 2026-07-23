import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";

const POLL_MS = 500;

async function postControl(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res.json();
}

// Polls edge/practice_server.py's /api/session/status (same-origin, served
// by that same process on the Pi) while a session is guiding/recording/
// grading, and calls onDone() once phase becomes "done" so App.jsx can
// switch to the result view (which auto-loads the freshly-written
// result.json).
export default function LiveSession({ songTitle, onDone, onError }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState(null);
  const doneFired = useRef(false);

  const phaseLabel = {
    starting: t("phaseStarting"),
    guiding: t("phaseGuiding"),
    grading: t("phaseGrading"),
    done: t("phaseDone"),
    error: t("phaseError"),
  };

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch("/api/session/status");
        const data = await res.json();
        if (cancelled) return;
        setStatus(data);
        if (data.phase === "done" && !doneFired.current) {
          doneFired.current = true;
          onDone();
        }
        if (data.phase === "error") {
          onError(data.error || "unknown error");
        }
      } catch {
        // transient -- keep polling, this Pi's network has occasional blips
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [onDone, onError]);

  const phase = status?.phase || "starting";
  const progress = status?.song_end > 0 ? Math.min(1, (status.song_pos || 0) / status.song_end) : 0;

  return (
    <div className="flex flex-col gap-4 rounded-xl border px-6 py-6" style={{ borderColor: "var(--border)" }}>
      <div>
        <h2 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
          {songTitle}
        </h2>
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          {phaseLabel[phase] || phase}
        </span>
      </div>

      {phase === "guiding" && (
        <>
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {(status.song_pos || 0).toFixed(1)}s / {status.song_end.toFixed(1)}s
            {status.paused && <span style={{ color: "var(--status-timing-off)" }}> · {t("paused")}</span>}
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--border)" }}>
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${progress * 100}%`, background: "var(--status-correct)" }}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
              onClick={() => postControl("/api/session/control", { action: "speed_delta", value: -0.1 })}
            >
              {t("slower")}
            </button>
            <span className="min-w-[3.5rem] text-center text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              {(status.speed || 1).toFixed(1)}x
            </span>
            <button
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
              onClick={() => postControl("/api/session/control", { action: "speed_delta", value: 0.1 })}
            >
              {t("faster")}
            </button>
            <button
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
              onClick={() => postControl("/api/session/control", { action: "pause_toggle" })}
            >
              {status.paused ? t("resume") : t("pause")}
            </button>
            <button
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
              onClick={() => postControl("/api/session/control", { action: "restart" })}
            >
              {t("restart")}
            </button>
            <button
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={{ borderColor: "var(--status-wrong-pitch)", color: "var(--status-wrong-pitch)" }}
              onClick={() => postControl("/api/session/stop", {})}
            >
              {t("endEarly")}
            </button>
          </div>
        </>
      )}

      {phase === "grading" && (
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          {t("gradingMessage")}
        </span>
      )}
    </div>
  );
}
