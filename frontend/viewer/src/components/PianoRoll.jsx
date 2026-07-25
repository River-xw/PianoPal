import { useMemo, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";

const PX_PER_SEC = 90;
const PX_PER_SEMITONE = 9;
const MARK_WIDTH = 16;
const MARGIN = { top: 24, right: 40, bottom: 32, left: 48 };

const STATUS_VAR = {
  correct: "--status-correct",
  timing_off: "--status-timing-off",
  wrong_pitch: "--status-wrong-pitch",
  missed: "--status-missed",
  extra: "--status-extra",
};

const STATUS_LABEL_KEYS = {
  correct: "statusLabelCorrect",
  timing_off: "statusLabelTimingOff",
  wrong_pitch: "statusLabelWrongPitch",
  missed: "statusLabelMissed",
  extra: "statusLabelExtra",
};

const TIMING_LABEL_KEYS = {
  accurate: "timingAccurate",
  rush: "timingRush",
  drag: "timingDrag",
};

function noteTime(note) {
  // the position to draw a note's primary mark at
  if (note.status === "timing_off") return note.onset_perf_sec;
  if (note.status === "extra") return note.onset_perf_sec;
  return note.onset_ref_sec;
}

function notePitch(note) {
  if (note.status === "wrong_pitch" || note.status === "extra") return note.pitch_perf;
  return note.pitch_ref;
}

export default function PianoRoll({ notes }) {
  const { t } = useTranslation();
  const [hovered, setHovered] = useState(null);

  const { minPitch, maxPitch, maxTime, measureMarks } = useMemo(() => {
    let minP = Infinity, maxP = -Infinity, maxT = 0;
    const measureAtTime = new Map();
    for (const n of notes) {
      const p = notePitch(n);
      const t = noteTime(n);
      if (p != null) {
        minP = Math.min(minP, p);
        maxP = Math.max(maxP, p);
      }
      if (t != null) maxT = Math.max(maxT, t);
      if (n.measure != null && n.onset_ref_sec != null) {
        const existing = measureAtTime.get(n.measure);
        if (existing === undefined || n.onset_ref_sec < existing) {
          measureAtTime.set(n.measure, n.onset_ref_sec);
        }
      }
    }
    if (!Number.isFinite(minP)) { minP = 60; maxP = 72; }
    const marks = [...measureAtTime.entries()].sort((a, b) => a[1] - b[1]);
    return { minPitch: minP - 2, maxPitch: maxP + 2, maxTime: maxT, measureMarks: marks };
  }, [notes]);

  const width = maxTime * PX_PER_SEC + MARGIN.left + MARGIN.right + 60;
  const height = (maxPitch - minPitch) * PX_PER_SEMITONE + MARGIN.top + MARGIN.bottom;

  const xForTime = (t) => MARGIN.left + t * PX_PER_SEC;
  const yForPitch = (p) => MARGIN.top + (maxPitch - p) * PX_PER_SEMITONE;

  return (
    <div className="sketch-card">
      <div className="flex flex-wrap items-center gap-4 border-b px-4 py-3 text-sm" style={{ borderColor: "var(--border)" }}>
        <span className="panel-heading mr-2">{t("pianoRollTitle")}</span>
        {Object.entries(STATUS_VAR).map(([status, cssVar]) => (
          <span key={status} className="inline-flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: `var(${cssVar})` }} />
            {t(STATUS_LABEL_KEYS[status])}
          </span>
        ))}
      </div>

      <div className="relative overflow-x-auto" style={{ maxHeight: 520 }}>
        <svg width={width} height={height} style={{ display: "block" }}>
          {/* measure gridlines */}
          {measureMarks.map(([measure, t]) => (
            <g key={`measure-${measure}`}>
              <line
                x1={xForTime(t)} x2={xForTime(t)} y1={MARGIN.top} y2={height - MARGIN.bottom}
                stroke="var(--gridline)" strokeWidth={1}
              />
              <text x={xForTime(t) + 3} y={14} fontSize={11} fill="var(--text-muted)">
                {measure}
              </text>
            </g>
          ))}

          {notes.map((n, i) => {
            const t = noteTime(n);
            const p = notePitch(n);
            if (t == null || p == null) return null;
            const x = xForTime(t);
            const y = yForPitch(p);
            const key = `note-${i}`;
            const isHovered = hovered === i;

            const commonProps = {
              onMouseEnter: () => setHovered(i),
              onMouseLeave: () => setHovered((h) => (h === i ? null : h)),
              style: { cursor: "pointer" },
            };

            if (n.status === "missed") {
              return (
                <rect
                  key={key}
                  {...commonProps}
                  x={x - MARK_WIDTH / 2} y={y - 4} width={MARK_WIDTH} height={8} rx={4}
                  fill="none" stroke="var(--status-missed)" strokeWidth={1.5} strokeDasharray="3 2"
                  opacity={isHovered ? 1 : 0.85}
                />
              );
            }

            if (n.status === "extra") {
              const size = 9;
              return (
                <rect
                  key={key}
                  {...commonProps}
                  x={x - size / 2} y={y - size / 2} width={size} height={size}
                  transform={`rotate(45 ${x} ${y})`}
                  fill="var(--status-extra)" opacity={isHovered ? 1 : 0.9}
                />
              );
            }

            if (n.status === "wrong_pitch") {
              const yExpected = yForPitch(n.pitch_ref);
              return (
                <g key={key}>
                  <line
                    x1={x} x2={x} y1={y} y2={yExpected}
                    stroke="var(--status-wrong-pitch)" strokeWidth={1} strokeDasharray="2 2" opacity={0.6}
                  />
                  <rect
                    x={x - MARK_WIDTH / 2} y={yExpected - 4} width={MARK_WIDTH} height={8} rx={4}
                    fill="none" stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="2 2" opacity={0.5}
                  />
                  <rect
                    onMouseEnter={() => setHovered(i)}
                    onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
                    style={{ cursor: "pointer" }}
                    x={x - MARK_WIDTH / 2} y={y - 4} width={MARK_WIDTH} height={8} rx={4}
                    fill="var(--status-wrong-pitch)" opacity={isHovered ? 1 : 0.9}
                  />
                </g>
              );
            }

            // correct / timing_off
            const color = n.status === "correct" ? "var(--status-correct)" : "var(--status-timing-off)";
            return (
              <g key={key}>
                <rect
                  {...commonProps}
                  x={x - MARK_WIDTH / 2} y={y - 4} width={MARK_WIDTH} height={8} rx={4}
                  fill={color} opacity={isHovered ? 1 : 0.9}
                />
                {n.status === "timing_off" && (
                  <text
                    x={x} y={y - 8} fontSize={10} textAnchor="middle" fill="var(--text-secondary)"
                  >
                    {n.offset_ms < 0 ? "←" : "→"} {Math.abs(Math.round(n.offset_ms))}ms
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {hovered !== null && (
          <NoteTooltip note={notes[hovered]} />
        )}
      </div>
    </div>
  );
}

function NoteTooltip({ note }) {
  const { t } = useTranslation();
  return (
    <div
      className="pointer-events-none absolute left-3 top-3 rounded-lg border px-3 py-2 text-xs shadow-lg"
      style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text-primary)" }}
    >
      <div className="font-medium">{note.name ?? "?"} — {t(STATUS_LABEL_KEYS[note.status] ?? "statusLabelCorrect")}</div>
      {note.pitch_ref != null && (
        <div style={{ color: "var(--text-secondary)" }}>
          {t("tooltipExpectedPitch", { pitch: note.pitch_ref, time: note.onset_ref_sec?.toFixed(3) })}
        </div>
      )}
      {note.pitch_perf != null && (
        <div style={{ color: "var(--text-secondary)" }}>
          {t("tooltipPlayedPitch", { pitch: note.pitch_perf, time: note.onset_perf_sec?.toFixed(3) })}
        </div>
      )}
      {note.offset_ms != null && (
        <div style={{ color: "var(--text-secondary)" }}>
          {t("tooltipOffset", { ms: note.offset_ms.toFixed(1), timing: t(TIMING_LABEL_KEYS[note.timing] ?? note.timing) })}
        </div>
      )}
      {note.measure != null && (
        <div style={{ color: "var(--text-muted)" }}>
          {t("tooltipMeasure", { measure: note.measure, hand: note.hand ? t("tooltipHandSuffix", { hand: note.hand }) : "" })}
        </div>
      )}
    </div>
  );
}
