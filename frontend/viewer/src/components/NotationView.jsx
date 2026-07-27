import { useEffect, useMemo, useRef, useState } from "react";
import {
  Renderer, Stave, StaveNote, Formatter, Accidental,
} from "vexflow";
import { useTranslation } from "../LanguageContext.jsx";

const NOTE_LETTERS = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"];

// [beats, vexflow duration code], longest first -- nearest-match quantizer
const DURATION_TABLE = [
  [4, "w"], [3, "hd"], [2, "h"], [1.5, "qd"], [1, "q"],
  [0.75, "8d"], [0.5, "8"], [0.375, "16d"], [0.25, "16"], [0.125, "32"],
];

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

const MEASURE_BASE_WIDTH = 90;
const PER_NOTE_WIDTH = 26;
const STAVE_LEFT_PAD = 60; // room for the clef on measure 1
const STAVE_HEIGHT = 260;

function pitchToVexKey(pitch) {
  const octave = Math.floor(pitch / 12) - 1;
  return `${NOTE_LETTERS[pitch % 12]}/${octave}`;
}

function quantizeDuration(beats) {
  if (beats == null || beats <= 0) return "8";
  let best = DURATION_TABLE[0];
  let bestDiff = Infinity;
  for (const entry of DURATION_TABLE) {
    const diff = Math.abs(entry[0] - beats);
    if (diff < bestDiff) { bestDiff = diff; best = entry; }
  }
  return best[1];
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Extra notes carry no `measure` (no reference counterpart) -- they inherit
// whichever measure the nearest earlier note in time belongs to, so they
// still land in a sensible place on the page.
function inferMeasures(notes) {
  let last = 1;
  return notes.map((n) => {
    if (n.measure != null) {
      last = n.measure;
      return n;
    }
    return { ...n, measure: last };
  });
}

function groupIntoChords(notes, timeKey) {
  const sorted = [...notes].sort((a, b) => (a[timeKey] ?? 0) - (b[timeKey] ?? 0));
  const chords = [];
  for (const n of sorted) {
    const t = n[timeKey] ?? 0;
    const last = chords[chords.length - 1];
    if (last && Math.abs((last[0][timeKey] ?? 0) - t) < 0.02) {
      last.push(n);
    } else {
      chords.push([n]);
    }
  }
  return chords;
}

// Only show an accidental the first time a given letter+octave needs one
// within a measure (standard notation convention) -- `accidentalState` is a
// Map that the caller resets once per measure per stave.
function buildStaveNote(chordNotes, clef, accidentalState, preview) {
  const keys = chordNotes.map((n) => pitchToVexKey(n.status === "wrong_pitch" || n.status === "extra" ? n.pitch_perf : n.pitch_ref));
  const duration = quantizeDuration(chordNotes[0].dur_beats);
  const staveNote = new StaveNote({ keys, duration, clef, auto_stem: true });

  chordNotes.forEach((n, i) => {
    if (!preview) {
      const color = cssVar(STATUS_VAR[n.status] ?? "--status-correct");
      const opacity = n.status === "missed" ? 0.55 : 1;
      staveNote.setKeyStyle(i, { fillStyle: color, strokeStyle: color, opacity });
    }

    const key = keys[i];
    const [letterPart, octave] = key.split("/");
    const trackKey = `${letterPart[0]}${octave}`;
    const isSharp = letterPart.includes("#");
    const previouslySharp = accidentalState.get(trackKey) === "#";

    if (isSharp && !previouslySharp) {
      staveNote.addModifier(new Accidental("#"), i);
      accidentalState.set(trackKey, "#");
    } else if (!isSharp && previouslySharp) {
      staveNote.addModifier(new Accidental("n"), i);
      accidentalState.set(trackKey, null);
    }
  });

  return staveNote;
}

// preview: true renders plain (no per-note status colors/legend) -- used for
// the segment-loop measure picker in SessionSetup.jsx, showing the song's
// reference notation before any performance exists to score.
// highlightRange: {start, end} (measure numbers, inclusive) draws a tinted
// band behind those measures so the currently-selected loop range is visible
// at a glance.
export default function NotationView({
  notes,
  preview = false,
  highlightRange = null,
  followMeasure = null,
  titleKey = "notationTitle",
}) {
  const { t } = useTranslation();
  const containerRef = useRef(null);
  const scrollerRef = useRef(null);
  const [measureLayout, setMeasureLayout] = useState([]);

  const measures = useMemo(() => {
    const inferred = inferMeasures(notes);
    const byMeasure = new Map();
    for (const n of inferred) {
      const hand = n.hand ?? ((n.status === "wrong_pitch" || n.status === "extra" ? n.pitch_perf : n.pitch_ref) >= 60 ? "R" : "L");
      if (!byMeasure.has(n.measure)) byMeasure.set(n.measure, { R: [], L: [] });
      byMeasure.get(n.measure)[hand === "L" ? "L" : "R"].push(n);
    }
    return [...byMeasure.entries()].sort((a, b) => a[0] - b[0]);
  }, [notes]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || measures.length === 0) return;
    container.innerHTML = "";

    const trebleY = 30;
    const bassY = 140;

    const widths = measures.map(([, { R, L }]) => {
      const rChords = groupIntoChords(R, "onset_ref_sec").length;
      const lChords = groupIntoChords(L, "onset_ref_sec").length;
      return MEASURE_BASE_WIDTH + PER_NOTE_WIDTH * Math.max(rChords, lChords, 1);
    });
    const totalWidth = STAVE_LEFT_PAD + widths.reduce((a, b) => a + b, 0) + 20;

    const renderer = new Renderer(container, Renderer.Backends.SVG);
    renderer.resize(totalWidth, STAVE_HEIGHT);
    const context = renderer.getContext();
    context.setFont("system-ui", 10);

    let x = 10;
    const layout = [];
    measures.forEach(([measureNum, { R, L }], i) => {
      const width = widths[i] + (i === 0 ? STAVE_LEFT_PAD : 0);
      layout.push({ measureNum, x, width });

      const trebleStave = new Stave(x, trebleY, width);
      const bassStave = new Stave(x, bassY, width);
      if (i === 0) {
        trebleStave.addClef("treble");
        bassStave.addClef("bass");
      }
      trebleStave.setContext(context).draw();
      bassStave.setContext(context).draw();

      context.fillText(String(measureNum), x + 2, trebleY - 6);

      const trebleAccidentals = new Map();
      const bassAccidentals = new Map();
      const rChords = groupIntoChords(R, "onset_ref_sec").map((c) => buildStaveNote(c, "treble", trebleAccidentals, preview));
      const lChords = groupIntoChords(L, "onset_ref_sec").map((c) => buildStaveNote(c, "bass", bassAccidentals, preview));

      if (rChords.length) Formatter.FormatAndDraw(context, trebleStave, rChords);
      if (lChords.length) Formatter.FormatAndDraw(context, bassStave, lChords);

      x += width;
    });
    setMeasureLayout(layout);
  }, [measures, preview]);

  useEffect(() => {
    const scroller = scrollerRef.current;
    const current = measureLayout.find((item) => item.measureNum === followMeasure);
    if (!scroller || !current) return;
    const left = Math.max(0, current.x + current.width / 2 - scroller.clientWidth / 2);
    scroller.scrollTo({ left, behavior: "smooth" });
  }, [followMeasure, measureLayout]);

  return (
    <div className="sketch-card">
      <div className="flex flex-wrap items-center gap-4 border-b px-4 py-3 text-sm" style={{ borderColor: "var(--border)" }}>
        <span className="panel-heading mr-2">{t(titleKey)}</span>
        {!preview && Object.entries(STATUS_VAR).map(([status, cssVarName]) => (
          <span key={status} className="inline-flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: `var(${cssVarName})` }} />
            {t(STATUS_LABEL_KEYS[status])}
          </span>
        ))}
      </div>
      <div ref={scrollerRef} className="overflow-x-auto p-2" style={{ maxHeight: 340 }}>
        <div className="relative">
          {highlightRange && measureLayout
            .filter((m) => m.measureNum >= highlightRange.start && m.measureNum <= highlightRange.end)
            .map((m) => (
              <div
                key={m.measureNum}
                className="absolute top-0 rounded"
                style={{ left: m.x, width: m.width, height: STAVE_HEIGHT, background: "var(--accent-light)", opacity: 0.8 }}
              />
            ))}
          <div ref={containerRef} className="relative" />
        </div>
      </div>
    </div>
  );
}
