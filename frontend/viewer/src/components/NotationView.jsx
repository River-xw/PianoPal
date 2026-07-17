import { useEffect, useMemo, useRef } from "react";
import {
  Renderer, Stave, StaveNote, Formatter, Accidental,
} from "vexflow";

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

const MEASURE_BASE_WIDTH = 90;
const PER_NOTE_WIDTH = 26;
const STAVE_LEFT_PAD = 60; // room for the clef on measure 1

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
function buildStaveNote(chordNotes, clef, accidentalState) {
  const keys = chordNotes.map((n) => pitchToVexKey(n.status === "wrong_pitch" || n.status === "extra" ? n.pitch_perf : n.pitch_ref));
  const duration = quantizeDuration(chordNotes[0].dur_beats);
  const staveNote = new StaveNote({ keys, duration, clef, auto_stem: true });

  chordNotes.forEach((n, i) => {
    const color = cssVar(STATUS_VAR[n.status] ?? "--status-correct");
    const opacity = n.status === "missed" ? 0.55 : 1;
    staveNote.setKeyStyle(i, { fillStyle: color, strokeStyle: color, opacity });

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

export default function NotationView({ notes }) {
  const containerRef = useRef(null);

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
    const staveHeight = 260;

    const widths = measures.map(([, { R, L }]) => {
      const rChords = groupIntoChords(R, "onset_ref_sec").length;
      const lChords = groupIntoChords(L, "onset_ref_sec").length;
      return MEASURE_BASE_WIDTH + PER_NOTE_WIDTH * Math.max(rChords, lChords, 1);
    });
    const totalWidth = STAVE_LEFT_PAD + widths.reduce((a, b) => a + b, 0) + 20;

    const renderer = new Renderer(container, Renderer.Backends.SVG);
    renderer.resize(totalWidth, staveHeight);
    const context = renderer.getContext();
    context.setFont("system-ui", 10);

    let x = 10;
    measures.forEach(([measureNum, { R, L }], i) => {
      const width = widths[i] + (i === 0 ? STAVE_LEFT_PAD : 0);

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
      const rChords = groupIntoChords(R, "onset_ref_sec").map((c) => buildStaveNote(c, "treble", trebleAccidentals));
      const lChords = groupIntoChords(L, "onset_ref_sec").map((c) => buildStaveNote(c, "bass", bassAccidentals));

      if (rChords.length) Formatter.FormatAndDraw(context, trebleStave, rChords);
      if (lChords.length) Formatter.FormatAndDraw(context, bassStave, lChords);

      x += width;
    });
  }, [measures]);

  return (
    <div className="rounded-xl border" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
      <div className="flex items-center gap-4 border-b px-4 py-2 text-sm" style={{ borderColor: "var(--border)" }}>
        <span className="font-medium" style={{ color: "var(--text-primary)" }}>Notation</span>
        {Object.entries(STATUS_VAR).map(([status, cssVarName]) => (
          <span key={status} className="inline-flex items-center gap-1.5" style={{ color: "var(--text-secondary)" }}>
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: `var(${cssVarName})` }} />
            {status.replace("_", " ")}
          </span>
        ))}
      </div>
      <div className="overflow-x-auto p-2" style={{ maxHeight: 340 }}>
        <div ref={containerRef} />
      </div>
    </div>
  );
}
