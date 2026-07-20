const STATUS_LABELS = {
  correct: "Correct",
  timing_off: "Timing off",
  wrong_pitch: "Wrong pitch",
  missed: "Missed",
  extra: "Extra",
};

const STATUS_VARS = {
  correct: "--status-correct",
  timing_off: "--status-timing-off",
  wrong_pitch: "--status-wrong-pitch",
  missed: "--status-missed",
  extra: "--status-extra",
};

function StatTile({ label, value }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border px-4 py-3" style={{ borderColor: "var(--border)" }}>
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>{label}</span>
      <span className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
        {value.toFixed(1)}
      </span>
    </div>
  );
}

function TempoTrendChip({ trend }) {
  const arrow = trend === "accelerating" ? "↗" : trend === "decelerating" ? "↘" : "→";
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm"
      style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
    >
      {arrow} {trend}
    </span>
  );
}

export default function SummaryPanel({ summary }) {
  const { score, sub_scores, global_tempo_ratio, tempo_trend, counts } = summary;
  const harmonicExtrasRemoved = summary.harmonic_extras_removed ?? 0;

  return (
    <div className="flex flex-col gap-4 rounded-xl border p-6" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>Overall score</div>
          <div className="text-5xl font-semibold leading-none" style={{ color: "var(--text-primary)" }}>
            {score.toFixed(1)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {global_tempo_ratio !== null && (
            <span
              className="inline-flex items-center rounded-full border px-3 py-1 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            >
              tempo ratio {global_tempo_ratio.toFixed(3)}
            </span>
          )}
          <TempoTrendChip trend={tempo_trend} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <StatTile label="Pitch accuracy" value={sub_scores.pitch} />
        <StatTile label="Rhythm accuracy" value={sub_scores.rhythm} />
        <StatTile label="Timing stability" value={sub_scores.timing_stability} />
      </div>

      <div className="flex flex-wrap gap-3">
        {Object.entries(counts)
          .filter(([status]) => STATUS_LABELS[status])
          .map(([status, count]) => (
            <span key={status} className="inline-flex items-center gap-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: `var(${STATUS_VARS[status]})` }}
              />
              {STATUS_LABELS[status]}: {count}
            </span>
          ))}
      </div>

      {harmonicExtrasRemoved > 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {harmonicExtrasRemoved} harmonic-overtone artifact{harmonicExtrasRemoved === 1 ? "" : "s"} filtered
          out before scoring (spurious octave-up notes coinciding with a real note).
        </div>
      )}

      {(summary.octave_slips_in_wrong_pitch ?? 0) > 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {summary.octave_slips_in_wrong_pitch} of the wrong-pitch notes {summary.octave_slips_in_wrong_pitch === 1 ? "is" : "are"} an
          exact octave slip — on audio input this usually means a transcription octave error rather than a finger 12 keys away.
        </div>
      )}
    </div>
  );
}
