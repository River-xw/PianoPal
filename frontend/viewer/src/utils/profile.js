// Derives the "用户画像" one-line summary shown on HomePage/MyPage's recent-
// summary card, straight from the `profile` block GET /api/history already
// returns (total_sessions/recent_avg_score/most_frequent_piece) -- no
// backend model, just a few thresholds, same "compute a short sentence
// client-side" spirit as feedback.js's pattern suggestions. Plain JS (no
// React) so both pages can share it via translate() directly.

import { translate } from "../i18n";

const LEVEL_THRESHOLDS = [
  { max: 5, key: "profileLevelBeginner" },
  { max: 20, key: "profileLevelIntermediate" },
  { max: Infinity, key: "profileLevelAdvanced" },
];

export function profileLevel(totalSessions, lang) {
  const tier = LEVEL_THRESHOLDS.find((t) => totalSessions < t.max) || LEVEL_THRESHOLDS[LEVEL_THRESHOLDS.length - 1];
  return translate(tier.key, lang);
}

export function profileSummarySentence(profile, lang) {
  if (!profile || !profile.total_sessions) return translate("profileNoHistory", lang);

  const parts = [translate("profileLevelLine", lang, { level: profileLevel(profile.total_sessions, lang) })];
  if (profile.most_frequent_piece) {
    parts.push(translate("profileFavoritePiece", lang, { title: profile.most_frequent_piece.title }));
  }
  if (profile.recent_avg_score != null) {
    parts.push(translate("profileRecentAvg", lang, { score: profile.recent_avg_score.toFixed(1) }));
  }
  return parts.join(lang === "en" ? " · " : "・");
}
