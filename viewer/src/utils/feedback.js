// Groups non-"correct" notes into contiguous measure ranges by their
// dominant error type, and generates templated Traditional Chinese
// commentary -- entirely client-side, computed straight from result.json.

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

function dominantStatus(entries) {
  const counts = {};
  for (const e of entries) counts[e.status] = (counts[e.status] ?? 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
}

function mergeRanges(problemNotes) {
  const byMeasure = new Map();
  for (const n of problemNotes) {
    if (!byMeasure.has(n.measure)) byMeasure.set(n.measure, []);
    byMeasure.get(n.measure).push(n);
  }
  const measureNumbers = [...byMeasure.keys()].sort((a, b) => a - b);

  const ranges = [];
  for (const m of measureNumbers) {
    const status = dominantStatus(byMeasure.get(m));
    const last = ranges[ranges.length - 1];
    if (last && last.status === status && m - last.end <= 1) {
      last.end = m;
      last.notes.push(...byMeasure.get(m));
    } else {
      ranges.push({ start: m, end: m, status, notes: [...byMeasure.get(m)] });
    }
  }
  return ranges;
}

function measureLabel(range) {
  return range.start === range.end ? `第 ${range.start} 小節` : `第 ${range.start}-${range.end} 小節`;
}

function describeRange(range) {
  const { notes, status } = range;
  const label = measureLabel(range);

  if (status === "wrong_pitch") {
    const example = notes[0];
    return `${label}：出現 ${notes.length} 處彈錯音的情形，例如應該彈 ${example.name}(第${example.ref_index}個音)，卻彈成別的音高。`;
  }

  if (status === "missed") {
    return `${label}：漏彈了 ${notes.length} 個音符，建議放慢速度單獨練習這幾小節。`;
  }

  if (status === "extra") {
    return `${label}附近：多彈出了 ${notes.length} 個樂譜上沒有的音，可能是手指誤觸或多按了鍵。`;
  }

  if (status === "timing_off") {
    const offsets = notes.map((n) => n.offset_ms).filter((v) => v != null);
    const avg = offsets.reduce((a, b) => a + b, 0) / offsets.length;
    const direction = avg < 0 ? "搶拍(彈太早)" : "拖拍(彈太晚)";
    return `${label}：明顯${direction}，平均偏差約 ${Math.abs(Math.round(avg))} 毫秒，共 ${notes.length} 個音符受影響。`;
  }

  return `${label}：有 ${notes.length} 個音符需要留意。`;
}

function overallLine(summary) {
  const { global_tempo_ratio, tempo_trend, counts } = summary;
  const parts = [];

  if (global_tempo_ratio != null) {
    const pct = Math.round((global_tempo_ratio - 1) * 100);
    if (Math.abs(pct) >= 2) {
      parts.push(`整體節奏比參考${pct > 0 ? "慢" : "快"}了約 ${Math.abs(pct)}%`);
    } else {
      parts.push("整體節奏跟參考速度很接近");
    }
  }

  if (tempo_trend === "accelerating") parts.push("演奏過程中有越彈越快的趨勢");
  else if (tempo_trend === "decelerating") parts.push("演奏過程中有越彈越慢的趨勢");

  const totalProblems = counts.timing_off + counts.wrong_pitch + counts.missed + counts.extra;
  if (totalProblems === 0) {
    parts.push("沒有偵測到任何錯誤，非常好！");
  }

  return parts.length ? parts.join("，") + "。" : null;
}

export function generateFeedback(notes, summary) {
  const inferred = inferMeasure(notes);
  const problemNotes = inferred.filter((n) => n.status !== "correct");
  const ranges = mergeRanges(problemNotes);

  // worst-first: most notes affected first, so the biggest issues surface at the top
  ranges.sort((a, b) => b.notes.length - a.notes.length);

  return {
    overall: overallLine(summary),
    items: ranges.map((r) => ({
      key: `${r.status}-${r.start}-${r.end}`,
      status: r.status,
      text: describeRange(r),
    })),
  };
}
