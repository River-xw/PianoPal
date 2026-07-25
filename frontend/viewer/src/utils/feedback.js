// Generates the "評語"/feedback panel: a short overall line plus a handful
// of PATTERN-based practice suggestions -- not a per-measure echo of what
// the piano roll/notation views already show (that would just be restating
// colored dots as text). Each detector below asks "is there a single
// dominant, actionable pattern here worth calling out", and stays silent
// (returns null) when the evidence is too thin or too spread out to name one
// confidently -- a wrong guess at a nonexistent pattern is worse than saying
// nothing. Entirely client-side, computed straight from result.json.
//
// Bilingual: every generated sentence goes through translate() from ../i18n
// (the same plain-JS dictionary the React components use via
// LanguageContext), parameterized with {vars} -- this module has no React
// context of its own, so `lang` is passed in explicitly by the caller
// (FeedbackPanel.jsx, which reads it from useTranslation()).

import { translate } from "../i18n";

function inferMeasure(notes) {
  let last = 1;
  return notes.map((n) => {
    if (n.measure != null) {
      last = n.measure;
      return n;
    }
    return { ...n, measure: last };
  });
}

function measureRangeLabel(start, end, lang) {
  return start === end
    ? translate("measureRangeSingle", lang, { start })
    : translate("measureRangeMulti", lang, { start, end });
}

function overallLine(summary, lang) {
  const { global_tempo_ratio, counts } = summary;
  const parts = [];

  if (global_tempo_ratio != null) {
    const pct = Math.round((global_tempo_ratio - 1) * 100);
    if (Math.abs(pct) >= 2) {
      parts.push(translate(pct > 0 ? "tempoSlowerBy" : "tempoFasterBy", lang, { pct: Math.abs(pct) }));
    } else {
      parts.push(translate("tempoCloseToReference", lang));
    }
  }

  // A single accelerating/decelerating label for the WHOLE piece can't tell
  // "rushed throughout" from "rushed the first few bars, steady after" --
  // exactly the distinction a real lesson needs. That's now handled by
  // chunkTempoTrend()/detectTempoAdvice() below (localized, per measure-
  // range); this line sticks to the one honest global-average statement.

  const totalProblems = counts.timing_off + counts.wrong_pitch + counts.missed + counts.extra;
  if (totalProblems === 0) {
    parts.push(translate("noErrorsDetected", lang));
  }

  if (!parts.length) return null;
  return lang === "en" ? parts.join(", ") + "." : parts.join("，") + "。";
}

function motionFeedback(summary, lang) {
  const assessment = summary.motion_assessment;
  const subScores = summary.sub_scores ?? {};
  const rawScore =
    subScores.motion ??
    subScores.hand_shape ??
    assessment?.motion_score ??
    assessment?.hand_shape_score;

  if (assessment?.available === false || rawScore == null || !Number.isFinite(Number(rawScore))) {
    return translate("motionFeedbackUnavailable", lang);
  }

  const score = Number(rawScore);
  const key =
    score >= 85
      ? "motionFeedbackExcellent"
      : score >= 60
        ? "motionFeedbackGood"
        : "motionFeedbackNeedsWork";
  return translate(key, lang, { score: score.toFixed(1) });
}

// --- pattern detectors: each returns a suggestion string, or null if the
// pattern isn't clear/strong enough to call out confidently ---

// Chords (2+ reference notes sharing an onset) where one member consistently
// comes through and the other doesn't -- grouped by pitch position within
// the chord (lower vs higher), not by the "hand" field, since this
// reference's hand-tagging isn't reliable for single-track-MIDI songs (every
// note can end up tagged the same hand regardless of pitch).
function detectChordCompleteness(notes, lang) {
  const groups = new Map();
  for (const n of notes) {
    if (n.onset_ref_sec == null || n.pitch_ref == null) continue;
    const key = Math.round(n.onset_ref_sec * 20); // ~50ms bucket
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(n);
  }

  let chordGroups = 0;
  let partialFailures = 0;
  let lowerFailures = 0;
  let higherFailures = 0;
  for (const g of groups.values()) {
    if (g.length < 2) continue;
    chordGroups++;
    const bad = g.filter((n) => n.status === "missed" || n.status === "wrong_pitch");
    const ok = g.filter((n) => n.status === "correct" || n.status === "timing_off");
    if (bad.length === 0 || ok.length === 0) continue;
    partialFailures++;
    const byPitch = [...g].sort((a, b) => a.pitch_ref - b.pitch_ref);
    if (bad.includes(byPitch[0])) lowerFailures++;
    if (bad.includes(byPitch[byPitch.length - 1])) higherFailures++;
  }

  if (chordGroups < 4 || partialFailures < 3 || partialFailures / chordGroups < 0.25) return null;
  const skew = Math.abs(lowerFailures - higherFailures) / partialFailures;
  if (skew < 0.3) return null; // no clear voice-specific pattern, just scattered chord misses

  const voice = translate(lowerFailures > higherFailures ? "chordVoiceLower" : "chordVoiceHigher", lang);
  return translate("chordCompletenessTip", lang, { voice });
}

// A single pitch responsible for a disproportionate share of the wrong/
// missed notes -- points at a specific finger/key to double-check, rather
// than a vague "practice more".
function detectPitchHotspot(problemNotes, lang) {
  const named = problemNotes.filter((n) => n.name);
  if (named.length < 4) return null;

  const counts = new Map();
  for (const n of named) counts.set(n.name, (counts.get(n.name) ?? 0) + 1);
  const [topName, topCount] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
  if (topCount < 3 || topCount / named.length < 0.3) return null;

  return translate("pitchHotspotTip", lang, { name: topName, count: topCount });
}

