# audio_to_performance

把單人單鋼琴的麥克風錄音，轉成 [scoring](../scoring) 引擎吃的 `performance.json`。跟先前 `latency_test` 那套用通用 onset 偵測（librosa spectral flux）的做法不同——這裡用 Spotify 的 **basic-pitch**，一個真正訓練過的複音鋼琴轉譜神經網路，而不是「有沒有聲音突然變大聲」這種通用方法。

## 目前的建議用法：已知曲譜時，評分學生錄音改用 `grade_audio_reference_constrained.py`

**評分「學生錄音 vs 已知曲譜」這個主要場景，現在改用 `scripts/grade_audio_reference_constrained.py --mode reference-grid`（不經過 basic-pitch），不再用 `scripts/grade_audio.py`。**

原因：這台 BF-3738C 電子琴的音色跟 basic-pitch 訓練用的真鋼琴差很多，一直有「多餘音符」(harmonic bleed 誤判成新音符)的問題，就算加了 `suppress_harmonic_extras` 之類的heuristic 也只能減少、不能根除。

實測拿曲庫裡5首完全落在22個白鍵範圍內的歌(其餘6首含黑鍵/超出範圍，用keybank合成會不公平)，各自合成成真實音色音檔，同一份音檔分別跑兩條路徑評分：

| 曲目 | refgrid分數 | bp分數 | refgrid(對/錯音/漏/多) | bp(對/錯音/漏/多) |
| --- | --- | --- | --- | --- |
| 10_little_indians | 92.96 | 87.29 | 66/0/5/0 | 69/0/2/10 |
| alabama | 93.14 | 85.67 | 95/0/7/0 | 95/5/2/13 |
| pachelbel_canon_bpno | 94.23 | 92.03 | 98/0/6/0 | 102/0/2/6 |
| silent_night_easy | 100.00 | 90.05 | 74/0/0/0 | 72/0/2/7 |
| twinkle_twinkle | 95.65 | 90.65 | 66/0/3/0 | 69/0/0/7 |
| **合計(438個音符)** | | | **399/0/21/0** | **407/5/8/43** |

`reference-grid` 每一首歌分數都比 basic-pitch 高，而且**5首歌加總 0 個 extra、0 個 wrong_pitch**——不是單一首歌的偶然結果。basic-pitch 抓到的音符總數略多(漏音較少)，但代價是 43 個 extra + 5 個 wrong_pitch，這就是一直存在的「泛音誤判成新音符」問題；`reference-grid` 完全不會有這個毛病，因為它從頭到尾只在已知候選音高集合裡驗證，不會憑空多冒出音符。

`reference-grid` 模式（`reference_constrained.py` 的 `transcribe_reference_constrained`）完全不猜音高——已知曲譜的每個音符各自在對應時間點的音檔窗口裡驗證「參考音高的證據夠不夠強」，不會像 basic-pitch 那樣把泛音誤判成獨立新音符。漏掉的21個音，一部分是已知的 F3 硬體特性(基頻弱)這類個別鍵的問題，其餘屬於還可以調參數優化的範圍(見下方)，不是新 bug。

**這條路線原本有一個嚴重 bug 已修好**：時間對齊原本用一個粗略的「音檔哪裡有聲音」RMS 門檻估計，28秒的曲子會累積將近0.7秒的誤差，導致後半首歌大量誤判成 `missed`（分數曾經只有42分）。改成用模組裡已有的 onset 偵測去對齊第一個/最後一個音符的時間，才修正回 95.65 分。

**沒有被取代的部分**：`transcribe.py`/`pipeline.py`/`preprocess.py`/`postprocess.py` 這些 basic-pitch 模組保留，`validation/roundtrip.py` 等內部驗證工具還在用它們做「合成音檔反向驗證 MIDI 轉譜」這件事，跟「評分學生錄音」是不同用途。`grade_audio.py` 本身也還在，沒有刪除，只是不再是評分學生錄音的預設工具。

## 為什麼要換掉之前的方法

