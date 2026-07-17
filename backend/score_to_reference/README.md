# score_to_reference

把一份樂譜（MIDI / MusicXML）轉換成一份**單一、標準化的 JSON 參考答案**，給 AIoT 鋼琴陪練系統的三個下游模組共用：

1. WS2812B LED 指法燈光提示
2. 網頁前端的音符掉落節奏遊戲
3. 節奏 / 音高評分（DTW）

核心設計理念：**拍數（beats）才是唯一真相，秒數只是衍生值**。因為使用者會用節拍器在不同 BPM 下練習，所以每個音符只需要存「第幾拍」，真正播放用的秒數可以隨時針對任何目標速度重新算出來。

---

## 1. 安裝

```bash
cd score_to_reference
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

需要 Python 3.11。相依套件：

- [`music21`](https://www.music21.org/)：解析 MusicXML，能讀出五線譜的譜號、調性、拍號等資訊
- [`pretty_midi`](https://craffel.github.io/pretty-midi/)：解析 MIDI
- [`mido`](https://mido.readthedocs.io/)：`pretty_midi` 的底層依賴

---

## 2. 支援的輸入格式

| 副檔名 | 說明 |
|---|---|
| `.mid`, `.midi` | 標準 MIDI 檔 |
| `.musicxml`, `.xml`, `.mxl` | MusicXML（含壓縮格式 `.mxl`） |
| `.pdf` | **不支援**。會丟出 `OpticalMusicRecognitionNotSupportedError`，提示你先在 MuseScore 裡把 PDF 匯入、辨識後，匯出成 `.musicxml` 或 `.mid` 再轉 |
| 其他任何副檔名 | 丟出 `UnsupportedFormatError` |

---

## 3. 當作 Python 套件使用

### 3.1 `convert(path) -> dict`

後端呼叫的主函式，讀一個檔案路徑，回傳一份可以直接 `json.dumps()` 的 dict。

```python
from backend.score_to_reference import convert

reference = convert("我的樂譜.musicxml")
print(reference["title"], reference["tempo_bpm"], len(reference["notes"]))
```

### 3.2 `to_seconds(reference, bpm) -> dict`

使用者要用其他速度（例如節拍器設 90 BPM）練習時，用這個函式重新算出所有音符的秒數，**不會改到原本傳進去的 reference**（回傳的是深拷貝）。

```python
from backend.score_to_reference import convert, to_seconds

reference = convert("我的樂譜.musicxml")     # 樂譜原始速度，例如 120 bpm
slow_practice = to_seconds(reference, bpm=60)  # 慢一半速度練習
# slow_practice 裡每個音符的 onset_sec / dur_sec 都變成原本的兩倍
```

原理很單純：`秒 = 拍數 × 60 / bpm`，所以速度加倍、秒數就直接減半，跟樂譜原本有沒有變速無關。

### 3.3 `save_to_db(reference)`

目前是**尚未實作的 stub**，呼叫會直接丟 `NotImplementedError`。要接上真正的後端資料庫時，打開 [`db.py`](db.py)，把裡面標示 `TODO(backend)` 的地方換成實際的 SQLAlchemy model / session import，再照著檔案內附的範例程式碼實作 insert 邏輯。

### 3.4 例外處理

```python
from backend.score_to_reference import (
    convert,
    UnsupportedFormatError,
    OpticalMusicRecognitionNotSupportedError,
    ScoreParsingError,
)

try:
    reference = convert(path)
except OpticalMusicRecognitionNotSupportedError:
    print("請先用 MuseScore 匯出 .musicxml 或 .mid")
except UnsupportedFormatError:
    print("副檔名不支援")
except ScoreParsingError as e:
    print(f"檔案格式對，但內容解析失敗：{e}")
```

---

## 4. 命令列（CLI）使用

```bash
# 轉換並印到終端機
python -m backend.score_to_reference 我的樂譜.musicxml

# 轉換並存成檔案
python -m backend.score_to_reference 我的樂譜.musicxml -o ref.json

