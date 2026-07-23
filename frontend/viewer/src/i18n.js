// Plain (non-React) translation data + lookup, so it's importable from both
// components (via LanguageContext.jsx) and plain-JS modules like
// utils/feedback.js, which generates parameterized sentences and has no
// React context of its own to read from.

export const LANGUAGES = { ZH: "zh", EN: "en" };
export const DEFAULT_LANGUAGE = LANGUAGES.ZH;
export const STORAGE_KEY = "pianopal_lang";

const dict = {
  // --- App.jsx ---
  appTitle: { zh: "PianoPal", en: "PianoPal" },
  backToSongs: { zh: "返回选歌", en: "Back to songs" },
  loadResultJson: { zh: "加载 result.json", en: "Load result.json" },
  errorNotAResultFile: { zh: "不是评分结果 result.json（缺少 summary/notes）。", en: "Not a scoring result.json (missing summary/notes)." },

  // --- SessionSetup.jsx ---
  connectFailed: { zh: "连不上练习服务器，确认树莓派上的 edge/practice_server.py 有在跑", en: "Can't reach the practice server -- check that edge/practice_server.py is running on the Raspberry Pi." },
  startPractice: { zh: "开始练习", en: "Start practice" },
  startPracticeDescription: { zh: "输入姓名、选一首歌、设定速度，开始后会在琴上点灯引导、同步录音，结束后自动显示评分结果。", en: "Enter your name, pick a song and speed -- the keyboard will light up as a guide while it records, then automatically show your scored result." },
  yourName: { zh: "姓名", en: "Your name" },
  yourNamePlaceholder: { zh: "输入姓名，用来保存你的评分记录", en: "Enter your name to keep your scores separate" },
  yourNameRequired: { zh: "请先输入姓名再开始", en: "Please enter your name before starting" },
  song: { zh: "曲目", en: "Song" },
  songNotesSuffix: { zh: "音", en: "notes" },
  songHasBlackKeysSuffix: { zh: "，含黑键/超出范围", en: ", includes black keys/out of range" },
  blackKeyWarning: { zh: "这首歌用到黑键或超出 22 白键范围，灯光引导跟评分准确度会受影响。", en: "This song uses black keys or notes outside the 22-white-key range, which affects LED guidance and grading accuracy." },
  importSong: { zh: "自行汇入曲目 (MIDI)", en: "Import your own song (MIDI)" },
  importing: { zh: "汇入中...", en: "Importing..." },
  importFailed: { zh: "汇入失败", en: "Import failed" },
  speedLabel: { zh: "倍速：{speed}x", en: "Speed: {speed}x" },
  starting: { zh: "启动中...", en: "Starting..." },
  cannotStart: { zh: "无法启动", en: "Couldn't start" },
  viewLastResult: { zh: "查看最近评分结果", en: "View last result" },

  // --- LiveSession.jsx ---
  phaseStarting: { zh: "启动中...", en: "Starting..." },
  phaseGuiding: { zh: "引导中", en: "Guiding" },
  phaseGrading: { zh: "评分中...", en: "Grading..." },
  phaseDone: { zh: "完成", en: "Done" },
  phaseError: { zh: "发生错误", en: "Error" },
  paused: { zh: "已暂停", en: "paused" },
  slower: { zh: "− 慢一点", en: "− Slower" },
  faster: { zh: "+ 快一点", en: "+ Faster" },
  resume: { zh: "继续", en: "Resume" },
  pause: { zh: "暂停", en: "Pause" },
  restart: { zh: "重新开始", en: "Restart" },
  endEarly: { zh: "提前结束", en: "End early" },
  gradingMessage: { zh: "正在把录音抓回来评分，请稍候...", en: "Fetching the recording and grading it, please wait..." },

  // --- SummaryPanel.jsx ---
  overallScore: { zh: "总分", en: "Overall score" },
  tempoRatio: { zh: "速度比例 {ratio}", en: "tempo ratio {ratio}" },
  pitchAccuracy: { zh: "音高准确率", en: "Pitch accuracy" },
  rhythmAccuracy: { zh: "节奏准确率", en: "Rhythm accuracy" },
  timingStability: { zh: "节奏稳定度", en: "Timing stability" },
  statCorrect: { zh: "正确", en: "Correct" },
  statTimingOff: { zh: "时间偏差", en: "Timing off" },
  statWrongPitch: { zh: "弹错音", en: "Wrong pitch" },
  statMissed: { zh: "漏弹", en: "Missed" },
  statExtra: { zh: "多弹", en: "Extra" },
  harmonicExtrasRemoved: { zh: "已过滤掉 {n} 个泛音假讯号（跟真正弹奏的音同时出现的高八度假音），不计入评分。", en: "{n} harmonic-overtone artifact{plural} filtered out before scoring (spurious octave-up notes coinciding with a real note)." },
  octaveSlips: { zh: "彈错音里有 {n} 个是刚好差一个八度——用麦克风录音辨识时，这通常是辨识时的八度误判，不一定是手指真的按错了 12 个键外的琴键。", en: "{n} of the wrong-pitch notes {isAre} an exact octave slip -- on audio input this usually means a transcription octave error rather than a finger 12 keys away." },

  // --- FeedbackPanel.jsx ---
  feedbackTitle: { zh: "评语", en: "Feedback" },

  // --- feedback.js overallLine ---
  tempoSlowerBy: { zh: "整体节奏比参考慢了约 {pct}%", en: "Overall tempo is about {pct}% slower than the reference" },
  tempoFasterBy: { zh: "整体节奏比参考快了约 {pct}%", en: "Overall tempo is about {pct}% faster than the reference" },
  tempoCloseToReference: { zh: "整体节奏跟参考速度很接近", en: "Overall tempo is very close to the reference" },
  noErrorsDetected: { zh: "没有侦测到任何错误，非常好！", en: "No errors detected -- great job!" },

  // --- feedback.js pattern suggestions ---
  chordCompletenessTip: { zh: "和弦里{voice}的那个音经常漏弹或弹错——建议先把两手分开，各自单独确认和弦音的位置，熟悉后再合起来弹。", en: "The {voice} note in chords is often missed or wrong -- try practicing each hand's chord notes separately first, then combine once both are solid." },
  chordVoiceLower: { zh: "音高较低", en: "lower-pitched" },
  chordVoiceHigher: { zh: "音高较高", en: "higher-pitched" },
  pitchHotspotTip: { zh: "{name} 这个音特别容易漏弹或弹错（共 {count} 次）——建议确认一下这个键对应的手指位置，单独反复练习这个音的按法。", en: "The note {name} is especially error-prone (missed or wrong {count} times) -- check the finger position for that key and drill it on its own." },
  sectionConcentrationTip: { zh: "这次的问题有 {pct}% 集中在{label}——建议先单独反复练习这几小节，熟悉后再跟前后段落串起来弹。", en: "{pct}% of this attempt's problems are concentrated in {label} -- try isolating and repeating just that section before playing it in context." },
  tempoEarlyRushTip: { zh: "开头几小节明显偏快——建议弹奏前先在心里默数一小节的拍子，用稳定的速度开始，不要一开始就抢拍。", en: "The opening measures are noticeably rushed -- try counting one full measure silently before you start playing, so you begin at a steady tempo instead of rushing in." },
  tempoRangeTip: { zh: "{label}节奏明显{verb}——建议这几小节搭配节拍器放慢练习，抓稳拍子后再逐渐恢复正常速度。", en: "{label} is noticeably {verb} -- try practicing that section slowly with a metronome, then gradually bring it back up to speed once it's steady." },
  tempoVerbRush: { zh: "抢拍(偏快)", en: "rushed" },
  tempoVerbDrag: { zh: "拖拍(偏慢)", en: "dragging" },
  measureRangeSingle: { zh: "第 {start} 小节", en: "measure {start}" },
  measureRangeMulti: { zh: "第 {start}-{end} 小节", en: "measures {start}-{end}" },

  // --- PianoRoll.jsx / NotationView.jsx / TimingStrip.jsx ---
  pianoRollTitle: { zh: "钢琴卷帘", en: "Piano roll" },
  notationTitle: { zh: "五线谱", en: "Notation" },
  timingStripTitle: { zh: "节奏偏移趋势图", en: "Timing drift over time" },
  statusLabelCorrect: { zh: "正确", en: "correct" },
  statusLabelTimingOff: { zh: "时间偏差", en: "timing off" },
  statusLabelWrongPitch: { zh: "弹错音", en: "wrong pitch" },
  statusLabelMissed: { zh: "漏弹", en: "missed" },
  statusLabelExtra: { zh: "多弹", en: "extra" },
  tooltipExpectedPitch: { zh: "应弹音高：{pitch} @ {time}s", en: "expected pitch: {pitch} @ {time}s" },
  tooltipPlayedPitch: { zh: "实际音高：{pitch} @ {time}s", en: "played pitch: {pitch} @ {time}s" },
  tooltipOffset: { zh: "偏差：{ms}ms（{timing}）", en: "offset: {ms}ms ({timing})" },
  tooltipMeasure: { zh: "第 {measure} 小节{hand}", en: "measure {measure}{hand}" },
  tooltipHandSuffix: { zh: "・{hand}手", en: " · {hand} hand" },
  timingAccurate: { zh: "准确", en: "accurate" },
  timingRush: { zh: "抢拍", en: "rush" },
  timingDrag: { zh: "拖拍", en: "drag" },
};

export function translate(key, lang, vars) {
  const entry = dict[key];
  let str = entry ? (entry[lang] ?? entry[DEFAULT_LANGUAGE] ?? key) : key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      str = str.split(`{${name}}`).join(String(value));
    }
  }
  return str;
}
