# viewer

给 [backend.scoring](../../backend/scoring) 模块输出的 `result.json` 用的网页查看器，也是整个练习流程的前端：引导页（姓名输入 + Slogan）→ 主页（logo + 近期总结 + 三张导览卡片）→ 学习模式／演奏模式（各自的选歌→引导/录音→评分报告）／我的（历史纪录 + 画像 + 趋势/比对）。

## 页面架构

不用 `react-router`（维持项目一贯的轻量风格），`App.jsx` 用一个 `page: "onboarding" | "home" | "learn" | "perform" | "me"` 的 state 机做最外层导览，`learn`/`perform` 内部各自维持 `setup → live → result` 三态子状态机（两者共用 `SessionSetup`/`LiveSession`，用 `mode` prop 区分文案跟行为）。姓名存在 localStorage：第一次打开（或姓名被清空）落到 `onboarding`，之后刷新直接进 `home`；`home` 页上有个「目前用户：xxx（更换）」链接可以随时切回 `onboarding` 换身份。

**学习模式 vs 演奏模式**：都是 `POST /api/session/start` 带 `mode: "learn"|"perform"`，后端依 mode 选一组 `ScoringConfig` 权重（`edge/practice_server.py`/`scripts/session_server.py` 的 `MODE_SCORE_WEIGHTS`）——学习模式旋律／动作权重高、节奏均匀度不计；演奏模式三者较均衡的严格评分，而且会多带 `--no-leds` 给 `ws2812_guide_song.py`（只计时+录音，不点灯）。**评分引擎本身完全没有分两套**，纯粹是权重参数不同。手型评分在 `edge/practice_server.py`（前端实际在用的树莓派原生 orchestrator）已经接上真的 IMU 姿势分类器——有设置 BLE 传感设备（`edge/microbit_rpi_comm/raspberry/config.json`）时，`edge/posture_capture.py` 会在整场练习期间即时分类手型姿势、把「正常姿势时间窗比例」换算成 `motion_score`（0-100）喂进评分公式；BLE、设置档或模型不可用时这个子分数显示 N/A，并且**从总分的加权平均中重新正规化排除**，不会用固定占位分顶替去拉低或掩盖总分（旧版「没装硬件就退回固定 100 分」的行为已经改掉）。`scripts/session_server.py`（SSH 备案 orchestrator）目前还没接这块真实数据。

学习模式另外还有：**灯光参数**（亮度滑杆 + 全键位/单键位范围切换，随 `POST /api/session/start` 的 `brightness`/`full_range` 传给 `ws2812_guide_song.py` 既有的 `--brightness`/`--full-range`）、**节拍器**（`LiveSession.jsx` 用 `src/utils/metronome.js` 的 Web Audio lookahead scheduler，贯穿整个引导过程持续播放，拍速 = 曲子的 `tempo_bpm × 目前倍速`，跟树莓派的灯光/录音时序完全独立，纯浏览器端）、**曲目记忆**（`GET /api/songs?username=&mode=` 回传这个用户在这个模式下最近弹的 `last_song_id`，选歌下拉缺省带出）、**分段循环练习**（指定小节范围让 `ws2812_guide_song.py` 反复循环引导，见下方独立说明）。

**分段循环练习**：学习模式选歌画面上的另一个独立按钮（不是「开始练习」，是「开始分段练习」），带 `loop_start_measure`/`loop_end_measure` 给后端；`ws2812_guide_song.py` 算出这个小节范围对应的时间区间，让播放时钟到达区间终点就自动绕回起点、无限循环，直到用户按「结束」。这种 session **不计分、不存入历史纪录**（`Session.practice_only`）——分段反复弹奏的录音对着整曲的参考谱评分没有意义，纯粹是熟练用的练习辅助。

**我的**：每次评分完成，后端会把正式评测产物存到 `data/formal_assessments/sessions/<姓名>/<session_id>/`（包含 `performance.wav`、`motion_assessment.json`、`audio_debug.json` 与 `result.json`），与 `data/training_collection/` 下的原始训练采集完全分开，并把摘要写进 `backend/db/sqlite.py` 管理的 SQLite（`practice_sessions` 表）。前端「我的」页面打 `GET /api/history?username=&mode=&song_id=` 拿列表（回应同时带一个 `profile` 区块：`total_sessions`/`recent_avg_score`/`most_frequent_piece`，`home`页的「近期总结」卡片跟「我的」页最上面的画像卡片共用同一份数据、同一句用 `src/utils/profile.js` 产生的画像文本）、`GET /api/history/<session_id>` 拿单笔完整报告（直接喂给跟即时结果同一组 `SummaryPanel`/`NotationView`/`FeedbackPanel`/`PianoRoll`/`TimingStrip`）、`DELETE /api/history/<session_id>` 删除。列表下方还有**分数趋势图**（`TrendChart.jsx`，手刻 SVG，同 `PianoRoll`/`TimingStrip` 风格）跟**多笔比对**（勾选 2 笔以上跳出子分数对照表），每笔记录可以直接**导出 JSON**（纯前端 Blob 下载，没有额外后端 API）。这套 SQLite schema是队友原本为了姿势辨识另外写的，这次接进来重用，额外加了一个 `mode` 字段（additive migration，不影响队友原本的用法）。

