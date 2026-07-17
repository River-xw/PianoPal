# scoring

把使用者彈的東西（一串音符）拿去跟 [score_to_reference](../score_to_reference) 產生的「正確答案」JSON 做比對，算出彈得準不準、準時不準時，回傳一份結構化的評分結果。

假設是**理想、零延遲環境**：沒有感測器、沒有 onset 偵測，使用者彈奏出來的就是一份乾淨、精準的音符清單（就像直接從 MIDI 鍵盤錄下來的一樣）。所以這整個模組做的事情，本質上是「符號音樂對齊」（symbolic music alignment）——用 DTW/edit-distance 把兩串音符對起來，而不是處理音訊或做 onset detection。

---

## 1. 核心設計：為什麼要「先抓整體速度差，再看個別音符」

使用者練琴時常常會「整首都彈快了」或「整首都彈慢了」——這不是錯誤，只是選了不同的節拍器速度。如果不處理這件事，一個彈得很穩、只是速度不同的演奏，會被誤判成每個音都遲到或搶拍。

所以評分分兩層：

1. **全域節奏（global tempo）**：先找出「大致對得上」的音符，用穩健回歸（Theil-Sen，不是普通最小平方法，才不會被少數幾個抓錯的音符帶偏）算出一條 `perf_onset ≈ global_tempo_ratio × ref_onset + offset` 的關係。這個 `global_tempo_ratio` 代表使用者整體彈得比參考快還是慢。
2. **局部誤差（local error）**：把上面那條關係「扣掉」之後剩下的殘差，才是每個音符真正的「搶拍/拖拍」誤差（`offset_ms`）。

如果你已經知道使用者是對著哪個 BPM 的節拍器彈的（`target_bpm`），就不用猜測全域速度了——直接把參考樂譜換算到那個 BPM（用 `backend.score_to_reference.to_seconds`），殘差就是絕對值，不做回歸。

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
cd PianoPal/          # 倉庫根目錄，不是 cd backend/scoring/
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
print(result.summary.sub_scores)     # {"pitch":.., "rhythm":.., "timing_stability":..}
print(result.summary.global_tempo_ratio)  # 例如 0.95 = 整體彈快了一點
```

如果使用者是對著已知 BPM 的節拍器彈的：

```python
result = score_performance(reference, performance, target_bpm=90)
```

自訂門檻/權重全部集中在 `ScoringConfig`（不用改程式碼）：

```python
config = ScoringConfig(tol_ms=30, w_pitch=3.0)   # 容忍度收緊到 30ms，音高錯誤的懲罰加重
result = score_performance(reference, performance, config=config)
```

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
      "rhythm": 78.57,              // 節奏準確率
      "timing_stability": 64.1      // 節奏穩定度
    },
    "global_tempo_ratio": 0.95,     // 整體速度比例；target_bpm 有給的話這裡是 null
    "tempo_trend": "accelerating",  // accelerating(越彈越快) / steady / decelerating
    "counts": {"correct": 11, "timing_off": 3, "wrong_pitch": 1, "missed": 1, "extra": 1}
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
- **rhythm accuracy** = correct ÷ (correct + timing_off) × 100 —— 音高對的音符裡，時間點準的比例
- **timing stability** = 100 ÷ (1 + std(offset_ms) / tol_ms) —— 誤差標準差=0 時是100分，標準差=容忍度時是50分
- **overall** = 三個子分數的加權平均（權重在 `ScoringConfig`）

### status / timing 分類邏輯

| status | 意思 |
|---|---|
| `correct` | 對齊成功、音高對、時間在容忍度內 |
| `timing_off` | 對齊成功、音高對，但時間點超出容忍度（`timing`欄位會標 `rush`搶拍或`drag`拖拍）|
| `wrong_pitch` | 對齊成功但音高不對——**不會**被拆成「漏彈+多彈」兩筆，而是保留成一筆「彈錯」|
| `missed` | 參考樂譜裡有、但使用者沒彈的音 |
| `extra` | 使用者彈了、但參考樂譜裡沒有對應的音 |

---

## 6. 和弦/複音怎麼處理

`chord_window_sec`（預設 30ms）內的音符會被視為同一個「事件」，並且**依音高排序**後才拿去比對——這樣就算使用者彈和弦時手指落下的順序跟參考不同，或輸入的音符清單順序不同，也不會被誤判成音高錯誤或漏彈/多彈。細節在 `align.py` 開頭的說明。

---

## 7. 執行測試

```bash
cd 學習用/
source score_to_reference/.venv/bin/activate   # 或你自己裝好依賴的環境
python -m pytest scoring/tests -v
```

11 個測試涵蓋：滿分演奏、整體變速被正確吸收、雜訊越大分數越低、局部搶拍被抓到、刪除/插入/改音高分別對應 missed/extra/wrong_pitch、搶拍與拖拍等量對稱扣分、輸出決定性（同輸入同輸出）、和弦比對。

---

## 8. 檔案結構速查

| 檔案 | 作用 |
|---|---|
| `align.py` | 核心比對邏輯：事件分組、穩健全域速度回歸（Theil-Sen）、兩階段 DTW |
| `score.py` | 把對齊結果轉成 status/timing 分類，算出三個子分數與總分 |
| `config.py` | 所有門檻/權重集中在 `ScoringConfig` 一個 dataclass |
| `models.py` | 輸出用的 dataclass（`NoteResult`、`ScoringSummary`、`ScoringResult`） |
| `midi_io.py` | `midi_to_performance()`：把 MIDI 錄音轉成 performance.json 格式 |
| `cli.py` / `__main__.py` | `python -m backend.scoring ...` |
| `tests/` | pytest，全部用手寫的小型 reference dict，不需要外部檔案 |

## 9. 已知限制

- 依賴同層的 `score_to_reference` 套件（見第 2 節的工作目錄注意事項），不是獨立可安裝的套件
- 沒有處理任何音訊/感測器層面的東西——上游必須先把演奏轉成乾淨的符號音符清單
- DTW 是 O(N×M) 全表計算，對非常長的曲子（數千個音符以上）會變慢；目前沒有做band-限制的優化
