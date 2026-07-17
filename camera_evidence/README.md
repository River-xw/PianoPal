# camera_evidence

用鏡頭看到的「指尖在哪個琴鍵上」，當作跟音訊完全獨立的第二證據來源，去解決 `audio_to_performance`/basic-pitch 的**八度誤判**問題。

## 為什麼需要這個模組

音訊本身有個先天模糊性：一個音符跟它高八度、完全五度的泛音，在頻譜上長得很像，basic-pitch 偶爾會把泛音誤判成主音（或反過來）。`validation/roundtrip.py` 已經證實這個問題確實存在（詳見該模組的驗證報告）。

但物理上的琴鍵位置完全沒有這個模糊性——C4 跟 C5 是鍵盤上兩個不重疊的像素區域，鏡頭看到手指壓在哪裡，不會有「泛音」這種東西。所以：音訊負責「什麼時候彈了、聽起來是哪個音」，鏡頭負責「這個時間點手指壓在哪個鍵上」，兩者對不上的時候，鏡頭的空間證據可以幫忙判斷音訊到底是不是八度誤判。

**目前沒有鏡頭硬體**，所以這個模組完全用合成的指尖位置資料開發跟測試（`SyntheticFingertipSource`），等硬體到了再接上真的 MediaPipe 手部偵測（`MediaPipeFingertipSource`，目前只是一個會丟 `NotImplementedError` 的 stub）。

## 範圍：只做「這個時間點手指在哪」，不做「有沒有按下去」

鏡頭**不**負責偵測按鍵的 onset 時間點——那個仍然由音訊/IMU 負責。鏡頭只回答一個很單純的空間查詢：「在某個時間戳記，手指位置對應到哪個琴鍵」。這個範圍限制很重要，直接影響到 `missed` 音符的處理方式：鏡頭看到手指壓在正確的鍵上，只能說「有手指在那裡」，不能證明「真的按下去發出聲音了」（可能只是手指懸停、或按得太輕音訊沒收到）。所以對 `missed` 音符，這個模組只會加註記（`camera_suggests_missed_detection`），**不會**自己生出一個音訊從未確認過的音符。

## 用法

### 1. 校準鏡頭（`calibration.py`）

一次性設定，鏡頭位置不變就不用重做。給定鍵盤可見範圍的四個像素角點，加上這個範圍涵蓋的 MIDI 音高範圍：

```python
from camera_evidence import calibrate, save_calibration

calibration = calibrate(
    top_left=(120, 80), top_right=(1050, 60),
    bottom_left=(100, 420), bottom_right=(1080, 400),
    lowest_pitch=48, highest_pitch=84,  # 37鍵鍵盤範例
    camera_id="raspi-cam-1",
)
save_calibration(calibration, "calib.json")
```

角點不需要是正方形——內部用完整的透視變換（homography）處理攝影機角度造成的透視變形，不是簡單假設軸對齊矩形。白鍵在校準寬度內平均分布；黑鍵用標準鋼琴排列（E-F、B-C 之間沒有黑鍵）算出較窄的區域，且只佔琴鍵深度前面一部分（`black_key_depth_ratio`，黑鍵摸不到鍵盤最前緣）。

```python
from camera_evidence import pixel_to_pitch, load_calibration

calibration = load_calibration("calib.json")
pitch = pixel_to_pitch(x=530, y=150, calibration)  # -> 一個 MIDI pitch，或 None（超出鍵盤範圍）
```

### 2. 指尖位置來源（`fingertip_source.py`）

`FingertipSource` 是一個抽象介面（`get_position(timestamp_sec) -> (x, y) | None`），這樣真正的鏡頭實作接上時，下游的比對邏輯完全不用改。

- **`SyntheticFingertipSource`**（現在用這個測試）：吃一份 `reference.json`，在每個參考音符的 onset 時間點「假裝」手指壓在正確的鍵上（經過 calibration 轉成像素座標），可以加像素雜訊（`noise_px`）跟故意注入錯誤位置的機率（`error_rate`，模擬 MediaPipe 偵測失誤）。
- **`MediaPipeFingertipSource`**：還沒做，沒鏡頭硬體可以測。等硬體到了再實作（追蹤 MediaPipe Hands 的食指指尖 landmark，緩存 (timestamp, x, y)，`get_position()` 查最近的一筆）。

