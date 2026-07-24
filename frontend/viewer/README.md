# viewer

給 [backend.scoring](../../backend/scoring) 模組輸出的 `result.json` 用的網頁檢視器，也是整個練習流程的前端：引導頁（姓名輸入 + Slogan）→ 主頁（logo + 近期總結 + 三張導覽卡片）→ 學習模式／演奏模式（各自的選歌→引導/錄音→評分報告）／我的（歷史紀錄 + 畫像 + 趨勢/比對）。

## 頁面架構

不用 `react-router`（維持專案一貫的輕量風格），`App.jsx` 用一個 `page: "onboarding" | "home" | "learn" | "perform" | "me"` 的 state 機做最外層導覽，`learn`/`perform` 內部各自維持 `setup → live → result` 三態子狀態機（兩者共用 `SessionSetup`/`LiveSession`，用 `mode` prop 區分文案跟行為）。姓名存在 localStorage：第一次打開（或姓名被清空）落到 `onboarding`，之後重新整理直接進 `home`；`home` 頁上有個「目前使用者：xxx（更換）」連結可以隨時切回 `onboarding` 換身份。

**學習模式 vs 演奏模式**：都是 `POST /api/session/start` 帶 `mode: "learn"|"perform"`，後端依 mode 選一組 `ScoringConfig` 權重（`edge/practice_server.py`/`scripts/session_server.py` 的 `MODE_SCORE_WEIGHTS`）——學習模式旋律／動作權重高、節奏均勻度不計；演奏模式三者較均衡的嚴格評分，而且會多帶 `--no-leds` 給 `ws2812_guide_song.py`（只計時+錄音，不點燈）。**評分引擎本身完全沒有分兩套**，純粹是權重參數不同。手型評分在 `edge/practice_server.py`（前端實際在用的樹莓派原生 orchestrator）已經接上真的 IMU 姿勢分類器——有設定 BLE 感測裝置（`edge/microbit_rpi_comm/raspberry/config.json`）時，`edge/posture_capture.py` 會在整場練習期間即時分類手型姿勢、把「正常姿勢時間窗比例」換算成 `motion_score`（0-100）餵進評分公式；BLE、設定檔或模型不可用時這個子分數顯示 N/A，並且**從總分的加權平均中重新正規化排除**，不會用固定佔位分頂替去拉低或掩蓋總分（舊版「沒裝硬體就退回固定 100 分」的行為已經改掉）。`scripts/session_server.py`（SSH 備案 orchestrator）目前還沒接這塊真實資料。

學習模式另外還有：**燈光參數**（亮度滑桿 + 全鍵位/單鍵位範圍切換，隨 `POST /api/session/start` 的 `brightness`/`full_range` 傳給 `ws2812_guide_song.py` 既有的 `--brightness`/`--full-range`）、**節拍器**（`LiveSession.jsx` 用 `src/utils/metronome.js` 的 Web Audio lookahead scheduler，貫穿整個引導過程持續播放，拍速 = 曲子的 `tempo_bpm × 目前倍速`，跟樹莓派的燈光/錄音時序完全獨立，純瀏覽器端）、**曲目記憶**（`GET /api/songs?username=&mode=` 回傳這個使用者在這個模式下最近彈的 `last_song_id`，選歌下拉預設帶出）、**分段循環練習**（指定小節範圍讓 `ws2812_guide_song.py` 反覆循環引導，見下方獨立說明）。

**分段循環練習**：學習模式選歌畫面上的另一個獨立按鈕（不是「開始練習」，是「開始分段練習」），帶 `loop_start_measure`/`loop_end_measure` 給後端；`ws2812_guide_song.py` 算出這個小節範圍對應的時間區間，讓播放時鐘到達區間終點就自動繞回起點、無限循環，直到使用者按「結束」。這種 session **不計分、不存入歷史紀錄**（`Session.practice_only`）——分段反覆彈奏的錄音對著整曲的參考譜評分沒有意義，純粹是熟練用的練習輔助。