之前用 `latency_test` 測試過兩首完全不同的曲子（Für Elise 真實演奏、Bach前奏曲排除rubato變因），都得到同樣的結果：**72% 的音符完全沒被偵測到**，而且從頭到尾沒有音高資訊（只能判斷「有沒有聲音、什麼時候」，判斷不了「彈了哪個音」）。這是通用 onset 偵測方法在複音、連續鋼琴音樂上的已知天花板，不是調參數能解決的。

basic-pitch 是不一樣量級的工具：它是專門訓練來做「polyphonic automatic music transcription」的模型，同時輸出音高、起始時間、結束時間。在這個模組的端對端測試裡（合成一段C大調分解和弦），4個真實音符全部被正確辨識成 `correct`（音高、時間都對），`missed: 0`——相較之前的72%漏偵測，是質的差異。

## 安裝（注意：需要 Python 3.11，不是 3.14）

`basic-pitch` 的依賴鏈（主要是 `resampy`/`numpy` 的原始碼包）在 Python 3.14 上編譯不起來，因為裡面用到已經被移除的 `pkgutil.ImpImporter`。這個專案其他模組能在 3.14 上跑，但這個模組需要自己的 Python 3.11 虛擬環境：

```bash
brew install python@3.11   # 如果還沒裝
cd <repo根目錄>
python3.11 -m venv backend/audio_to_performance/.venv
source backend/audio_to_performance/.venv/bin/activate
pip install -r backend/audio_to_performance/requirements.txt
pip install music21   # backend.scoring 會 import backend.score_to_reference，間接需要這個
```

**另一個安裝陷阱**：`setuptools` 從某個版本開始把 `pkg_resources` 整個移除了（resampy 還在用這個舊 API），所以 `requirements.txt` 裡特別釘住 `setuptools<81`。如果你自己手動升級過 setuptools，可能又會踩到這個錯誤，訊息長這樣：

```
ModuleNotFoundError: No module named 'pkg_resources'
```

重新 `pip install "setuptools<81"` 就能解決。

## 用法

### CLI

```bash
python -m backend.audio_to_performance 錄音.wav -o performance.json --save-midi 轉譜結果.mid
```

加上前處理（預設全部關閉，見下方說明）：

```bash
python -m backend.audio_to_performance 錄音.wav -o performance.json \
  --denoise --bandpass --normalize \
  --onset-thresh 0.6 --frame-thresh 0.4
```

### 當 Python 套件用

```python
from backend.audio_to_performance import transcribe, AudioToPerformanceConfig

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
python -m backend.audio_to_performance 錄音.wav -o performance.json --suppress-harmonics
```

## 限制式驗證(`constrained_verification.py`)：用已知的參考譜縮小搜尋範圍

basic-pitch 是自由(不受限)的複音轉譜——在整個鋼琴音域裡自己猜每個音是什麼。這正是八度誤判的根源：2*f0 在物理上就跟高八度的音重疊，鋼琴的非諧性(inharmonicity)在低音區還可能讓泛音比基音更強，模型有時候會挑到泛音而不是基音。但既然我們透過 `reference.json` 已經知道「這個時間點應該是哪個音」，就不需要每次都做開放式轉譜——可以只在一個很小的候選音高集合裡（預期音高本身 + 最可能搞混的幾個音）比對原始音訊證據，而不是照單全收 basic-pitch 給的猜測。

這是疊加在既有 pipeline **之上**的一層，不是取代它：只重新檢視 `result.json` 裡已經被標記 `wrong_pitch`/`missed` 的音符。