### 3. 交叉驗證（`cross_validate.py`）——核心邏輯

吃 `scoring/` 產生的 `result.json` + 一個 `FingertipSource` + calibration，對每個 `wrong_pitch` 音符（尤其是差整數個八度的）跟每個 `missed` 音符做查詢：

```python
from camera_evidence import apply_camera_evidence, SyntheticFingertipSource, load_calibration
import json

result = json.load(open("result.json"))
reference = json.load(open("reference.json"))
calibration = load_calibration("calib.json")
source = SyntheticFingertipSource(reference, calibration, error_rate=0.0)

augmented = apply_camera_evidence(result, source, calibration)
```

每個音符會多一個（可為 `None` 的）`camera_evidence` 欄位，`status` 依情況可能被改寫：

| 狀況 | `status` 變化 | `camera_evidence.flag` |
| --- | --- | --- |
| `wrong_pitch`，鏡頭同意參考譜 | 改成 `camera_corrected_octave_error`，`pitch_perf` 覆寫成 `pitch_ref` | `camera_corrected_octave_error` |
| `wrong_pitch`，鏡頭同意音訊聽到的音 | 不變（真的彈錯，不是誤判） | `camera_confirms_wrong_pitch` |
| `wrong_pitch`/`missed`，鏡頭證據跟兩邊都對不上（或沒讀到） | 不變（不亂猜） | `camera_evidence_inconclusive` |
| `missed`，鏡頭看到手指在對的鍵上 | 不變（鏡頭不能證明真的按下去了） | `camera_suggests_missed_detection` |

`summary.counts` 會依實際（可能被改寫過的）狀態重新統計，另外加一個 `summary.camera_evidence_summary` 統計各種鏡頭判決的數量。

### CLI

```bash
python -m camera_evidence result.json --calibration calib.json \
  --synthetic --reference reference.json --error-rate 0.1 --noise-px 5 \
  -o augmented_result.json
```

`--synthetic` 現在是唯一能跑的模式（沒鏡頭硬體）；不加的話會嘗試用 `MediaPipeFingertipSource`，直接印出清楚的錯誤訊息說明還沒做。

## 執行測試

```bash
python -m pytest camera_evidence/tests -v
```

全部用合成資料，不需要鏡頭：

- `test_calibration.py`：角點對應到範圍兩端音高、超出範圍回傳 `None`（含邊緣容忍度）、黑鍵/白鍵在相鄰像素解析成不同音高、標準排列（E-F、B-C 沒黑鍵）
- `test_fingertip_source.py`：`error_rate=0` 時一定落在正確的鍵上
- `test_cross_validate.py`：+12 八度誤判被鏡頭糾正、非八度的真實彈錯音不會被誤「糾正」、鏡頭證據矛盾時原狀不動、`missed` 音符鏡頭支持時只加註記不生新音符

## 檔案結構

| 檔案 | 作用 |
| --- | --- |
| `config.py` | `CameraEvidenceConfig`：哪些狀態觸發鏡頭查詢、校準邊緣容忍度、黑鍵幾何參數 |
| `calibration.py` | 像素角點 -> homography -> 白鍵/黑鍵版面，`pixel_to_pitch()` / `pitch_to_pixel()` |
| `fingertip_source.py` | `FingertipSource` 介面、`SyntheticFingertipSource`、`MediaPipeFingertipSource`（stub） |
| `cross_validate.py` | 核心比對邏輯，吃 `result.json` 吐出加註 `camera_evidence` 的版本 |
| `cli.py` / `__main__.py` | `python -m camera_evidence ...` |
| `tests/` | 見上 |

## 重要限制

- 鏡頭只做空間查詢，不做 onset 偵測——這條界線是刻意的，不要在這個模組裡加「自動補一個音符」的邏輯
- 目前完全沒有真實鏡頭資料驗證過；`SyntheticFingertipSource` 假設的雜訊/誤判模型是合理猜測，等真的 MediaPipe 接上後，這裡的雜訊參數需要用真實資料重新校準
- calibration 假設鍵盤是一個平面（單一 homography）跟標準鋼琴黑白鍵排列，如果鏡頭角度太刁鑽或看不到完整鍵盤，這個模型可能不夠用