**我的**：每次評分完成，後端會把正式評測產物存到 `data/formal_assessments/sessions/<姓名>/<session_id>/`（包含 `performance.wav`、`motion_assessment.json`、`audio_debug.json` 與 `result.json`），與 `data/training_collection/` 下的原始训练采集完全分开，并把摘要写进 `backend/db/sqlite.py` 管理的 SQLite（`practice_sessions` 表）。前端「我的」頁面打 `GET /api/history?username=&mode=&song_id=` 拿列表（回應同時帶一個 `profile` 區塊：`total_sessions`/`recent_avg_score`/`most_frequent_piece`，`home`頁的「近期總結」卡片跟「我的」頁最上面的畫像卡片共用同一份資料、同一句用 `src/utils/profile.js` 產生的畫像文字）、`GET /api/history/<session_id>` 拿單筆完整報告（直接餵給跟即時結果同一組 `SummaryPanel`/`NotationView`/`FeedbackPanel`/`PianoRoll`/`TimingStrip`）、`DELETE /api/history/<session_id>` 刪除。列表下方還有**分數趨勢圖**（`TrendChart.jsx`，手刻 SVG，同 `PianoRoll`/`TimingStrip` 風格）跟**多筆比對**（勾選 2 筆以上跳出子分數對照表），每筆記錄可以直接**匯出 JSON**（純前端 Blob 下載，沒有額外後端 API）。這套 SQLite schema是隊友原本為了姿勢辨識另外寫的，這次接進來重用，額外加了一個 `mode` 欄位（additive migration，不影響隊友原本的用法）。

## 視覺風格

整體是「手繪塗鴉風」：標題/logo 用 Google Fonts 的 `Permanent Marker`/`Caveat`（英文）+ `ZCOOL KuaiLe`（中文專用的圓潤手寫字體——前兩個純西文字體完全不含中文字形，中文文字都是靠字體堆疊自動 fallback 到 `ZCOOL KuaiLe` 才有手寫感，見 `index.html` 的字體 `<link>` 跟 `index.css` 的 `--font-title`/`--font-hand`），內文用 `Kalam`。所有卡片容器用 `.sketch-card`/`.sketch-card-alt`（`index.css`）套不對稱的 `border-radius` 做出歪斜的手繪感，配合暖色紙感背景(`body::before` 的顆粒紋理)、便利貼膠帶(`.washi-tape`)、螢光筆畫重點(`.marker-highlight`)。主色調是藍色系（`--accent` + 天空藍/藍綠/藍紫/深靛藍四種裝飾色 `--sketch-*`/`--tint-*`），評分視覺化用的狀態色（`--status-*`）完全獨立、不隨主色調變動。`引導/主頁/學習模式/演奏模式` 這幾個內容量小的「單卡片」畫面在 `App.jsx` 裡會垂直置中在扣掉 header 後的剩餘高度，避免寬螢幕(16:9)下面留一大片空白；「我的」跟評分報告頁維持從上往下自然排列，因為內容量會隨資料增減。

## 執行

### 方式 A（推薦）：整套跑在樹莓派上，本機純看畫面

前端 build 成靜態檔、跟後端一起由樹莓派上的 `edge/practice_server.py` 一個程序 serve，本機（或任何同網段裝置）只要開瀏覽器，什麼都不用裝。

前置（樹莓派上要有 backend/ 跟評分依賴，一次性）：

```bash
# 樹莓派上
sudo pip3 install librosa scipy soundfile pretty_midi mido music21 --break-system-packages
```

在本機 build 前端、連同後端一起同步到樹莓派（樹莓派沒有 Node，所以在有 Node 的機器 build 好再送過去；`edge/frontend_dist/` 是 build 產物，不進 git）：

```bash
cd frontend/viewer && npm install && npm run build
rsync -av frontend/viewer/dist/ pi@<樹莓派IP>:~/PianoPal/edge/frontend_dist/
rsync -av --exclude='.venv' --exclude='__pycache__' backend/ pi@<樹莓派IP>:~/PianoPal/backend/
rsync -av --exclude='*.wav' data/bf3738c_keybank docs/piano_music pi@<樹莓派IP>:~/PianoPal/data/ 2>/dev/null
```

樹莓派上啟動一個程序：

```bash
cd ~/PianoPal && python3 edge/practice_server.py
```

本機瀏覽器打開 `http://<樹莓派IP>:8900/` 就是選歌畫面。整個練習流程（引導/錄音/評分）都在樹莓派本地跑，本機跟樹莓派之間的網路抖動不影響流程，只影響你看不看得到畫面。

### 方式 B（備案）：dev 機器透過 SSH 遙控樹莓派

樹莓派沒裝評分依賴時用這個——轉譜跟評分在 dev 機器上跑，透過 SSH 啟動樹莓派的燈光引導+錄音、再把錄音抓回來評分：

```bash
# 1. dev 機器上：SSH-based orchestrator（預設連 :8900）
./backend/audio_to_performance/.venv/bin/python3 scripts/session_server.py
# 2. dev 機器上：前端 dev server（vite 會把 /api 等請求 proxy 到 :8900）
cd frontend/viewer && npm install && npm run dev
```