## 视觉风格

整体是「手绘涂鸦风」：每页顶部、引导页与首页使用用户手绘的 `public/assets/pianopal-logo.png`，进入时以逐段揭示模拟书写过程；其余标题和内文统一使用较规整的 `Patrick Hand`，中文逐字 fallback 到 `ZCOOL KuaiLe`。全局 rem 基准也已放大，面板标题另有更大的 `.panel-heading` 层级。动画遵守系统的「减少动态效果」设置。

同一目录还放有四张用户手绘小精灵：惊讶版用于姓名输入页、打招呼版在首页搭配随机钢琴练习语录、开心/沮丧版依总分是否达到 60 分显示在 result 评语中。小精灵保留透明原图，不套圆形背景框；result 气泡还会依动作评分产生中英文的优秀／良好／需改善／数据不可用反馈。

首页三张模式卡上方各有一组双帧插画，资源位于 `public/illustrations/`：`learn`、`perform`、`profile` 各有 `-idle.svg` 与 `-active.svg`，鼠标悬浮或键盘聚焦时以淡入 + 轻微位移切换到 active 帧。两帧应保持相同画布、主体位置与透明背景，这样切换不会跳动；默认示例统一使用 `viewBox="0 0 200 140"`。自己绘制时优先使用 SVG；若是 Procreate/Photoshop 等点阵作品，建议导出透明 WebP（显示尺寸约 190×128 px，建议按 2x 输出为 380×256 px），再在 `HomePage.jsx` 的 `ModeIllustration` 路径中把扩展名从 `.svg` 改成 `.webp`。

所有卡片容器用 `.sketch-card`/`.sketch-card-alt`（`index.css`）套不对称的 `border-radius` 做出歪斜的手绘感，配合纸感背景(`body::before` 的颗粒纹理)、便利贴胶带(`.washi-tape`)、萤光笔画重点(`.marker-highlight`)。主色调是蓝色系（`--accent` + 天空蓝/蓝绿/蓝紫/深靛蓝四种装饰色 `--sketch-*`/`--tint-*`），评分可视化用的状态色（`--status-*`）完全独立、不随主色调制动。`引导/学习模式/演奏模式` 这几个内容量小的「单卡片」画面在 `App.jsx` 里会垂直置中；首页加入小精灵语录后改为自然滚动，避免矮屏内容被裁掉。「我的」跟评分报告页也维持从上往下自然排列。

## 运行

### 方式 A（推荐）：整套跑在树莓派上，本机纯看画面

前端 build 成静态档、跟后端一起由树莓派上的 `edge/practice_server.py` 一个进程 serve，本机（或任何同网段设备）只要开浏览器，什么都不用装。

前置（树莓派上要有 backend/ 跟评分依赖，一次性）：

```bash
# 树莓派上
sudo pip3 install librosa scipy soundfile pretty_midi mido music21 --break-system-packages
```

在本机 build 前端、连同后端一起同步到树莓派（树莓派没有 Node，所以在有 Node 的机器 build 好再送过去；`edge/frontend_dist/` 是 build 产物，不进 git）：

```bash
cd frontend/viewer && npm install && npm run build
rsync -av frontend/viewer/dist/ pi@<树莓派IP>:~/PianoPal/edge/frontend_dist/
rsync -av --exclude='.venv' --exclude='__pycache__' backend/ pi@<树莓派IP>:~/PianoPal/backend/
rsync -av --exclude='*.wav' data/bf3738c_keybank docs/piano_music pi@<树莓派IP>:~/PianoPal/data/ 2>/dev/null
```

树莓派上启动一个进程：

```bash
cd ~/PianoPal
PIANOPAL_RECORD_DEVICE='plughw:CARD=Device_1,DEV=0' \
PIANOPAL_PLAYBACK_DEVICE='plughw:CARD=Device,DEV=0' \
backend/audio_to_performance/.venv/bin/python3 edge/practice_server.py --port 8900
```

本机浏览器打开 `http://<树莓派IP>:8900/` 就是选歌画面。整个练习流程（引导/录音/评分）都在树莓派本地跑，本机跟树莓派之间的网络抖动不影响流程，只影响你看不看得到画面。

