# viewer

給 [backend.scoring](../../backend/scoring) 模組輸出的 `result.json` 用的網頁檢視器，也是「選歌→燈光引導+錄音→自動評分」整個練習流程的前端。

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

## 姓名分開存檔

首頁「開始練習」畫面多了一個姓名輸入框——這個名字會隨著 `POST /api/session/start` 一起送出，後端（`edge/practice_server.py`／`scripts/session_server.py`）評分完成後除了照舊寫一份到共用的 `result.json`（誰最後測都會蓋過去，純粹方便當下直接看），也會另外存一份到 `data/session_scratch/results/<姓名>.json`，之後要看「某人最近一次的評分」就用 `GET /api/results/<姓名>`（前端「查看最近評分結果」按鈕背後就是打這支）——不同人不會互相覆蓋彼此的紀錄。姓名會存在瀏覽器的 localStorage，重新整理頁面也不會忘記你是誰。

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
| `src/App.jsx` | 最外層：`setup`/`live`/`result` 三態狀態機、檔案選取、姓名狀態(含 localStorage)、把資料分派給各個面板 |
| `src/i18n.js` | 純資料的翻譯字典 + `translate(key, lang, vars)`，不依賴 React，`utils/feedback.js` 也直接 import |
| `src/LanguageContext.jsx` | 包在 `i18n.js` 外面的 React context/hook(`useTranslation`)，管理目前語言 + localStorage 持久化 |
| `src/components/SessionSetup.jsx` | 首頁選歌畫面：姓名輸入框、曲庫清單(來自 session server)、自行匯入 MIDI、倍速選擇、開始按鈕、依姓名查詢「查看最近評分結果」 |
| `src/components/LiveSession.jsx` | 引導中畫面：輪詢 session 狀態、顯示進度條、變速/暫停/重來/提前結束按鈕 |
| `src/components/SummaryPanel.jsx` | 總分/子分數/計數摘要卡片 |
| `src/components/NotationView.jsx` | 用 [VexFlow](https://www.vexflow.com/) 畫的五線譜視圖 |
| `src/components/FeedbackPanel.jsx` | 「評語」文字面板 |
| `src/utils/feedback.js` | 分析錯誤模式(和弦漏彈/特定音高/小節集中/節奏搶拍拖拍)、產生雙語練習建議的邏輯，不是逐音符列表 |
| `src/components/PianoRoll.jsx` | 鋼琴捲軸視覺化 |
| `src/components/TimingStrip.jsx` | 節奏漂移小圖 |
| `src/index.css` | Tailwind 進入點 + 顏色/介面用的 CSS variables(含深色模式) |

## 已知限制

- `result.json` 沒有拍號資訊，所以 Notation 面板不畫時間記號，也不驗證每小節的拍數是否補滿——單純把每個音符依量化後的時值排進去
- `extra`（多彈的音）沒有參考小節可以對應，Notation 面板會把它們掛在「時間上最接近的前一個音符」所在的小節，只是視覺上的近似安排
- Notation 面板的音符一律用升記號拼寫（不會自動改用降記號），如果樂曲調性偏好用降記號，畫出來的音高沒錯，但拼字不是最直覺的那種
- 目前只支援本機選檔或 `frontend/viewer/public/result.json` 自動載入，沒有做後端 API 串接