打開 `http://localhost:5173`。前端用同源相對路徑呼叫後端，dev 模式下由 `vite.config.js` 的 proxy 轉發到 session server；如果 session server 不在 `localhost:8900`，用 `SESSION_SERVER=host:port npm run dev` 指定。

### 只看既有結果

如果只是想單純看一份既有的 `result.json`（不透過樹莓派、也不跑任何 server），右上角「Load result.json」可以手動選檔案。

## 語言切換

右上角有個「EN／中文」按鈕，整個介面（含「評語」面板動態產生的建議句子）都有繁簡雙語版本，切換後會存在 localStorage，下次打開記得你上次選的語言。翻譯字典在 `src/i18n.js`（一份不依賴 React 的純資料，`utils/feedback.js` 這種產生動態句子的模組也是直接 import 它來用，不用透過 React context）。

## 畫面看到什麼

**上方摘要卡片**：總分、三個子分數（音高準確率／節奏準確率／節奏穩定度，節奏穩定度目前預設關閉顯示 N/A——見 `backend/scoring/README`／後端說明：這個指標在真人錄音上雜訊太大，不可靠）、全域速度比例（`global_tempo_ratio`），以及各分類（正確/時間偏差/彈錯音/漏彈/多彈）各幾個。

**Notation（五線譜）**：對彈奏者來說比 MIDI 風格的方格圖直觀很多——用真正的高音/低音譜表（右手→高音譜號、左手→低音譜號）畫出每個音符，依小節分行、依評分結果著色（顏色規則跟下面 Piano roll 一致）。音符時值是從 `dur_beats` 量化成最接近的標準音符（四分、八分…），所以節奏複雜的段落畫出來會略為簡化，不是逐拍精確的原始記譜。

**評語**：白話文列出「哪幾小節有什麼問題」，依影響音符數量由多到少排序，例如：

> 第 56-60 小節：明顯搶拍(彈太早)，平均偏差約 90 毫秒，共 95 個音符受影響。

這段文字完全是前端自己算出來的（`src/utils/feedback.js`），把連續、同類型的錯誤小節合併成一個範圍，不需要呼叫任何 AI/後端。

**Piano roll（鋼琴捲軸）**：x 軸是時間、y 軸是 MIDI 音高，灰色直線是小節分界。每個音符依評分結果著色：

| 顏色 | 狀態 | 畫法 |
| --- | --- | --- |
| 綠 | `correct` | 實心色塊，畫在參考位置 |
| 橘 | `timing_off` | 實心色塊，畫在**實際彈奏**的時間點，並標示 ← / → 箭頭與偏差毫秒數 |
| 紅 | `wrong_pitch` | 實心色塊畫在**實際彈到**的音高，虛線連到上方/下方期望音高的位置，兩者都能看到 |
| 灰（空心虛線框） | `missed` | 畫在參考位置，代表「應該有這個音但沒彈」 |
| 紫（菱形） | `extra` | 畫在實際彈奏的位置，用不同形狀跟其他狀態區分「這是多彈出來的」 |

滑鼠移到任一個音符上會跳出提示框，顯示期望音高/時間、實際音高/時間、偏差毫秒數、小節、左右手。（Notation 面板目前沒有做這個 hover 提示——出錯的細節交給「評語」跟 Piano roll 負責。）

**Timing drift over time（下方小圖）**：每個有時間資料的音符，x 軸是它在曲子裡的順序、y 軸是 `offset_ms`。如果這條線整體往下滑，代表使用者演奏中途開始搶拍（越彈越快）；往上滑則是拖拍。

## 顏色從哪裡來

狀態顏色不是隨便挑的，是套用專案內建的 dataviz 色票規則：`correct`/`timing_off`/`wrong_pitch` 對應色票裡保留給「good/warning/critical」狀態用的固定色（不會跟其他圖表的分類色衝突）；`extra` 沒有對應的第四個狀態色，所以借用了分類色票裡最接近紫色的 violet 色階。淺色/深色模式都有對應的數值，寫在 `src/index.css` 的 CSS variables 裡（跟著系統的深色模式設定自動切換）。Notation 面板用 `getComputedStyle` 在畫圖當下讀出這些變數目前解析出來的顏色，所以也會跟著深色模式切換。

## 檔案結構