- **候選集合**(`get_candidates`)：參考音高本身 + `±1、±2、±12、±24` 半音——涵蓋近似音跟一/二個八度的誤判。等實體鍵盤到了，把 `keyboard_range=(最低音, 最高音)` 設進 `ConstrainedVerificationConfig`，可以濾掉物理上鍵盤根本彈不出來的候選音(見程式碼裡的 TODO)。
- **泛音感知評分**(`score_candidate`)：從 CQT 讀每個候選音基頻位置的能量，如果某候選音剛好是集合裡另一個候選音的高八度、而且自己的能量明顯比那個低音候選音弱(預設門檻：不到 0.4 倍)，就大幅打折——代表這很可能只是泛音，不是真的獨立按下的音。
- **逐音重新驗證**(`reverify_note`)：贏家 = 參考音高 → 改判 `corrected_octave_or_harmonic_error`；贏家 = 原本 basic-pitch 猜的音 → 維持原狀(證實真的彈錯/沒偵測到)；贏家是集合裡其他候選音 → 改判 `reverified_different_pitch`；沒有候選音的信心度(佔全部候選音能量的比例)超過門檻 → 維持原狀，標 `reverification_inconclusive`，絕不亂猜。
- **獨立的「未預期起音」掃描**(`scan_unexpected_onsets`)：上面的方法結構上只會去參考譜「預期有音符」的地方找證據，看不到完全不在預期範圍內的音符。這裡改用最單純的 onset-strength 包絡線(不管音高)掃過整段錄音，找出離所有已知起音(參考譜 + `result.json` 裡已經配對過的起音)都太遠(預設 >0.2秒)的起音，標成 `possible_unscored_extra_onset`——純資訊性質，不會自己生一個配了分的音符，因為我們還不夠確定它的音高。

## 音色不符實體樂器：改用實體按鍵錄音的樣本比對(`keybank.py` / `keyboard_profile.py`)

舊版 `timbre_fingerprint.py`（每個鍵的 CQT 指紋、比對候選音）已移除，改用另一套機制：直接錄一段「從左到右彈過全部37個鍵」的音檔，按物理順序切成一段一段的樣本(`train_keybank_from_scale.py` → `keybank.py`)，不靠音高偵測去猜每一段是哪個音——因為這台琴的音色本來就容易讓音高偵測器(pYIN、basic-pitch)誤判，用彈奏順序當標籤才可靠。

- **`keybank.py`**：從左到右的音階錄音偵測 onset、依序切割貼上 midi 標籤，同時算每個鍵的泛音能量統計；額外用 pYIN 做一個「診斷用」複核，跟物理順序標籤差超過 0.75 半音就標記 `pyin_octave_or_pitch_disagrees_with_order_label`——但這只是診斷資訊，不影響標籤本身。
- **`keyboard_profile.py`**：把 keybank 的每鍵泛音統計整理成一份可重複使用的「這台琴聽起來長怎樣」的 profile。
- **`constrained_verification.py` 的 `keyboard_profile` 參數**：候選音評分時，如果這個候選音在 profile 裡有記錄，會用觀測到的泛音能量分佈跟 profile 模板做 cosine 相似度，加權疊加到原本的 CQT 能量分數上(不是整個切換，是額外加分)。
- **`synthesize_reference_from_keybank.py`**：直接照參考譜的音高、時間，從 keybank 找對應樣本原音重播混音，不做任何 pitch-shift。

### 另一條路：完全不用 basic-pitch 的「音對音」比對(`audio_reference.py` / `reference_constrained.py`)

上面的 `keyboard_profile` 只是疊加在 basic-pitch 轉譜結果上的加分項，錄音本身還是得先過一次 basic-pitch。這裡是另一套獨立機制，完全跳過 basic-pitch：

- **`reference_constrained.py`**：`_candidate_pitches()` 直接把候選音高鎖死在 22 個白鍵(或整個鍵盤範圍)——不是拿 basic-pitch 的猜測結果來篩選，而是從一開始就只在這個小集合裡評分，`ReferenceConstrainedConfig` 可設 `allowed_pitches=WHITE_KEY_MIDIS` 限定白鍵模式。
- **`audio_reference.py`**：
  - `build_audio_reference()`：直接對一段「範例錄音」做 onset 偵測 + 上面的候選音高評分，產生一份音訊原生的參考譜(不需要對應的 MIDI/樂譜檔)——`scripts/build_demo_audio_reference.py` 的實作。
  - `grade_student_against_demo()`：把學生錄音一樣做 onset+候選音評分，直接拿去跟這份「範例錄音」的參考譜比對評分——完全是音檔對音檔，兩邊都不經過 basic-pitch——`scripts/grade_against_demo_audio.py` 的實作。