### 方式 B（备案）：dev 机器通过 SSH 遥控树莓派

树莓派没装评分依赖时用这个——转谱跟评分在 dev 机器上跑，通过 SSH 启动树莓派的灯光引导+录音、再把录音抓回来评分：

```bash
# 1. dev 机器上：SSH-based orchestrator（缺省连 :8900）
./backend/audio_to_performance/.venv/bin/python3 scripts/session_server.py
# 2. dev 机器上：前端 dev server（vite 会把 /api 等请求 proxy 到 :8900）
cd frontend/viewer && npm install && npm run dev
```

打开 `http://localhost:5173`。前端用同源相对路径调用后端，dev 模式下由 `vite.config.js` 的 proxy 转发到 session server；如果 session server 不在 `localhost:8900`，用 `SESSION_SERVER=host:port npm run dev` 指定。

### 只看既有结果

如果只是想单纯看一份既有的 `result.json`（不通过树莓派、也不跑任何 server），右上角「Load result.json」可以手动选文件。

## 语言切换

右上角有个「EN／中文」按钮，整个接口（含「评语」面板动态产生的建议句子）都有繁简双语版本，切换后会存在 localStorage，下次打开记得你上次选的语言。翻译字典在 `src/i18n.js`（一份不依赖 React 的纯数据，`utils/feedback.js` 这种产生动态句子的模块也是直接 import 它来用，不用通过 React context）。

## 画面看到什么

**上方摘要卡片**：总分、三个子分数（旋律准确性／节奏准确率／动作评分）、全域速度比例（`global_tempo_ratio`），以及各分类（正确/时间偏差/弹错音/漏弹/多弹）各几个。节奏稳定度已从 result 展示、历史比对和生产评分权重中移除；旧 result.json 即使仍带有该字段也会被忽略。

**Notation（五线谱）**：对弹奏者来说比 MIDI 风格的方格图直观很多——用真正的高音/低音谱表（右手→高音谱号、左手→低音谱号）画出每个音符，依小节分行、依评分结果着色（颜色规则跟下面 Piano roll 一致）。音符时值是从 `dur_beats` 量化成最接近的标准音符（四分、八分…），所以节奏复杂的段落画出来会略为简化，不是逐拍精确的原始记谱。

**评语**：开心或沮丧小精灵会先用手绘气泡给出动作状态反馈，再以白话文列出「哪几小节有什么问题」，依影响音符数量由多到少排序，例如：

> 第 56-60 小节：明显抢拍(弹太早)，平均偏差约 90 毫秒，共 95 个音符受影响。

这段文本完全是前端自己算出来的（`src/utils/feedback.js`），把连续、同类型的错误小节合并成一个范围，不需要调用任何 AI/后端。

**Piano roll（钢琴滚动条）**：x 轴是时间、y 轴是 MIDI 音高，灰色直线是小节分界。每个音符依评分结果着色：

| 颜色 | 状态 | 画法 |
| --- | --- | --- |
| 绿 | `correct` | 实心色块，画在参考位置 |
| 橘 | `timing_off` | 实心色块，画在**实际弹奏**的时间点，并标示 ← / → 箭头与偏差毫秒数 |
| 红 | `wrong_pitch` | 实心色块画在**实际弹到**的音高，虚线连到上方/下方期望音高的位置，两者都能看到 |
| 灰（空心虚线框） | `missed` | 画在参考位置，代表「应该有这个音但没弹」 |
| 紫（菱形） | `extra` | 画在实际弹奏的位置，用不同形状跟其他状态区分「这是多弹出来的」 |

鼠标移到任一个音符上会跳出提示框，显示期望音高/时间、实际音高/时间、偏差毫秒数、小节、左右手。（Notation 面板目前没有做这个 hover 提示——出错的细节交给「评语」跟 Piano roll 负责。）

**Timing drift over time（下方小图）**：每个有时间数据的音符，x 轴是它在曲子里的顺序、y 轴是 `offset_ms`。如果这条线整体往下滑，代表用户演奏中途开始抢拍（越弹越快）；往上滑则是拖拍。

## 颜色从哪里来

状态颜色不是随便挑的，是套用项目内置的 dataviz 色票规则：`correct`/`timing_off`/`wrong_pitch` 对应色票里保留给「good/warning/critical」状态用的固定色（不会跟其他图表的分类色冲突）；`extra` 没有对应的第四个状态色，所以借用了分类色票里最接近紫色的 violet 色阶。浅色/深色模式都有对应的数值，写在 `src/index.css` 的 CSS variables 里（跟着系统的深色模式设置自动切换）。Notation 面板用 `getComputedStyle` 在画图当下读出这些变量目前解析出来的颜色，所以也会跟着深色模式切换。

## 文件结构

