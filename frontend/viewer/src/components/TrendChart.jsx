import { useMemo, useState } from "react";
import { useTranslation } from "../LanguageContext.jsx";

const HEIGHT = 160;
const MARGIN = { top: 10, right: 16, bottom: 24, left: 32 };
const PX_PER_POINT = 36;
const MIN_WIDTH = 400;

// Score trend across this user's completed sessions -- hand-rolled SVG
// (same style as TimingStrip.jsx/PianoRoll.jsx, no chart library). A single
// series on a fixed 0-100 axis needs no legend/second hue; the accent color
// introduced for the onboarding page doubles as this chart's one color.
export default function TrendChart({ sessions }) {
  const { t } = useTranslation();
  const [hovered, setHovered] = useState(null);

  // `sessions` is newest-first (as returned by GET /api/history); the chart
  // reads left-to-right chronologically, so reverse it.
  const points = useMemo(
    () =>
      sessions
        .filter((s) => s.status === "completed" && s.score != null)
        .slice()
        .reverse()
        .map((s, seq) => ({ session: s, seq })),
    [sessions]
  );

  if (points.length < 2) return null;

  const width = Math.max(MIN_WIDTH, MARGIN.left + MARGIN.right + points.length * PX_PER_POINT);
  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;

  const xForSeq = (seq) => MARGIN.left + (points.length <= 1 ? plotW / 2 : (seq / (points.length - 1)) * plotW);
  const yForScore = (v) => MARGIN.top + plotH - (v / 100) * plotH;

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      <div className="mb-2 text-sm font-medium" style={{ color: "var(--text-primary)" }}>
        {t("trendChartTitle")}
      </div>
      <div className="relative overflow-x-auto">
        <svg width={width} height={HEIGHT} style={{ display: "block" }}>
          <line x1={MARGIN.left} x2={width - MARGIN.right} y1={yForScore(0)} y2={yForScore(0)} stroke="var(--axis)" strokeWidth={1} />
          <text x={2} y={yForScore(0) + 4} fontSize={10} fill="var(--text-muted)">0</text>
          <text x={2} y={yForScore(100) + 4} fontSize={10} fill="var(--text-muted)">100</text>

          <polyline
            fill="none"
            stroke="var(--accent)"
            strokeWidth={2}
            points={points.map((p) => `${xForSeq(p.seq)},${yForScore(p.session.score)}`).join(" ")}
          />

          {points.map((p) => (
            <circle
              key={p.session.id}
              cx={xForSeq(p.seq)}
              cy={yForScore(p.session.score)}
              r={hovered === p.session.id ? 5 : 3.5}
              fill="var(--accent)"
              stroke="var(--surface)"
              strokeWidth={1.5}
              style={{ cursor: "pointer" }}
              onMouseEnter={() => setHovered(p.session.id)}
              onMouseLeave={() => setHovered((h) => (h === p.session.id ? null : h))}
            />
          ))}
        </svg>

        {hovered !== null && (() => {
          const p = points.find((pt) => pt.session.id === hovered);
          if (!p) return null;
          return (
            <div
              className="pointer-events-none absolute left-3 top-1 rounded-lg border px-3 py-2 text-xs shadow-lg"
              style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--text-primary)" }}
            >
              <div className="font-medium">{p.session.piece_title}</div>
              <div style={{ color: "var(--text-secondary)" }}>
                {new Date(p.session.started_at).toLocaleDateString()} · {p.session.score.toFixed(1)}
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