| 檔案 | 作用 |
| --- | --- |
| `src/App.jsx` | 最外層：`page`(onboarding/home/learn/perform/me) + `view`(setup/live/result，只在 learn/perform 內有意義) 狀態機、檔案選取、姓名狀態(含 localStorage)、把資料分派給各個面板 |
| `src/i18n.js` | 純資料的翻譯字典 + `translate(key, lang, vars)`，不依賴 React，`utils/feedback.js`/`utils/profile.js` 也直接 import |
| `src/LanguageContext.jsx` | 包在 `i18n.js` 外面的 React context/hook(`useTranslation`)，管理目前語言 + localStorage 持久化 |
| `src/components/OnboardingPage.jsx` | 引導頁：逐字打出來的手寫標題動畫、Slogan、姓名輸入框、「進入」按鈕 |
| `src/components/HomePage.jsx` | 主頁：logo(含 Mascot)、近期總結卡片(總練習次數/近期平均分/上次練習/畫像一句話)、學習模式/演奏模式/我的三張導覽卡片、切換使用者連結 |
| `src/components/Mascot.jsx` | 手繪風小人物插圖(純 SVG，之後會換成真的圖片檔)，用在引導頁/主頁 |
| `src/components/Doodles.jsx` | 背景散落的手繪小圖示(星星/愛心/閃光)，只用在資料量少的頁面(引導頁/主頁)，避免干擾資料密集畫面的閱讀 |
| `src/components/icons.jsx` | 共用的極簡線條圖示(燈泡/靶心/循環箭頭/展開箭頭)，`SessionSetup.jsx` 用來標示學習/演奏模式跟各個子區塊 |
| `src/components/MyPage.jsx` | 我的：使用者畫像卡片、分數趨勢圖、練習記錄列表(依模式/曲目篩選、多筆勾選比對)、單筆查看(複用結果視圖)、刪除、匯出 JSON |
| `src/components/TrendChart.jsx` | 分數趨勢折線圖(手刻 SVG，同 PianoRoll/TimingStrip 風格) |
| `src/utils/profile.js` | 從 `profile` 聚合資料算出「新手/進階/熟練」等級 + 一句話畫像文字，HomePage/MyPage 共用 |
| `src/utils/download.js` | 純前端 Blob 下載小工具，匯出功能用 |
| `src/utils/metronome.js` | Web Audio lookahead-scheduler 節拍器 class，不依賴 React，`LiveSession.jsx` 用它在學習模式引導過程中持續播放拍子 |
| `src/components/SessionSetup.jsx` | 學習/演奏模式共用的選歌畫面：姓名輸入框、曲庫清單(來自 session server，含曲目記憶預設)、自行匯入 MIDI、倍速/目標速度選擇；學習模式另有燈光參數(亮度/範圍)跟分段循環練習區塊；開始按鈕，用 `mode` prop 切換文案跟送出的權重模式 |
| `src/components/LiveSession.jsx` | 引導中畫面：輪詢 session 狀態、顯示進度條、跑節拍器；學習模式有變速/暫停/重來/節拍器靜音按鈕，演奏模式只有提前結束(不能中途調速/暫停/重來) |
| `src/components/SummaryPanel.jsx` | 總分/子分數/計數摘要卡片 |
| `src/components/NotationView.jsx` | 用 [VexFlow](https://www.vexflow.com/) 畫的五線譜視圖 |
| `src/components/FeedbackPanel.jsx` | 「評語」文字面板 |
| `src/utils/feedback.js` | 分析錯誤模式(和弦漏彈/特定音高/小節集中/節奏搶拍拖拍)、產生雙語練習建議的邏輯，不是逐音符列表 |
| `src/components/PianoRoll.jsx` | 鋼琴捲軸視覺化 |
| `src/components/TimingStrip.jsx` | 節奏漂移小圖 |
| `src/index.css` | Tailwind 進入點 + 顏色/介面用的 CSS variables(含深色模式、引導頁用的 `--accent` 品牌藍) |

## 已知限制

- `result.json` 沒有拍號資訊，所以 Notation 面板不畫時間記號，也不驗證每小節的拍數是否補滿——單純把每個音符依量化後的時值排進去
- `extra`（多彈的音）沒有參考小節可以對應，Notation 面板會把它們掛在「時間上最接近的前一個音符」所在的小節，只是視覺上的近似安排
- Notation 面板的音符一律用升記號拼寫（不會自動改用降記號），如果樂曲調性偏好用降記號，畫出來的音高沒錯，但拼字不是最直覺的那種
- 目前只支援本機選檔或 `frontend/viewer/public/result.json` 自動載入，沒有做後端 API 串接
- 分段循環練習跟燈光亮度/範圍參數這兩個功能只在本機做過程式邏輯 dry-run（`--no-leds`），實際樹莓派 LED 硬體效果還沒有實機驗證過
