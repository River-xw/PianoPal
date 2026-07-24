import { useTranslation } from "../LanguageContext.jsx";

const STATUS_LABEL_KEYS = {
  correct: "statCorrect",
  timing_off: "statTimingOff",
  wrong_pitch: "statWrongPitch",
  missed: "statMissed",
  extra: "statExtra",
};

const STATUS_VARS = {
  correct: "--status-correct",
  timing_off: "--status-timing-off",
  wrong_pitch: "--status-wrong-pitch",
  missed: "--status-missed",
  extra: "--status-extra",
};

function StatTile({ label, value }) {
  // null when the timing dimension was dropped (ScoringConfig.score_weight_timing_stability=0) --
  // not applicable rather than a real zero
  const display = value === null || value === undefined ? "N/A" : value.toFixed(1);
  return (
    <div className="flex flex-col gap-1 rounded-lg border px-4 py-3" style={{ borderColor: "var(--border)" }}>
      <span className="text-sm" style={{ color: "var(--text-muted)" }}>{label}</span>
      <span className="text-2xl font-semibold" style={{ color: "var(--text-primary)" }}>
        {display}
      </span>
    </div>
  );
}

export default function SummaryPanel({ summary }) {
  const { t } = useTranslation();
  const { score, sub_scores, global_tempo_ratio, counts } = summary;
  const harmonicExtrasRemoved = summary.harmonic_extras_removed ?? 0;
  const octaveSlips = summary.octave_slips_in_wrong_pitch ?? 0;
  const motionAssessment = summary.motion_assessment;
  const melodyAccuracy = sub_scores.melody_accuracy ?? sub_scores.pitch;
  const motionScore = sub_scores.motion ?? sub_scores.hand_shape;

  return (
    <div className="sketch-card flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-sm" style={{ color: "var(--text-muted)" }}>{t("overallScore")}</div>
          <div className="text-5xl leading-none" style={{ color: "var(--accent)", fontFamily: "var(--font-title)" }}>
            {score.toFixed(1)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {global_tempo_ratio !== null && (
            <span
              className="inline-flex items-center rounded-full border px-3 py-1 text-sm"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
            >
              {t("tempoRatio", { ratio: global_tempo_ratio.toFixed(3) })}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label={t("pitchAccuracy")} value={melodyAccuracy} />
        <StatTile label={t("handShapeScore")} value={motionScore} />
        <StatTile label={t("rhythmAccuracy")} value={sub_scores.rhythm} />
        <StatTile label={t("timingStability")} value={sub_scores.timing_stability} />
      </div>

      {motionAssessment && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {motionAssessment.available
            ? t("motionSamples", {
                total: motionAssessment.total_predictions ?? 0,
                normal: motionAssessment.normal_predictions ?? 0,
              })
            : t("motionScoreUnavailable")}
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        {Object.entries(counts)
          .filter(([status]) => STATUS_LABEL_KEYS[status])
          .map(([status, count]) => (
            <span key={status} className="inline-flex items-center gap-1.5 text-sm" style={{ color: "var(--text-secondary)" }}>
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: `var(${STATUS_VARS[status]})` }}
              />
              {t(STATUS_LABEL_KEYS[status])}: {count}
            </span>
          ))}
      </div>

      {harmonicExtrasRemoved > 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {t("harmonicExtrasRemoved", { n: harmonicExtrasRemoved, plural: harmonicExtrasRemoved === 1 ? "" : "s" })}
        </div>
      )}

      {octaveSlips > 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {t("octaveSlips", { n: octaveSlips, isAre: octaveSlips === 1 ? "is" : "are" })}
        </div>
      )}
    </div>
  );
}
