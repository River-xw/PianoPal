const POSTURE_DEMOS = Object.freeze({
  finger_collapse: {
    src: "/gestures/figure_collapse.gif",
    labelKey: "postureLabelFingerCollapse",
  },
  high_lift_tap: {
    src: "/gestures/high_lift_tip.gif",
    labelKey: "postureLabelHighLiftTap",
  },
  wrist_arch: {
    src: "/gestures/wrist_arch.gif",
    labelKey: "postureLabelWristArch",
  },
  wrist_collapse: {
    src: "/gestures/wrist_collapse.gif",
    labelKey: "postureLabelWristCollapse",
  },
  wrist_shake: {
    src: "/gestures/wrist_shake.gif",
    labelKey: "postureLabelWristShake",
  },
});

function readMotionScore(summary) {
  const assessment = summary?.motion_assessment;
  const subScores = summary?.sub_scores ?? {};
  const raw =
    subScores.motion ??
    subScores.hand_shape ??
    assessment?.motion_score ??
    assessment?.hand_shape_score;
  const score = Number(raw);
  return raw == null || !Number.isFinite(score) ? null : score;
}

export function getPostureComparison(summary) {
  const assessment = summary?.motion_assessment;
  const motionScore = readMotionScore(summary);
  if (!assessment || assessment.available === false || motionScore == null || motionScore >= 80) {
    return null;
  }

  const errorEntries = Object.entries(assessment.label_counts ?? {})
    .filter(([label, count]) => label !== "normal" && POSTURE_DEMOS[label] && Number(count) > 0)
    .sort(([labelA, countA], [labelB, countB]) => Number(countB) - Number(countA) || labelA.localeCompare(labelB));

  if (errorEntries.length === 0) return null;

  const [errorLabel, errorCount] = errorEntries[0];
  return {
    motionScore,
    errorLabel,
    errorCount: Number(errorCount),
    errorSrc: POSTURE_DEMOS[errorLabel].src,
    errorLabelKey: POSTURE_DEMOS[errorLabel].labelKey,
    normalSrc: "/gestures/normal.gif",
  };
}
