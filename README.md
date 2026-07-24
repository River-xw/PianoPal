# PianoPal

PianoPal 是一個鋼琴陪練/評分系統：一台 37 鍵電子琴（BF-3738C）+ WS2812 燈條做即時按鍵引導，麥克風錄音拿去跟樂譜比對算出音準/節奏分數，選配的手腕 IMU 感測器可以額外算一個手型/姿勢分數，全部整合在一個網頁前端裡。

## 核心體驗

前端（`frontend/viewer/`）是整個系統的入口，架構是：

```text
引導頁（姓名 + Slogan）
  -> 主頁（近期總結 + 三張導覽卡片）
      ├ 學習模式：選歌 -> 燈光引導 + 錄音 -> 寬鬆評分報告（存入歷史）
      ├ 演奏模式：選歌 -> 無燈光、只錄音 -> 嚴格評分報告（存入歷史）
      └ 我的：歷史紀錄列表、使用者畫像、分數趨勢圖、多筆比對、匯出
```

學習模式跟演奏模式**共用同一套評分引擎**（`backend.scoring`），差別純粹是權重參數（見下方評分演算法）跟要不要點燈。細節見 [frontend/viewer/README.md](frontend/viewer/README.md)。

## Current Data Flow

```text
POST /api/session/start（樹莓派原生 orchestrator：edge/practice_server.py）
  -> ws2812_guide_song.py：LED 引導 + 麥克風錄音（演奏模式用 --no-leds）
  -> posture_capture.py（選配，需要 BLE IMU 感測器才會啟動）：即時手型姿勢分類 -> 一個 0-100 分數
  -> scripts/grade_audio_reference_constrained.py
       -> backend.audio_to_performance（麥克風錄音 -> 音符清單，reference-dtw 模式吸收真人節奏浮動）
       -> backend.scoring（符號音樂對齊 + 評分公式，見下方）
  -> data/session_scratch/results/<使用者>/<session_id>.json + backend.db.sqlite（practice_sessions 表）
  -> GET /api/history, /api/history/<id> 給前端「我的」頁面
```

沒有裝評分依賴的樹莓派可以用 `scripts/session_server.py`（SSH 遙控備案）取代 `edge/practice_server.py`，跑在開發機上、透過 SSH 遙控樹莓派的燈光引導+錄音。

## 評分演算法（目前驗證過的版本）

`backend.scoring` 做的是「符號音樂對齊」——把參考樂譜跟實際彈奏的音符清單，用兩階段 DTW 對齊起來：

1. 先用一輪音高優先的粗略對齊找出「確實彈對音高」的錨點，在這些錨點上用穩健回歸（Theil-Sen）分段擬合一條**分段線性節奏曲線**，吸收使用者整體變速或中途變速（rubato）——不會被誤判成每個音都搶拍/拖拍。
2. 再用真正的對齊成本函數做第二輪 DTW，把每個演奏音符跟參考音符配對，分類成 `correct`/`timing_off`/`wrong_pitch`/`missed`/`extra`。

總分是最多四個子分數的加權平均：

| 子分數 | 公式 | 說明 |
| --- | --- | --- |
| 音準（pitch） | (correct+timing_off) / 全部 × 100 | 音高彈對的比例 |
| 節奏（rhythm） | 音準 × correct/(correct+timing_off) | 音高對的裡面，時間點準的比例，再乘音準做覆蓋率修正 |
| 節奏穩定度（timing_stability） | 音準 × 100/(1+std(offset_ms)/tol_ms) | 預設權重 0，不計算/不顯示——真人麥克風錄音上雜訊太大不可靠 |
| 手型（hand_shape） | 外部傳入(IMU 姿勢分類器) | 這個模組本身不做任何感測——見下方 |

學習模式（寬鬆：音準/手型權重高、節奏均勻度不計）跟演奏模式（嚴格：三者均衡）**用同一個評分函式**，只是 `edge/practice_server.py`/`scripts/session_server.py` 的 `MODE_SCORE_WEIGHTS` 傳不同的權重進去。詳細公式、`tol_beat`/`ignore_timing`/泛音假訊號過濾等選項，見 [backend/scoring/README.md](backend/scoring/README.md)。