// The single measure (or pair of adjacent measures) responsible for a large
// share of all problems -- names WHERE to drill, not just that a problem
// exists there (the piano roll already shows that).
function detectSectionConcentration(problemNotes, lang) {
  if (problemNotes.length < 4) return null;

  const byMeasure = new Map();
  for (const n of problemNotes) {
    if (n.measure == null) continue;
    byMeasure.set(n.measure, (byMeasure.get(n.measure) ?? 0) + 1);
  }
  const sorted = [...byMeasure.entries()].sort((a, b) => b[1] - a[1]);
  if (sorted.length === 0) return null;

  let [start, count] = sorted[0];
  let end = start;
  const runnerUp = sorted[1];
  if (runnerUp && Math.abs(runnerUp[0] - start) === 1 && runnerUp[1] >= count * 0.6) {
    start = Math.min(start, runnerUp[0]);
    end = Math.max(end, runnerUp[0]);
    count += runnerUp[1];
  }

  const share = count / problemNotes.length;
  if (share < 0.3 || count < 3) return null;

  return translate("sectionConcentrationTip", lang, {
    pct: Math.round(share * 100),
    label: measureRangeLabel(start, end, lang),
  });
}

// How far (ms) a CHUNK's average offset must be from zero to count as a real
// directional bias rather than noise. Looser than the per-note correct/
// timing_off tolerance on purpose: a single note within tolerance can still
// be part of a genuine sustained few-dozen-ms rush/drag that only shows up
// once averaged over several notes.
const TEMPO_CHUNK_BIAS_THRESHOLD_MS = 50;

function chunkTempoTrend(notes) {
  const timed = notes
    .filter((n) => n.offset_ms != null)
    .sort((a, b) => (a.ref_index ?? 0) - (b.ref_index ?? 0));
  if (timed.length < 6) return [];

  // Roughly 6 chunks regardless of piece length, so short and long pieces
  // get comparably granular localization instead of a fixed note count.
  const chunkSize = Math.max(4, Math.round(timed.length / 6));
  const chunks = [];
  for (let i = 0; i < timed.length; i += chunkSize) {
    const slice = timed.slice(i, i + chunkSize);
    const avg = slice.reduce((a, n) => a + n.offset_ms, 0) / slice.length;
    const measures = slice.map((n) => n.measure).filter((m) => m != null);
    chunks.push({
      avg,
      direction: avg <= -TEMPO_CHUNK_BIAS_THRESHOLD_MS ? "rush" : avg >= TEMPO_CHUNK_BIAS_THRESHOLD_MS ? "drag" : "steady",
      measureStart: measures.length ? Math.min(...measures) : null,
      measureEnd: measures.length ? Math.max(...measures) : null,
      count: slice.length,
    });
  }

  // Merge adjacent chunks that share a direction into one range, dropping
  // "steady" stretches -- only report where a real rush/drag holds up.
  const ranges = [];
  for (const c of chunks) {
    if (c.direction === "steady") continue;
    const last = ranges[ranges.length - 1];
    if (last && last.direction === c.direction && last.measureEnd != null && c.measureStart != null && c.measureStart - last.measureEnd <= 1) {
      last.measureEnd = c.measureEnd ?? last.measureEnd;
      last.totalOffset += c.avg * c.count;
      last.count += c.count;
    } else {
      ranges.push({ direction: c.direction, measureStart: c.measureStart, measureEnd: c.measureEnd, totalOffset: c.avg * c.count, count: c.count });
    }
  }
  return ranges;
}

// Localized rush/drag: prioritizes calling out an early rush specifically
// (a very common, very fixable pattern -- "count yourself in"), otherwise
// names whichever range has the strongest bias.
function detectTempoAdvice(tempoRanges, firstMeasure, lang) {
  if (tempoRanges.length === 0) return null;

  const earlyRush = tempoRanges.find(
    (r) => r.direction === "rush" && r.measureStart != null && firstMeasure != null && r.measureStart <= firstMeasure + 1
  );
  if (earlyRush) {
    return translate("tempoEarlyRushTip", lang);
  }

  const worst = [...tempoRanges].sort((a, b) => Math.abs(b.totalOffset / b.count) - Math.abs(a.totalOffset / a.count))[0];
  const verb = translate(worst.direction === "rush" ? "tempoVerbRush" : "tempoVerbDrag", lang);
  const label = worst.measureStart == null ? "" : measureRangeLabel(worst.measureStart, worst.measureEnd, lang);
  return translate("tempoRangeTip", lang, { label, verb });
}

export function generateFeedback(notes, summary, lang) {
  const inferred = inferMeasure(notes);
  const problemNotes = inferred.filter((n) => n.status !== "correct");
  const measures = inferred.map((n) => n.measure).filter((m) => m != null);
  const firstMeasure = measures.length ? Math.min(...measures) : null;

  const suggestions = [];

  const chordTip = detectChordCompleteness(inferred, lang);
  if (chordTip) suggestions.push({ key: "tip-chord", status: "missed", text: chordTip });

  const pitchTip = detectPitchHotspot(problemNotes, lang);
  if (pitchTip) suggestions.push({ key: "tip-pitch", status: "wrong_pitch", text: pitchTip });

  const sectionTip = detectSectionConcentration(problemNotes, lang);
  if (sectionTip) suggestions.push({ key: "tip-section", status: "missed", text: sectionTip });

  const tempoTip = detectTempoAdvice(chunkTempoTrend(inferred), firstMeasure, lang);
  if (tempoTip) suggestions.push({ key: "tip-tempo", status: "timing_off", text: tempoTip });

  return {
    overall: overallLine(summary, lang),
    motion: motionFeedback(summary, lang),
    items: suggestions,
  };
}
