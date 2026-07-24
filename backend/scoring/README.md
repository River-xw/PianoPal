# scoring

把使用者彈的東西（一串音符）拿去跟 [score_to_reference](../score_to_reference) 產生的「正確答案」JSON 做比對，算出彈得準不準、準時不準時，回傳一份結構化的評分結果。

假設是**理想、零延遲環境**：沒有感測器、沒有 onset 偵測，使用者彈奏出來的就是一份乾淨、精準的音符清單（就像直接從 MIDI 鍵盤錄下來的一樣）。所以這整個模組做的事情，本質上是「符號音樂對齊」（symbolic music alignment）——用 DTW/edit-distance 把兩串音符對起來，而不是處理音訊或做 onset detection。

---

## 1. 核心設計：為什麼要「先抓節奏曲線，再看個別音符」

使用者練琴時常常會「整首都彈快了/慢了」，或是「彈到一半速度變了」（rubato、彈到熟悉的段落加速…）——這些都不是錯誤，只是選了不同的節奏。如果不處理這件事，一個彈得很穩、只是速度不同（或中途變速）的演奏，會被誤判成每個音都遲到或搶拍。

所以評分分兩層：

1. **節奏曲線（tempo curve）**：先用一輪粗略的「音高優先」DTW 找出「音高確實對得上」的音符當錨點，再用穩健回歸（Theil-Sen，不是普通最小平方法，才不會被少數幾個抓錯的音符帶偏）在這些錨點上分段（滑動視窗，`tempo_window_notes`/`tempo_window_step`）擬合出一條**分段線性**的節奏曲線（`align.TempoCurve`），而不是單一一條全域直線。這樣真的中途變速（rubato、彈熟的段落加速）會被曲線吸收掉，不會被硬套一條全域直線後產生一堆虛假的殘差。`global_tempo_ratio`（回傳給前端顯示的那個數字）是所有錨點的整體穩健回歸斜率，純粹給人看整體快慢用；實際拿來分類每個音符對錯的，是這條曲線在該處的局部預測值，不是這個單一數字。
2. **局部誤差（local error）**：每個音符實際彈奏時間，減掉節奏曲線在該處的預測值，剩下的殘差才是這個音符真正的「搶拍/拖拍」誤差（`offset_ms`）。

如果你已經知道使用者是對著哪個 BPM 的節拍器彈的（`target_bpm`），就不用擬合節奏曲線了——直接把參考樂譜換算到那個 BPM（用 `backend.score_to_reference.to_seconds`），殘差就是絕對值，不做回歸（`global_tempo_ratio` 這時是 `null`）。

---

## 2. 安裝

```bash
cd scoring
python3 -m venv .venv   # 或沿用 score_to_reference/.venv，兩個套件裝在同一個環境更方便
source .venv/bin/activate
pip install -r requirements.txt
```

**重要**：`backend.scoring` 依賴 `backend.score_to_reference`（用來呼叫 `to_seconds`）。執行時的**工作目錄**請放在倉庫根目錄，這樣 `import backend.score_to_reference` 才找得到路徑：

```bash
cd <repo根目錄>          # 不是 cd backend/scoring/
python -m backend.scoring ...
```

---

## 3. 當作 Python 套件使用

```python
from backend.scoring import score_performance, ScoringConfig
import json

reference = json.load(open("reference.json"))      # score_to_reference 產生的 JSON
performance = json.load(open("performance.json"))    # 使用者彈的音符清單

result = score_performance(reference, performance)
print(result.summary.score)          # 0-100 總分
print(result.summary.sub_scores)     # {"pitch":.., "rhythm":.., "timing_stability":.., "hand_shape":..}
print(result.summary.global_tempo_ratio)  # 例如 0.95 = 整體彈快了一點（target_bpm 有給的話是 None）
```

如果使用者是對著已知 BPM 的節拍器彈的：

```python
result = score_performance(reference, performance, target_bpm=90)
```

自訂門檻/權重全部集中在 `ScoringConfig`（不用改程式碼）。**注意兩組容易混淆的欄位**：`w_pitch`/`w_time`/`gap_penalty` 是 DTW **對齊**的成本函數（決定哪個演奏音符對應哪個參考音符），跟 `score_weight_pitch` 這組**評分**權重（決定總分怎麼加權三/四個子分數）是完全不同的兩件事：