**手型評分**：`edge/practice_server.py` 有設定 BLE IMU 裝置時，`edge/posture_capture.py` 會即時分類手型姿勢、把「正常姿勢時間窗比例」換算成分數；沒裝硬體就自動退回固定佔位值，不擋練習流程。分類器本身（`edge/raspi_runtime/posture.py`）跟訓練資料/腳本見 [backend/sensors/README.md](backend/sensors/README.md)。

## Repository Structure

```text
.
├── backend/                 # Python 函式庫：樂譜解析、音訊轉譜、評分、驗證
│   ├── audio_to_performance/ # 麥克風錄音 -> 演奏音符清單（reference-dtw 對齊麥克風音準轉錄）
│   ├── score_to_reference/   # MusicXML/MIDI 樂譜 -> 標準化參考 JSON
│   ├── scoring/               # 參考 vs 演奏比對 -> result.json（詳見上方演算法說明）
│   ├── db/                    # 本地 SQLite 索引（使用者/曲目/練習紀錄/檔案路徑）
│   ├── sensors/               # IMU 封包格式、CSV 解析、關鍵時間窗切割
│   └── validation/            # 轉譜品質的往返驗證
├── camera_evidence/         # 用鏡頭看指尖位置，當作解決音準轉譜八度誤判的第二證據來源（目前沒有鏡頭硬體，只用合成資料測過）
├── edge/                    # 裝置端/樹莓派程式碼
│   ├── practice_server.py    # 前端實際在用的樹莓派原生 orchestrator（LED 引導+錄音+評分+歷史）
│   ├── ws2812_guide_song.py  # WS2812 燈條引導 + 錄音
│   ├── posture_capture.py    # 練習期間的即時手型姿勢評分 subprocess
│   ├── microbit_rpi_comm/    # micro:bit BLE 韌體 + 樹莓派 BLE 接收端
│   └── raspi_runtime/        # 獨立的感測器/音訊「採集」runtime，用來收集姿勢分類器的訓練資料
├── experiments/             # 校準跟一次性實驗
│   ├── latency_test/          # 麥克風延遲/節奏驗證
│   └── benchmarks/            # 樹莓派硬體效能測試
├── frontend/
│   └── viewer/                # Vite + React：整個練習流程的前端（見上方核心體驗）
├── models/                  # 訓練好的手型姿勢分類器
├── data/                    # 本地資料集、SQLite、練習錄音/結果暫存
├── docs/                    # 曲庫 MIDI、架構筆記、錄音驗證指南
└── scripts/                 # 開發者用的包裝腳本（評分、訓練、驗證）
```

## Useful Commands

用真人錄音驗證評分算法準不準（給不熟這個專案的組員用的一鍵腳本，見 [docs/VALIDATION_GUIDE.md](docs/VALIDATION_GUIDE.md)）：

```bash
./scripts/validate_recording.sh
```

跑目前的正式評分流程（樂譜 + 錄音 -> 評分結果，`reference-dtw` 模式）：

```bash
python3 scripts/grade_audio_reference_constrained.py reference.mid recording.wav \
  --keyboard-profile data/bf3738c_keybank/bf3738c_white_profile.json --white-keys-only \
  -o result.json
```

樂譜轉成參考 JSON：

```bash
python -m backend.score_to_reference score.musicxml -o reference.json
```

單純評分（reference.json + performance.json，不經過音訊轉譜）：

```bash
python -m backend.scoring reference.json performance.json -o result.json
```

啟動樹莓派原生 orchestrator（前端實際會連的那個）：

```bash
python3 edge/practice_server.py
```

啟動前端（dev 模式，透過 SSH 備案 orchestrator）：

```bash
cd frontend/viewer
npm install
npm run dev
```

各模組更完整的指令/CLI 參數說明，見對應資料夾的 README。

## Notes For Future Work

- Raspberry Pi 跟 micro:bit 採集端程式碼放 `edge/` 底下。
- 訓練好的模型檔案放 `models/` 底下。
- 可重用的後端流程放 `backend/` 底下；`experiments/` 是一次性腳本，不要被其他模組 import。
- 本機裝置設定（BLE MAC 位址等）放在 `.gitignore` 排除的檔案裡，例如 `edge/microbit_rpi_comm/raspberry/config.json`。
- 手型評分目前只接了 `edge/practice_server.py`；`scripts/session_server.py`（SSH 備案）還沒接，因為 BLE 只存在樹莓派端，備案需要多一層「錄完 IMU 資料再抓回開發機」的邏輯才能接上。
