# benchmarks

一次性、跑在目標硬體上的效能測試，不是可重複匯入的函式庫——結果記在這裡跟對話紀錄裡，不是斷言在測試套件裡。

## `basic_pitch_pi_bench.py`：決定 basic-pitch 轉譜能不能搬到樹莓派上跑

目前 `audio_to_performance/` 假設轉譜跑在筆電/雲端，不是樹莓派本身。但這是一個 AIoT 專案，展示時還要依賴筆電，跟「IoT裝置自己做事」的故事有點矛盾。在真的把架構改成「樹莓派自己轉譜」之前，先測一下樹莓派的推論速度夠不夠快。

刻意只用**輕量**推論後端（ARM 上合理的選擇）：優先 `tflite-runtime`，不行就退到 ONNX Runtime，都不行只剩全套 TensorFlow SavedModel 的話會印出明顯警告——那正是這個測試想避開的重量級後端。

## 在樹莓派 5(Debian 13 trixie, Python 3.13, aarch64)上實測遇到的安裝問題

這部分值得記下來，因為坑不小：

1. **basic-pitch 在 Linux 上的 `install_requires` 直接要求 `tensorflow<2.15.1`**（Mac 上這條規則因為 `platform_system != "Darwin"` 的條件被排除，所以 Mac 裝 `basic-pitch[onnx]` 完全沒事，但 Linux 上這是硬性條件，不管你裝不裝 tf extras）。而 `tensorflow<2.15.1` 沒有支援 Python 3.13 的 aarch64 wheel（TF 是最近的 2.19+ 才加上 3.13 支援，版本已經超過 `<2.15.1` 的上限），導致 `pip install basic-pitch` 直接失敗，還會讓 pip 的 resolver 往回探索更舊的 basic-pitch 版本，一路挖到 `numpy<1.24`（連 numpy 都得從沒有 wheel 的舊 sdist build，在新版 Python 上會因為 `setuptools.build_meta` 相關問題整個炸掉）。

   **解法**：跳過 basic-pitch 自己的依賴解析，只裝它實際「推論」路徑真正需要的東西：
   ```bash
   pip install --no-deps basic-pitch==0.4.0
   pip install numpy librosa resampy pretty_midi scipy mir_eval
   ```
   這裡特意不裝 `tensorflow`、`scikit-learn`——檢查過 `basic_pitch/inference.py` 跟 `note_creation.py`(predict() 實際會走到的程式碼)完全沒 import 這兩個，那些只有 `models.py`/`nn.py`/`train.py`/`visualize.py`(訓練/視覺化用，不會被 `predict()` 碰到)才需要。basic_pitch 自己的 `__init__.py` 對 tflite/onnx/tf/coreml 都是 try/except 包起來的，缺了不會真的壞掉——**除非一個後端都不裝**：那樣 `_default_model_type` 完全沒被賦值，連 `import basic_pitch` 都會 `NameError`，所以至少要裝一個推論後端才能用。

2. **`tflite-runtime` 在這個平台/Python版本組合完全沒有可用的發佈版本**(`pip install tflite-runtime` 直接回報 "Could not find a version that satisfies the requirement... from versions: none")——這是已知問題，Google 很長一段時間沒有再為新版 Python/ARM 組合發佈 wheel。程式碼裡的 fallback 邏輯正是為了這個情況設計的：自動退到 `onnxruntime`(有 cp313 aarch64 wheel，正常裝)。

3. 網路速度不穩(這台機器連線速度時快時慢，numpy 15MB 一度花了 2.5 分鐘)，純粹是這次測試環境的問題，跟程式碼無關。

## 實測結果(Raspberry Pi 5 Model B Rev 1.1, 8GB RAM, Debian 13 trixie, Python 3.13.5, ONNX Runtime 後端)

| 音檔長度 | 平均推論時間 | RTF(real-time factor) | 峰值記憶體 | 結論 |
| --- | --- | --- | --- | --- |
| 5s | 0.121s | 0.02 | 266MB | 比即時快超過40倍 |
| 10s | 0.211s | 0.02 | 270MB | 比即時快超過40倍 |
| 20s | 0.400s | 0.02 | 279MB | 比即時快超過40倍 |
| 30s | 0.594s | 0.02 | 289MB | 比即時快超過40倍 |

**結論：完全可行，而且遠遠超乎預期。** RTF 穩定在 0.02 左右(轉譜時間只佔音檔本身長度的2%)，記憶體也只用了不到300MB(樹莓派5有8GB)——不只是「可以做批次處理」，是連即時/近即時回饋都綽綽有餘。這個數字是 Pi 5 + ONNX Runtime 後端測出來的，跟晚一輩的 Pi(3/4，記憶體更少、CPU更弱)不能直接類推——如果之後要在更舊型號上部署，需要重新跑一次這個 benchmark。

完整原始報告：`pi5_benchmark_report.json`(在對話的 scratchpad 裡，未加入這個 git repo，因為是單次測試結果不是程式碼)。

## 用法

```bash
python -m benchmarks.basic_pitch_pi_bench --durations 5 10 20 30 --runs 3 -o report.json
```

32位元系統會直接印錯誤退出(TF/ONNX 的 ARM wheel 在32位元上常常裝不上或裝了會壞，與其在依賴錯誤裡越挖越深，不如直接换64位元映像檔)。