```python
config = ScoringConfig(
    tol_ms=30,                      # 分類容忍度收緊到 30ms
    score_weight_pitch=0.5,         # 總分裡「音高準確率」的權重
    score_weight_hand_shape=0.25,   # 開啟手型評分維度（見第 5 節）
)
result = score_performance(reference, performance, config=config, hand_shape_score=92.0)
```

其他值得知道的 `ScoringConfig` 選項：

- `tol_beat`：用「幾分之幾拍」而不是固定毫秒數當容忍度（例如 `1/16`），會依當下 BPM 換算成有效的 `tol_ms`（`effective_tol_ms()`）；給了就會蓋過 `tol_ms`。
- `ignore_timing`：設 `True` 直接整個關掉節奏這個維度——音高對就一律是 `correct`（不會有 `timing_off`），`offset_ms`/`timing`都是 `None`，`timing_stability` 也不計算，總分只剩音高+節奏準確率兩項（權重自動重新正規化成加總 1.0）。拿真人麥克風錄音診斷「音高/轉譜準不準」時很好用——演奏者天生的節奏彈性不然會蓋過真正想看的問題。
- `suppress_harmonic_extras`（預設開）：麥克風轉譜常常在正確音符的高八度/高八度+五度/高兩個八度同時聽到一個泛音假訊號，被判成「多彈」——這個選項會在對齊**之後**（只動已經被分類成 `extra` 的音符，不可能誤刪真正對上參考譜的音符）把這類泛音雜訊濾掉，被濾掉的數量記在 `summary.harmonic_extras_removed`。

### 從 MIDI 錄音產生 performance.json

```python
from backend.scoring import midi_to_performance

performance = midi_to_performance("使用者錄音.mid")
```

---

## 4. CLI

```bash
python -m backend.scoring reference.json performance.json -o result.json
python -m backend.scoring reference.json performance.json -o result.json --bpm 90
```

---

## 5. 輸出結構（result.json）

```jsonc
{
  "summary": {
    "score": 77.19,                 // 總分 0-100
    "sub_scores": {
      "pitch": 82.35,               // 音高準確率
      "rhythm": 78.57,              // 節奏準確率（已依音高覆蓋率打折，見下方公式）
      "timing_stability": 64.1,     // 節奏穩定度（同樣已依覆蓋率打折）；權重=0 時是 null，不是 0
      "hand_shape": null            // 手型/姿勢評分；沒有外部傳入分數或權重=0 時是 null
    },
    "global_tempo_ratio": 0.95,     // 整體速度比例；target_bpm 有給的話這裡是 null
    "tempo_trend": "accelerating",  // accelerating(越彈越快) / steady / decelerating
    "counts": {"correct": 11, "timing_off": 3, "wrong_pitch": 1, "missed": 1, "extra": 1},
    "harmonic_extras_removed": 2,        // 被濾掉的泛音假訊號數量（見第 3 節 suppress_harmonic_extras）
    "octave_slips_in_wrong_pitch": 1      // wrong_pitch 裡剛好差整數個八度的數量（常是轉譜的八度誤判）
  },
  "notes": [
    {
      "ref_index": 2, "perf_index": 2,
      "pitch_ref": 64, "pitch_perf": 63,       // 應該彈 64，實際彈了 63
      "name": "E4",
      "onset_ref_sec": 1.2, "onset_perf_sec": 1.14,
      "offset_ms": 0.0,
      "status": "wrong_pitch",                  // 見下方分類說明
      "timing": "accurate",                     // 音高錯了，但時間點是準的
      "measure": 1, "hand": "R",
      "dur_beats": 1.0                          // 來自參考樂譜的音符長度（拍）；extra 音符沒有這個值
    }
  ]
}
```

`dur_beats` 是給 `viewer` 畫五線譜用的（要知道畫四分音符還是八分音符）。只有 `correct`/`timing_off`/`wrong_pitch`/`missed`（都有對應的參考音符）會帶這個值；`extra` 音符沒有參考答案可以對，這個欄位會是 `null`。

### 分數公式（都寫在 `score.py` 的 docstring 裡，這裡摘要）