- **`train_keyboard_profile.py`**：另一種訓練 profile 的方式，直接對任意錄音跑 pYIN 抓穩定音高段落分組平均，不需要像 `keybank.py` 那樣照順序彈一次音階（兩者輸出的 profile JSON 格式相容）。
- **`scripts/grade_audio_reference_constrained.py`**：`grade_audio.py` 的替代品——用符號化參考譜(MIDI/MusicXML)+候選音限制的方式評分麥克風錄音，同樣完全不經過 basic-pitch。

**跟前面 `keyboard_profile` 疊加機制的差別**：前者仍然信任 basic-pitch 的轉譜，只在它猜錯時用泛音相似度去修正；這裡是從根本上不信任 basic-pitch，只在已知候選音高集合裡挑一個最像的。

**目前狀態**：`reference_constrained.py` 裡的 `transcribe_reference_constrained`（對應 `grade_audio_reference_constrained.py --mode reference-grid`）已經是評分「已知曲譜 + 學生錄音」的**預設工具**，見本文開頭——時間對齊的 bug 修好後實測比 basic-pitch 少了全部的 extra 誤判(見開頭比較表)。

`audio_reference.py` 的 `build_audio_reference()`/`grade_student_against_demo()`（沒有已知 MIDI 曲譜，純粹音檔對音檔）跟 `transcribe_onset_first`/`transcribe_reference_guided_onsets` 這兩個模式，還停留在只跑過自我一致性檢查的階段——這兩個模式受限於 `max_pitches_per_onset`(預設1)，同一個時間點有兩個音同時彈(和弦)時只會保留最強的那個，這在小星星這首歌(69個音符裡有26個時間點是2音同時)已經證實會漏掉大量音符，還沒有調過。

## 曲庫預先已知：用單曲音域縮小 basic-pitch 的搜尋範圍(`song_range.py`)

> **目前狀態**：`grade_audio.py` 整包被 Codex 版本覆蓋後，暫時沒有呼叫這個模組了(`--no-song-range`/`--ignore-timing` 這兩個 CLI 參數也一併消失)。模組本身、測試都還在，下面的 A/B 數據依然成立，只是還沒重新接回 `grade_audio.py`。

專案的曲庫不是開放式的任意音檔——每首歌的參考譜都預先知道，也就知道**這首歌實際會用到哪些音高**。之前測過把 basic-pitch 的 `minimum_frequency`/`maximum_frequency` 綁到整個鋼琴音域(27.5-4186Hz)完全沒效果，因為那個範圍太寬、幾乎沒縮小到什麼。單曲的音域通常窄很多，值得單獨測。

拿11首真實曲子(FluidSynth合成音，走完整評分流程)實測掃過幾種留白(padding)大小：

| padding | correct | wrong_pitch | missed | extra |
| --- | --- | --- | --- | --- |
| 不設範圍 | 995 | 7 | 22 | 60 |
| ±1個八度(12半音) | 995 | 7 | 22 | 60（跟不設一樣，留白太寬沒縮到東西） |
| ±6半音 | 995 | 6 | 23 | **50** |
| ±3半音 | 995 | 6 | 23 | 50（跟±6一樣） |
| 完全不留白(0) | **962** | 11 | **51** | 43（矯枉過正——曲子自己寫的音剛好卡在邊界也被切掉） |

**預設用 ±6半音**：extra 從60降到50、wrong_pitch 7→6，代價只有1個新增的missed，乾淨的淨改善。低於6沒有額外好處，降到0直接爆掉(correct掉33個、missed多29個)——所以6是實測出來的甜蜜點，不是隨便猜的。

`compute_song_frequency_range(reference, pad_semitones=6)`：算出這首歌實際音高範圍(留白後)對應的Hz範圍，餵給 `AudioToPerformanceConfig(minimum_frequency=..., maximum_frequency=...)`。`grade_audio.py` 預設會用，`--no-song-range` 關閉。

用法：

