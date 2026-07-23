import { useMemo, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";

const HEIGHT = 160;
const MARGIN = { top: 10, right: 16, bottom: 24, left: 44 };
const PX_PER_POINT = 4;
const MIN_WIDTH = 900;

const STATUS_VAR = {
  correct: "--status-correct",
  timing_off: "--status-timing-off",
  wrong_pitch: "--status-wrong-pitch",
};

const TIMING_LABEL_KEYS = {
  accurate: "timingAccurate",
  rush: "timingRush",
  drag: "timingDrag",
};

export default function TimingStrip({ notes }) {
  const { t } = useTranslation();
  const [hovered, setHovered] = useState(null);

  // `seq` is this point's position *within the filtered list* -- the x-axis
  // is "note index" among notes that actually have timing data, not the
  // note's position in the raw (unfiltered) notes array.
  const points = useMemo(
    () =>
      notes
        .map((n, originalIndex) => ({ note: n, originalIndex, offset: n.offset_ms }))
        .filter((p) => p.offset != null)
        .map((p, seq) => ({ ...p, seq })),
    [notes]
  );

  const width = Math.max(MIN_WIDTH, MARGIN.left + MARGIN.right + points.length * PX_PER_POINT);
  const maxAbsOffset = Math.max(10, ...points.map((p) => Math.abs(p.offset)));
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;

  const xForSeq = (seq) => MARGIN.left + (points.length <= 1 ? plotW / 2 : (seq / (points.length - 1)) * plotW);
  const yForOffset = (v) => MARGIN.top + plotH / 2 - (v / maxAbsOffset) * (plotH / 2);

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      <div className="mb-2 text-sm font-medium" style={{ color: "var(--text-primary)" }}>
        {t("timingStripTitle")}
      </div>
      <div className="relative overflow-x-auto">
        <svg width={width} height={HEIGHT} style={{ display: "block" }}>
          <line x1={MARGIN.left} x2={width - MARGIN.right} y1={yForOffset(0)} y2={yForOffset(0)} stroke="var(--axis)" strokeWidth={1} />
          <text x={4} y={yForOffset(0) + 4} fontSize={10} fill="var(--text-muted)">0ms</text>
          <text x={4} y={MARGIN.top + 8} fontSize={10} fill="var(--text-muted)">+{Math.round(maxAbsOffset)}</text>
          <text x={4} y={HEIGHT - MARGIN.bottom} fontSize={10} fill="var(--text-muted)">-{Math.round(maxAbsOffset)}</text>

          {points.length > 1 && (
            <polyline
              fill="none"
              stroke="var(--text-muted)"
              strokeWidth={1}
              opacity={0.4}
              points={points.map((p) => `${xForSeq(p.seq)},${yForOffset(p.offset)}`).join(" ")}
            />
          )}

          {points.map((p) => (
            <circle
              key={p.originalIndex}
              cx={xForSeq(p.seq)}
              cy={yForOffset(p.offset)}
              r={hovered === p.originalIndex ? 5 : 3.5}
              fill={`var(${STATUS_VAR[p.note.status] ?? "--status-correct"})`}
              stroke="var(--surface)"
              strokeWidth={1.5}
              style={{ cursor: "pointer" }}
              onMouseEnter={() => setHovered(p.originalIndex)}
              onMouseLeave={() => setHovered((h) => (h === p.originalIndex ? null : h))}
            />
          ))}
        </svg>

        {hovered !== null && (() => {
          const p = points.find((pt) => pt.originalIndex === hovered);
          if (!p) return null;
          return (
            <div
              className="pointer-events-none absolute left-3 top-1 rounded-lg border px-3 py-2 text-xs shadow-lg"
              style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text-primary)" }}
            >
              <div className="font-medium">{p.note.name ?? "?"}</div>
              <div style={{ color: "var(--text-secondary)" }}>
                {t("tooltipOffset", { ms: p.offset.toFixed(1), timing: t(TIMING_LABEL_KEYS[p.note.timing] ?? p.note.timing) })}
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
