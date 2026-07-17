# audio_to_performance

把單人單鋼琴的麥克風錄音，轉成 [scoring](../scoring) 引擎吃的 `performance.json`。跟先前 `latency_test` 那套用通用 onset 偵測（librosa spectral flux）的做法不同——這裡用 Spotify 的 **basic-pitch**，一個真正訓練過的複音鋼琴轉譜神經網路，而不是「有沒有聲音突然變大聲」這種通用方法。

## 為什麼要換掉之前的方法

之前用 `latency_test` 測試過兩首完全不同的曲子（Für Elise 真實演奏、Bach前奏曲排除rubato變因），都得到同樣的結果：**72% 的音符完全沒被偵測到**，而且從頭到尾沒有音高資訊（只能判斷「有沒有聲音、什麼時候」，判斷不了「彈了哪個音」）。這是通用 onset 偵測方法在複音、連續鋼琴音樂上的已知天花板，不是調參數能解決的。

basic-pitch 是不一樣量級的工具：它是專門訓練來做「polyphonic automatic music transcription」的模型，同時輸出音高、起始時間、結束時間。在這個模組的端對端測試裡（合成一段C大調分解和弦），4個真實音符全部被正確辨識成 `correct`（音高、時間都對），`missed: 0`——相較之前的72%漏偵測，是質的差異。

## 安裝（注意：需要 Python 3.11，不是 3.14）

`basic-pitch` 的依賴鏈（主要是 `resampy`/`numpy` 的原始碼包）在 Python 3.14 上編譯不起來，因為裡面用到已經被移除的 `pkgutil.ImpImporter`。這個專案其他模組能在 3.14 上跑，但這個模組需要自己的 Python 3.11 虛擬環境：

```bash
brew install python@3.11   # 如果還沒裝
cd 學習用/
python3.11 -m venv audio_to_performance/.venv
source audio_to_performance/.venv/bin/activate
pip install -r audio_to_performance/requirements.txt
pip install music21   # scoring 套件會 import score_to_reference，間接需要這個
```

**另一個安裝陷阱**：`setuptools` 從某個版本開始把 `pkg_resources` 整個移除了（resampy 還在用這個舊 API），所以 `requirements.txt` 裡特別釘住 `setuptools<81`。如果你自己手動升級過 setuptools，可能又會踩到這個錯誤，訊息長這樣：

```
ModuleNotFoundError: No module named 'pkg_resources'
```

重新 `pip install "setuptools<81"` 就能解決。

## 用法

### CLI

```bash
python -m audio_to_performance 錄音.wav -o performance.json --save-midi 轉譜結果.mid
```

加上前處理（預設全部關閉，見下方說明）：

```bash
python -m audio_to_performance 錄音.wav -o performance.json \
  --denoise --bandpass --normalize \
  --onset-thresh 0.6 --frame-thresh 0.4
```

### 當 Python 套件用

```python
from audio_to_performance import transcribe, AudioToPerformanceConfig

# 從檔案
performance = transcribe(wav_path="錄音.wav")

# 從記憶體裡的 numpy array(例如即時錄音的 buffer，不用先寫檔)
performance = transcribe(audio=my_audio_array, samplerate=44100)
```

`performance` 的格式跟 `scoring.midi_io.midi_to_performance()` 輸出的完全一樣——因為內部就是直接呼叫那個函式，兩條輸入路徑（真的 MIDI 鍵盤 vs. 麥克風轉譜）共用同一份「什麼是一個 performance 音符」的定義，沒有另外發明一套 schema。

## 前處理為什麼預設關閉

`denoise`(降噪)、`bandpass`(限制在鋼琴音域 27.5-4186Hz)、`normalize`(音量正規化)都做了，但預設**全部關閉**。原因：basic-pitch 是拿相對乾淨的原始音訊訓練的，這些前處理步驟可能會削弱或扭曲音符起始瞬間的瞬態訊號——而模型正是靠這個瞬態判斷「這裡有一個新的音符開始了」。降噪尤其容易把攻擊瞬間磨平。想開啟前，建議先關/開各自測一次，比較實際轉譜結果，不要預設「處理過的音訊一定比較好」。