| 文件 | 作用 |
| --- | --- |
| `src/App.jsx` | 最外层：`page`(onboarding/home/learn/perform/me) + `view`(setup/live/result，只在 learn/perform 内有意义) 状态机、文件选取、姓名状态(含 localStorage)、把数据分派给各个面板 |
| `src/i18n.js` | 纯数据的翻译字典 + `translate(key, lang, vars)`，不依赖 React，`utils/feedback.js`/`utils/profile.js` 也直接 import |
| `src/LanguageContext.jsx` | 包在 `i18n.js` 外面的 React context/hook(`useTranslation`)，管理目前语言 + localStorage 持久化 |
| `src/components/BrandLogo.jsx` | 共用的用户手绘 PianoPal PNG Logo |
| `src/components/OnboardingPage.jsx` | 引导页：惊讶小精灵、手写 Logo 动画、Slogan、姓名输入框、「进入」按钮 |
| `src/components/HomePage.jsx` | 主页：打招呼小精灵 + 随机语录、近期总结、三张双帧插画导览卡片、切换用户链接 |
| `public/assets/` | 用户提供的 Logo 与四种情绪小精灵 PNG |
| `public/illustrations/` | 首页三种模式的 idle/active 双帧 SVG 插画与替换规范 |
| `src/components/Doodles.jsx` | 背景散落的手绘小图标(星星/爱心/闪光)，只用在数据量少的页面(引导页/主页)，避免干扰数据密集画面的阅读 |
| `src/components/icons.jsx` | 共用的极简线条图标(灯泡/靶心/循环箭头/展开箭头)，`SessionSetup.jsx` 用来标示学习/演奏模式跟各个子区块 |
| `src/components/MyPage.jsx` | 我的：用户画像卡片、分数趋势图、练习记录列表(依模式/曲目筛选、多笔勾选比对)、单笔查看(复用结果视图)、删除、导出 JSON |
| `src/components/TrendChart.jsx` | 分数趋势折线图(手刻 SVG，同 PianoRoll/TimingStrip 风格) |
| `src/utils/profile.js` | 从 `profile` 聚合数据算出「新手/高端/熟练」等级 + 一句话画像文本，HomePage/MyPage 共用 |
| `src/utils/download.js` | 纯前端 Blob 下载小工具，导出功能用 |
| `src/utils/metronome.js` | Web Audio lookahead-scheduler 节拍器 class，不依赖 React，`LiveSession.jsx` 用它在学习模式引导过程中持续播放拍子 |
| `src/components/SessionSetup.jsx` | 学习/演奏模式共用的选歌画面：姓名输入框、曲库清单(来自 session server，含曲目记忆缺省)、自行导入 MIDI、倍速/目标速度选择；学习模式另有灯光参数(亮度/范围)跟分段循环练习区块；开始按钮，用 `mode` prop 切换文案跟送出的权重模式 |
| `src/components/LiveSession.jsx` | 引导中画面：轮询 session 状态、显示进度条、跑节拍器；学习模式有变速/暂停/重来/节拍器静音按钮，演奏模式只有提前结束(不能中途调速/暂停/重来) |
| `src/components/SummaryPanel.jsx` | 总分/子分数/计数摘要卡片 |
| `src/components/NotationView.jsx` | 用 [VexFlow](https://www.vexflow.com/) 画的五线谱视图 |
| `src/components/FeedbackPanel.jsx` | 「评语」文本面板 |
| `src/utils/feedback.js` | 分析错误模式(和弦漏弹/特定音高/小节集中/节奏抢拍拖拍)、产生双语练习建议的逻辑，不是逐音符列表 |
| `src/components/PianoRoll.jsx` | 钢琴滚动条可视化 |
| `src/components/TimingStrip.jsx` | 节奏漂移小图 |
| `src/index.css` | Tailwind 进入点 + 颜色/接口用的 CSS variables(含深色模式、引导页用的 `--accent` 品牌蓝) |

## 已知限制

- `result.json` 没有拍号信息，所以 Notation 面板不画时间记号，也不验证每小节的拍数是否补满——单纯把每个音符依量化后的时值排进去
- `extra`（多弹的音）没有参考小节可以对应，Notation 面板会把它们挂在「时间上最接近的前一个音符」所在的小节，只是视觉上的近似安排
- Notation 面板的音符一律用升记号拼写（不会自动改用降记号），如果乐曲调性偏好用降记号，画出来的音高没错，但拼字不是最直觉的那种
- 目前只支持本机选档或 `frontend/viewer/public/result.json` 自动加载，没有做后端 API 串接
- 分段循环练习跟灯光亮度/范围参数这两个功能只在本机做过程序逻辑 dry-run（`--no-leds`），实际树莓派 LED 硬件效果还没有实机验证过