```bash
python -m backend.audio_to_performance.constrained_verification result.json 錄音.wav \
  --reference reference.json --keyboard-range 21 108 \
  -o augmented_result.json
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
- `test_constrained_verification.py`：全部用手造的假 CQT 能量陣列測，不需要真的音訊——候選音生成、泛音折扣邏輯(含「真的彈錯不會被誤壓下去」的反例)、三種 reverify 結果、還有一個回歸測試專門確認「不確定的時候絕對不會偷偷改狀態」

## 37鍵實體鍵盤限制(`keyboard_range`，預設開啟)

專案的鍵盤只有37鍵(MIDI 48-84，C3-C6，唯一定義處在 `backend/hardware.py`)。這不是啟發式規則而是物理事實：鍵盤彈不出範圍外的音，所以**錄「這台鍵盤」的音檔裡轉譜出範圍外的音，百分之百是誤判**(通常是真音符的低八度/泛音鬼影)，直接刪掉。兩個地方都吃這個限制：

- `pipeline.transcribe()`：範圍外的轉譜音符直接過濾(`config.keyboard_range`，預設 48-84)
- `constrained_verification`：八度候選音超出鍵盤範圍的不列入考慮——邊界效果特別好，例如參考音是最低鍵48時，往下八度的36/24物理上不存在，低頻泛音就沒機會贏

**唯一要注意的**：音檔不是來自實體鍵盤時(例如 `validation/roundtrip` 拿任意MIDI合成的音訊)必須設 `keyboard_range=None`，不然會把真實存在的範圍外音符當誤判刪掉——`roundtrip.py` 已經自動處理，`scripts/grade_audio.py` 會依「參考譜是否落在鍵盤範圍內」自動決定。如果鍵盤其實有八度移調(octave shift)設定，改 `backend/hardware.py` 一個地方即可。

## 檔案結構

| 檔案 | 作用 |
| --- | --- |
| `config.py` | `AudioToPerformanceConfig`：前處理開關 + basic-pitch 參數 + 後處理開關 + 鍵盤範圍，全部集中一處 |
| `preprocess.py` | 降噪/bandpass/正規化，預設全關 |
| `transcribe.py` | 包裝 basic-pitch `predict()`，輸出 `pretty_midi.PrettyMIDI` |
| `postprocess.py` | 泛音/延音踏板誤判成新音符的過濾器，預設關閉 |
| `pipeline.py` | 串起來：載入音訊 → 前處理 → 轉譜 → 存成MIDI → 呼叫 `scoring.midi_io.midi_to_performance()` → (可選)後處理過濾 |
| `constrained_verification.py` | 疊加層：用參考譜縮小候選音高範圍，重新檢視 `wrong_pitch`/`missed`，外加獨立的未預期起音掃描；也是 `keyboard_profile` 加分機制的所在地 |
| `keybank.py` | 從左到右白鍵音階錄音訓練樣本庫，供 `synthesize_reference_from_keybank.py` 原音重播用 |
| `keyboard_profile.py` | 把 keybank 的泛音統計整理成可重複使用的音色 profile |
| `reference_constrained.py` | 候選音高從一開始就鎖在已知集合(白鍵/鍵盤範圍)裡評分，不信任 basic-pitch 的猜測 |
| `audio_reference.py` | 音對音比對：`build_audio_reference()` 從範例錄音產生音訊原生參考譜，`grade_student_against_demo()` 拿學生錄音直接比對 |
| `cli.py` / `__main__.py` | `python -m backend.audio_to_performance ...` |
| `tests/` | 見上 |

## 重要限制

- **這是一個深度學習模型，假設跑在筆電/雲端，不是樹莓派本身**——樹莓派那端應該只負責錄音+把音檔傳出去，不要在樹莓派上直接呼叫 `transcribe()`
- 轉譜不是100%準確，尤其是快速圓滑奏、踏板延音、極端音域的段落——這比通用 onset 偵測好非常多，但不是完美的
- 只處理單一鋼琴音源，不是多樂器分離(沒有用 Spleeter/Demucs 那類工具，也不需要，因為場景就是一台鋼琴)
