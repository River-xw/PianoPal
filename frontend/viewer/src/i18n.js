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

  // --- OnboardingPage.jsx ---
  onboardingEnter: { zh: "进入", en: "Enter" },
  onboardingNameQuestion: { zh: "Hi，你叫什么名字？", en: "Hi, what’s your name?" },

  // --- HomePage.jsx ---
  appSlogan: { zh: "跟着节奏，弹出自信", en: "Practice with rhythm, play with confidence" },
  navLearnMode: { zh: "学习模式", en: "Learning Mode" },
  navLearnModeDesc: { zh: "灯光引导 + 宽松评分，适合练熟一首新歌", en: "LED-guided practice with lenient scoring -- good for learning a new song" },
  navPerformMode: { zh: "演奏模式", en: "Performance Mode" },
  navPerformModeDesc: { zh: "无灯光引导 + 严格评分，检验真正学会了没有", en: "No LED guidance, strict scoring -- check whether you've really got it" },
  navMe: { zh: "我的", en: "Me" },
  navMeDesc: { zh: "练习记录、画像、趋势与比对", en: "Practice history, profile, trends and comparisons" },
  backToHome: { zh: "返回首页", en: "Back to home" },
  currentUserLabel: { zh: "目前使用者：{username}（更换）", en: "Current user: {username} (switch)" },
  recentSummaryTotal: { zh: "总练习次数 {count} 次", en: "{count} practice sessions total" },
  recentSummaryAvg: { zh: "近期平均分 {score}", en: "Recent average score {score}" },
  recentSummaryLast: { zh: "上次练习：{title}（{date}）", en: "Last practiced: {title} ({date})" },
  practiceQuote1: { zh: "慢一点没关系，稳稳地弹好每一个音。", en: "It is okay to go slowly—give every note a steady landing." },
  practiceQuote2: { zh: "先听见心里的节拍，再让手指跟上。", en: "Hear the beat inside first, then let your fingers follow." },
  practiceQuote3: { zh: "每天练十分钟，也会让喜欢的曲子越来越像你。", en: "Even ten minutes a day can make a favorite piece sound more like you." },
  practiceQuote4: { zh: "弹错不是失败，是下一次弹对的提示。", en: "A wrong note is not failure—it is a clue for the next try." },
  practiceQuote5: { zh: "把困难的小节拆开，进步会突然变得很清楚。", en: "Break down the hard measures and progress becomes easier to see." },

  // --- utils/profile.js ---
  profileNoHistory: { zh: "还没有练习纪录，开始你的第一次练习吧", en: "No practice history yet -- start your first session" },
  profileLevelBeginner: { zh: "新手", en: "Beginner" },
  profileLevelIntermediate: { zh: "进阶", en: "Intermediate" },
  profileLevelAdvanced: { zh: "熟练", en: "Proficient" },
  profileLevelLine: { zh: "{level}练习者", en: "{level} player" },
  profileFavoritePiece: { zh: "常练《{title}》", en: "Often practices “{title}”" },
  profileRecentAvg: { zh: "近期平均分 {score}", en: "recent average {score}" },

  // --- SessionSetup.jsx ---
  connectFailed: { zh: "连不上练习服务器，确认树莓派上的 edge/practice_server.py 有在跑", en: "Can't reach the practice server -- check that edge/practice_server.py is running on the Raspberry Pi." },
  startPractice: { zh: "开始练习", en: "Start practice" },
  startPracticeDescription: { zh: "输入姓名、选一首歌、设定速度，开始后会在琴上点灯引导、同步录音，结束后自动显示评分结果。", en: "Enter your name, pick a song and speed -- the keyboard will light up as a guide while it records, then automatically show your scored result." },
  startPerformDescription: { zh: "输入姓名、选一首歌、设定目标速度，开始后同步录音但不会点灯引导，结束后自动显示正式评测报告。", en: "Enter your name, pick a song and target speed -- it records without LED guidance, then automatically shows a formal scored report." },
  yourName: { zh: "姓名", en: "Your name" },
  yourNamePlaceholder: { zh: "输入姓名，用来保存你的评分记录", en: "Enter your name to keep your scores separate" },
  yourNameRequired: { zh: "请先输入姓名再开始", en: "Please enter your name before starting" },
  song: { zh: "曲目", en: "Song" },
  songNotesSuffix: { zh: "音", en: "notes" },
  songHasBlackKeysSuffix: { zh: "，含黑键/超出范围", en: ", includes black keys/out of range" },
  blackKeyWarning: { zh: "这首歌含有黑键或超出 22 白键范围的音符，这些音符不会显示灯光引导、也不计入评分，其余白键音符照常引导与计分。", en: "This song has black-key or out-of-range notes -- those are skipped from LED guidance and excluded from scoring entirely; the remaining white-key notes are guided/graded as usual." },
  importSong: { zh: "自行汇入曲目 (MIDI)", en: "Import your own song (MIDI)" },
  importing: { zh: "汇入中...", en: "Importing..." },
  importFailed: { zh: "汇入失败", en: "Import failed" },
  speedLabel: { zh: "倍速：{speed}x", en: "Speed: {speed}x" },
  targetSpeedLabel: { zh: "目标速度：{speed}x", en: "Target speed: {speed}x" },
  starting: { zh: "启动中...", en: "Starting..." },
  cannotStart: { zh: "无法启动", en: "Couldn't start" },
  viewLastResult: { zh: "查看最近评分结果", en: "View last result" },
  ledConfigLabel: { zh: "灯光参数", en: "LED settings" },
  brightnessLabel: { zh: "亮度：{pct}%", en: "Brightness: {pct}%" },
  fullRangeLabel: { zh: "点亮每个琴键的完整灯珠范围（预设只点第一颗）", en: "Light each key's full LED range (default: just the first LED)" },
  segmentLoopLabel: { zh: "分段循环练习", en: "Segmented loop practice" },
  segmentLoopHint: { zh: "指定小节范围反复循环引导，不计分、不存入历史纪录", en: "Repeats a measure range indefinitely -- not graded, not saved to history" },
  segmentLoopStart: { zh: "起始小节", en: "Start measure" },
  segmentLoopEnd: { zh: "结束小节", en: "End measure" },
  startSegmentLoop: { zh: "开始分段练习", en: "Start segment practice" },

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
  gradingMessage: { zh: "正在分析实际演奏录音与动作识别结果，请稍候...", en: "Analyzing the performance recording and motion result..." },
  noGuideNotice: { zh: "此模式没有灯光引导，请照记忆完整演奏一次。", en: "No LED guidance in this mode -- play the piece through from memory." },
  metronomeMute: { zh: "静音节拍器", en: "Mute metronome" },
  metronomeUnmute: { zh: "取消静音", en: "Unmute metronome" },
  microphoneStarting: { zh: "麦克风准备中", en: "Microphone starting" },
  microphoneRecording: { zh: "麦克风录制中", en: "Microphone recording" },
  motionRecognizing: { zh: "动作识别中", en: "Motion recognition active" },
  motionUnavailable: { zh: "动作识别不可用", en: "Motion recognition unavailable" },
  motionFinished: { zh: "动作识别已完成", en: "Motion recognition finished" },

  // --- SummaryPanel.jsx ---
  overallScore: { zh: "总分", en: "Overall score" },
  tempoRatio: { zh: "速度比例 {ratio}", en: "tempo ratio {ratio}" },
  pitchAccuracy: { zh: "旋律准确性", en: "Melody accuracy" },
  rhythmAccuracy: { zh: "节奏准确率", en: "Rhythm accuracy" },
  handShapeScore: { zh: "动作评分", en: "Motion score" },
  motionSamples: { zh: "动作识别共采纳 {total} 个窗口，其中正常动作 {normal} 个。", en: "Motion assessment used {total} windows; {normal} were classified as normal." },
  motionScoreUnavailable: { zh: "本次没有可用的动作识别数据，动作分不计入总分。", en: "No usable motion data was captured; motion is excluded from the overall score." },
  statCorrect: { zh: "正确", en: "Correct" },
  statTimingOff: { zh: "时间偏差", en: "Timing off" },
  statWrongPitch: { zh: "弹错音", en: "Wrong pitch" },
  statMissed: { zh: "漏弹", en: "Missed" },
  statExtra: { zh: "多弹", en: "Extra" },
  harmonicExtrasRemoved: { zh: "已过滤掉 {n} 个泛音假讯号（跟真正弹奏的音同时出现的高八度假音），不计入评分。", en: "{n} harmonic-overtone artifact{plural} filtered out before scoring (spurious octave-up notes coinciding with a real note)." },
  octaveSlips: { zh: "彈错音里有 {n} 个是刚好差一个八度——用麦克风录音辨识时，这通常是辨识时的八度误判，不一定是手指真的按错了 12 个键外的琴键。", en: "{n} of the wrong-pitch notes {isAre} an exact octave slip -- on audio input this usually means a transcription octave error rather than a finger 12 keys away." },

  // --- FeedbackPanel.jsx ---
  feedbackTitle: { zh: "评语", en: "Feedback" },
  spriteResultHappy: { zh: "做得不错！我们来看看这次值得保留的地方。", en: "Nice work! Let’s look at what is worth keeping from this take." },
  spriteResultSad: { zh: "别灰心，我已经帮你找到下一次可以先改善的地方。", en: "Don’t be discouraged—I found a good place to begin improving next time." },
  motionFeedbackExcellent: {
    zh: "动作评分 {score} 分：手部动作整体稳定、自然，绝大部分识别时段都保持了良好状态。",
    en: "Motion score {score}: your hand movement was stable and natural, with good form through most of the assessed windows.",
  },
  motionFeedbackGood: {
    zh: "动作评分 {score} 分：大部分动作状态良好，可以继续留意手腕放松和动作连贯性。",
    en: "Motion score {score}: most movement looked good; keep an eye on relaxed wrists and smooth transitions.",
  },
  motionFeedbackNeedsWork: {
    zh: "动作评分 {score} 分：有较多时段出现不理想动作，建议放慢速度，逐小节检查手腕与手指姿势。",
    en: "Motion score {score}: several windows showed less effective movement; slow down and check wrist and finger position measure by measure.",
  },
  motionFeedbackUnavailable: {
    zh: "这次没有取得可用的动作识别数据，因此暂时无法判断手部动作情况，也不会把动作分计入总分。",
    en: "No usable motion data was captured this time, so hand movement cannot be assessed and motion is excluded from the overall score.",
  },

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

  // --- MyPage.jsx (formerly HistoryPage.jsx) ---
  historyFilterMode: { zh: "模式", en: "Mode" },
  historyFilterAll: { zh: "全部", en: "All" },
  historyFilterSong: { zh: "曲目", en: "Song" },
  historyEmpty: { zh: "还没有练习纪录", en: "No practice records yet" },
  historyLoadFailed: { zh: "无法载入历史纪录", en: "Couldn't load history" },
  historyDelete: { zh: "删除", en: "Delete" },
  historyDeleteConfirm: { zh: "确定要删除这笔纪录吗？", en: "Delete this record?" },
  historyView: { zh: "查看", en: "View" },
  historyBackToList: { zh: "返回列表", en: "Back to list" },
  historyScore: { zh: "分数", en: "Score" },
  historyDate: { zh: "日期", en: "Date" },
  historyStatusError: { zh: "评分失败", en: "Grading failed" },
  historyExport: { zh: "汇出", en: "Export" },
  trendChartTitle: { zh: "分数趋势", en: "Score trend" },
  compareTitle: { zh: "多笔比对", en: "Comparison" },
  compareSelectHint: { zh: "勾选 2 笔以上的纪录可以比对子分数", en: "Select 2 or more records to compare their sub-scores" },
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
