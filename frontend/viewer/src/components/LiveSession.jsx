import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";
import { Metronome } from "../utils/metronome";
import NotationView from "./NotationView.jsx";

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
// result.json) -- or, for 分段循環練習 sessions, straight back to setup since
// there's no result to show (App.jsx decides which, via liveInfo.practiceOnly;
// this component's own rendering doesn't need to know).
export default function LiveSession({ mode, songId, songTitle, onDone, onError }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState(null);
  const [referenceNotes, setReferenceNotes] = useState([]);
  const [muted, setMuted] = useState(false);
  const doneFired = useRef(false);
  const metronomeRef = useRef(null);
  if (!metronomeRef.current) metronomeRef.current = new Metronome();

  // Learn-mode metronome: use browser Web Audio only when the Pi did not
  // advertise its own ALSA output. With PIANOPAL_PLAYBACK_DEVICE configured,
  // the guide process owns the clicks and this browser remains control-only.
  useEffect(() => {
    const metronome = metronomeRef.current;
    if (
      mode === "perform"
      || status?.phase !== "guiding"
      || !status?.tempo_bpm
      || status?.metronome_output === "pi"
    ) {
      metronome.stop();
      return;
    }
    metronome.start(status.tempo_bpm * (status.speed || 1));
    metronome.setBpm(status.tempo_bpm * (status.speed || 1));
    metronome.setPaused(!!status.paused);
    metronome.setMuted(muted);
  }, [
    mode,
    status?.phase,
    status?.tempo_bpm,
    status?.speed,
    status?.paused,
    status?.metronome_output,
    muted,
  ]);

  useEffect(() => {
    if (
      status?.metronome_output === "pi"
      && typeof status?.metronome_muted === "boolean"
    ) {
      setMuted(status.metronome_muted);
    }
  }, [status?.metronome_output, status?.metronome_muted]);

  useEffect(() => () => metronomeRef.current.stop(), []);

  useEffect(() => {
    if (!songId) return;
    let cancelled = false;
    fetch(`/api/songs/${encodeURIComponent(songId)}/reference`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled) setReferenceNotes(data?.notes || []);
      })
      .catch(() => {
        if (!cancelled) setReferenceNotes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [songId]);

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
  const capture = status?.capture;
  const currentMeasure = useMemo(() => {
    if (referenceNotes.length === 0) return null;
    const songPos = status?.song_pos || 0;
    let measure = referenceNotes[0].measure || 1;
    for (const note of referenceNotes) {
      if ((note.onset_ref_sec || 0) > songPos) break;
      measure = note.measure || measure;
    }
    return measure;
  }, [referenceNotes, status?.song_pos]);
  const motionStatusLabel = {
    running: t("motionRecognizing"),
    finished: t("motionFinished"),
    unavailable: t("motionUnavailable"),
  };

  return (
    <div className="sketch-card flex flex-col gap-4 px-6 py-6">
      <div>
        <h2 className="text-2xl" style={{ color: "var(--text-primary)" }}>
          {songTitle}
        </h2>
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>
          {phaseLabel[phase] || phase}
        </span>
      </div>

      {phase === "guiding" && (
        <>
          {mode === "perform" && (
            <div className="text-sm" style={{ color: "var(--status-timing-off)" }}>{t("noGuideNotice")}</div>
          )}
          {referenceNotes.length > 0 && currentMeasure != null && (
            <NotationView
              notes={referenceNotes}
              preview
              highlightRange={{ start: currentMeasure, end: currentMeasure }}
              followMeasure={currentMeasure}
              titleKey="liveNotationTitle"
            />
          )}
          <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {(status.song_pos || 0).toFixed(1)}s / {status.song_end.toFixed(1)}s
            {status.paused && <span style={{ color: "var(--status-timing-off)" }}> · {t("paused")}</span>}
          </div>
          {capture && (
            <div className="flex flex-wrap gap-2 text-xs">
              <span
                className="rounded-full border px-3 py-1"
                style={{
                  borderColor: capture.audio_recording ? "var(--status-correct)" : "var(--border)",
                  color: capture.audio_recording ? "var(--status-correct)" : "var(--text-muted)",
                }}
              >
                {capture.audio_recording ? t("microphoneRecording") : t("microphoneStarting")}
              </span>
              <span
                className="rounded-full border px-3 py-1"
                style={{
                  borderColor: capture.motion_recognition === "running" ? "var(--status-correct)" : "var(--border)",
                  color: capture.motion_recognition === "unavailable" ? "var(--text-muted)" : "var(--status-correct)",
                }}
              >
                {motionStatusLabel[capture.motion_recognition] || t("motionUnavailable")}
              </span>
            </div>
          )}
          <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--border)" }}>
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${progress * 100}%`, background: "var(--status-correct)" }}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {mode !== "perform" && (
              <>
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
                  onClick={() => {
                    metronomeRef.current.reset();
                    postControl("/api/session/control", { action: "restart" });
                  }}
                >
                  {t("restart")}
                </button>
                {status.tempo_bpm && (
                  <button
                    className="rounded-lg border px-3 py-1.5 text-sm"
                    style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                    onClick={() => setMuted((current) => {
                      const next = !current;
                      postControl("/api/session/control", {
                        action: "metronome_mute_set",
                        value: next,
                      });
                      return next;
                    })}
                  >
                    {muted ? t("metronomeUnmute") : t("metronomeMute")}
                  </button>
                )}
              </>
            )}
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