## 轉譜出來的「多餘音符」問題（`--suppress-harmonics`）

拿真實錄音實測發現：轉譜結果裡有不少 `extra`(參考樂譜裡沒有對應的音符)，但這些不是隨機幻覺。實際比對一份 Bach 前奏曲的錄音發現：

- 84% 的 extra 音符，都出現在某個「真的、被正確配對」的音符附近(150毫秒以內)
- 其中 58% 跟那個真音符差一個八度、完全五度、或完全四度——古典的泛音/共鳴音程
- extra 音符的音量中位數(50)明顯比真音符(73)小、拖長時間也短很多(0.28s vs 0.86s)

也就是說：多數 extra 是鋼琴自己的泛音、或延音踏板的共鳴，被 basic-pitch 誤判成一個新按下的音符，不是轉譜邏輯亂猜。

一開始想用單純的音量門檻濾掉，但發現 extra 跟真音符的音量分布重疊太多——設門檻濾掉六成 extra，也會誤殺一成真音符。所以改成更精準的條件（`postprocess.py`）：**只有同時滿足「時間夠近」+「音程是八度/五度/四度」+「音量明顯比旁邊那個真音符小」，才會被丟掉**。這樣可以放過：單獨彈的小聲音符（沒有旁邊音符可比較）、真的刻意八度加倍的和弦（兩個音量差不多大）。

實測效果（同一份錄音，同一份轉譜結果，只是套用這個過濾器）：extra 從 358 降到 264(-26%)，總分從 60.69 提升到 62.4。不是完美解法（真音符也會被誤殺一些，`correct` 從451掉到437），但淨效益是正的。

預設關閉，用 `--suppress-harmonics` 開啟：

```bash
python -m audio_to_performance 錄音.wav -o performance.json --suppress-harmonics
```

## 執行測試

```bash
source audio_to_performance/.venv/bin/activate
cd 學習用/
python3 -m pytest audio_to_performance/tests -v
```

- `test_preprocess.py`：純數學，合成 sine wave 測 bandpass/normalize/denoise，不需要真的錄音檔
- `test_postprocess.py`：純數學，驗證泛音過濾規則(八度/五度/四度+音量差)的各種邊界情況
- `test_pipeline.py`：**會真的呼叫 basic-pitch 做推論**——用加法合成器(sine+泛音+包絡線)生一段C大調分解和弦的假鋼琴音訊，跑完整 pipeline，檢查轉譜出來的音符數量、音高是否大致吻合(容忍度故意放寬，因為轉譜本來就不會100%精確，這裡測的是「整條路接得起來」，不是幫 basic-pitch 打分數)

## 檔案結構

| 檔案 | 作用 |
| --- | --- |
| `config.py` | `AudioToPerformanceConfig`：前處理開關 + basic-pitch 參數 + 後處理開關，全部集中一處 |
| `preprocess.py` | 降噪/bandpass/正規化，預設全關 |
| `transcribe.py` | 包裝 basic-pitch `predict()`，輸出 `pretty_midi.PrettyMIDI` |
| `postprocess.py` | 泛音/延音踏板誤判成新音符的過濾器，預設關閉 |
| `pipeline.py` | 串起來：載入音訊 → 前處理 → 轉譜 → 存成MIDI → 呼叫 `scoring.midi_io.midi_to_performance()` → (可選)後處理過濾 |
| `cli.py` / `__main__.py` | `python -m audio_to_performance ...` |
| `tests/` | 見上 |

## 重要限制

- **這是一個深度學習模型，假設跑在筆電/雲端，不是樹莓派本身**——樹莓派那端應該只負責錄音+把音檔傳出去，不要在樹莓派上直接呼叫 `transcribe()`
- 轉譜不是100%準確，尤其是快速圓滑奏、踏板延音、極端音域的段落——這比通用 onset 偵測好非常多，但不是完美的
- 只處理單一鋼琴音源，不是多樂器分離(沒有用 Spleeter/Demucs 那類工具，也不需要，因為場景就是一台鋼琴)