# 轉換同時換算成指定練習速度（例如 90 bpm）
python -m backend.score_to_reference 我的樂譜.mid -o ref.json --bpm 90
```

失敗時會印 `Error: ...` 到 stderr，並回傳 exit code 1（可用於 shell script 判斷成功與否）。

---

## 5. 輸出 JSON 結構

```jsonc
{
  "title": "Maple Leaf Rag",
  "tempo_bpm": 100,
  "tempo_map": [{"beat": 0.0, "bpm": 100.0}],   // 若樂譜中途變速，這裡會有多筆
  "time_signature": "2/4",
  "key": "A- major",
  "duration_beats": 168.5,                        // 全曲總拍數（衍生秒數用的來源）
  "duration_sec": 101.1,                           // = duration_beats 換算出來的秒數
  "notes": [
    {
      "pitch": 60,            // MIDI 音高編號 (0-127)
      "name": "C4",           // 音名 + 八度
      "onset_beats": 0.0,     // 從第幾拍開始（與速度無關，這是「唯一真相」）
      "onset_sec": 0.0,       // 依 tempo_bpm 算出來的秒數（衍生值）
      "dur_beats": 1.0,       // 音符長度，以拍為單位
      "dur_sec": 0.5,         // 音符長度，以秒為單位（衍生值）
      "velocity": 80,         // 力度 0-127
      "hand": "R",            // "R" = 右手/高音譜號，"L" = 左手/低音譜號
      "measure": 1            // 第幾小節
    }
  ]
}
```

`notes` 保證依 `(onset_beats, pitch)` 排序，所以同一份樂譜每次轉換出來的音符順序都一樣（deterministic），方便 DTW 比對或做差異測試。

### 左右手（hand）怎麼判斷？

- **MusicXML**：優先看該聲部的譜號（Clef）——高音譜號 → `R`，低音譜號 → `L`；如果完全沒有譜號資訊，就用聲部順序（第一聲部 `R`，其餘 `L`）當備援
- **MIDI**：MIDI 本身沒有譜號概念，只能用「第幾軌」猜——第 0 軌 `R`，其餘 `L`。如果來源 MIDI 的軌道順序跟左右手對不上，這個欄位可能不準，需要人工確認

---

## 6. 執行測試

```bash
cd score_to_reference
source .venv/bin/activate
python -m pytest tests -v
```

測試會用 `music21` **現場產生**一份極簡雙手小樂譜（不需要任何外部檔案），驗證：

- 音高 / 起始拍點抽取是否正確
- 拍數 → 秒數的換算（在原始樂譜速度下）
- 換速（`to_seconds`）：BPM 加倍時 `onset_sec` 是否正確減半
- 左右手標記（透過譜號）
- 音符排序是否具決定性（deterministic）
- PDF 輸入 / 不支援副檔名的錯誤是否正確拋出

---

## 7. 檔案結構速查

| 檔案 | 作用 |
|---|---|
| `__init__.py` | 套件對外介面：匯出 `convert` / `to_seconds` / `save_to_db` 與各種錯誤類別 |
| `errors.py` | 型別化錯誤定義 |
| `musicxml_parser.py` | 用 music21 解析 MusicXML，抽出音符、譜號、調性、拍號、速度 |
| `midi_parser.py` | 用 pretty_midi 解析 MIDI，抽出音符與速度變化 |
| `core.py` | `convert()` 與 `to_seconds()` 主邏輯：整合兩種 parser 的輸出、排序、拍數↔秒數換算 |
| `db.py` | `save_to_db()` stub，等待接上真正後端 DB |
| `__main__.py` | CLI 入口（`python -m backend.score_to_reference ...`） |
| `requirements.txt` | 相依套件清單 |
| `tests/` | pytest 測試，現場產生測試樂譜 |

---

## 8. 已知限制

- PDF 樂譜完全不支援光學辨識（OMR），需要先用 MuseScore 轉出 `.musicxml`/`.mid`
- MIDI 檔的左右手標記是用軌道順序猜的，不保證準確
- `save_to_db()` 尚未接上真正的資料庫，目前呼叫必定丟例外