- **pitch accuracy** = (correct + timing_off) ÷ (correct+timing_off+wrong_pitch+missed+extra) × 100 —— 有彈對音高的比例
- **rhythm accuracy** = pitch_accuracy × correct ÷ (correct + timing_off) —— 音高對的音符裡時間點準的比例，再乘上 pitch_accuracy 做覆蓋率修正，這樣「漏彈大半首、剩下幾個音卡得很準」不會被打成節奏滿分
- **timing stability** = pitch_accuracy × [100 ÷ (1 + std(offset_ms) / tol_ms)] —— 同樣先算誤差標準差=0時是100分、標準差=容忍度時是50分，再乘上 pitch_accuracy 做覆蓋率修正；`score_weight_timing_stability=0`（預設）時整個不計算，回傳 `null`
- **hand_shape** —— 完全是外部傳入的分數（`score_performance(..., hand_shape_score=...)`），這個模組本身不碰任何感測器/影像；`score_weight_hand_shape=0`（預設）或沒有傳入分數時回傳 `null`。目前唯一會真的算出非 `null` 分數餵進來的呼叫端是 `edge/practice_server.py`（見該模組說明的 IMU 姿勢分類器整合）
- **overall** = 對「當下實際可用」的子分數做**重新正規化**的加權平均——`timing_stability`/`hand_shape` 為 `null`（維度關閉，或該次感測不可用）時，不是直接當 0 分貢獻拖低總分，而是把它的權重份額從分母中移除、其餘子分數的權重按比例放大湊回 1.0。例如手型感測器沒接上、其餘三項都滿分，`overall` 依然是 100，而不是被扣掉 `score_weight_hand_shape` 那一份權重

### status / timing 分類邏輯

| status | 意思 |
|---|---|
| `correct` | 對齊成功、音高對、時間在容忍度內 |
| `timing_off` | 對齊成功、音高對，但時間點超出容忍度（`timing`欄位會標 `rush`搶拍或`drag`拖拍）|
| `wrong_pitch` | 對齊成功但音高不對——**不會**被拆成「漏彈+多彈」兩筆，而是保留成一筆「彈錯」|
| `missed` | 參考樂譜裡有、但使用者沒彈的音 |
| `extra` | 使用者彈了、但參考樂譜裡沒有對應的音（扣掉被判定是泛音假訊號、已經被濾掉的那些） |

---

## 6. 和弦/複音怎麼處理

`chord_window_sec`（預設 30ms）內的音符會被視為同一個「事件」，並且**依音高排序**後才拿去比對——這樣就算使用者彈和弦時手指落下的順序跟參考不同，或輸入的音符清單順序不同，也不會被誤判成音高錯誤或漏彈/多彈。細節在 `align.py` 開頭的說明。

---

## 7. 執行測試

```bash
cd 學習用/
source backend/audio_to_performance/.venv/bin/activate   # 或你自己裝好依賴的環境
python -m pytest backend/scoring/tests -v
```

21 個測試（`test_scoring.py` + `test_tempo_curve.py`）涵蓋：滿分演奏、整體變速被正確吸收、中途變速（rubato）被分段節奏曲線吸收而非累積成假殘差、雜訊越大分數越低、局部搶拍被抓到、刪除/插入/改音高分別對應 missed/extra/wrong_pitch、搶拍與拖拍等量對稱扣分、輸出決定性（同輸入同輸出）、和弦比對、`tol_beat` 換算、`ignore_timing` 關閉節奏維度後的權重重新正規化。

---

## 8. 檔案結構速查

| 檔案 | 作用 |
|---|---|
| `align.py` | 核心比對邏輯：事件分組、分段穩健節奏曲線擬合（`fit_tempo_curve`/`TempoCurve`）、兩階段 DTW |
| `score.py` | 把對齊結果轉成 status/timing 分類，算出子分數與總分，泛音假訊號過濾（`_suppress_harmonic_extras`） |
| `config.py` | 所有門檻/權重集中在 `ScoringConfig` 一個 dataclass |
| `models.py` | 輸出用的 dataclass（`NoteResult`、`ScoringSummary`、`ScoringResult`） |
| `midi_io.py` | `midi_to_performance()`：把 MIDI 錄音轉成 performance.json 格式 |
| `cli.py` / `__main__.py` | `python -m backend.scoring ...` |
| `tests/` | pytest，全部用手寫的小型 reference dict，不需要外部檔案 |

## 9. 已知限制

- 依賴同層的 `score_to_reference` 套件（見第 2 節的工作目錄注意事項），不是獨立可安裝的套件
- 沒有處理任何音訊/感測器層面的東西——上游必須先把演奏轉成乾淨的符號音符清單；`hand_shape` 也是純粹接收外部分數，不做任何姿勢推論
- DTW 是 O(N×M) 全表計算，對非常長的曲子（數千個音符以上）會變慢；目前沒有做band-限制的優化
