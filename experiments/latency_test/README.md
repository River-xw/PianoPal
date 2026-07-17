# latency_test

量「喇叭 → 空氣 → 麥克風 → onset 偵測」這整條路徑的系統延遲。跟裝置無關——現在先用電腦內建麥克風測，之後真正的麥克風/音訊感測器接上以後，同一支程式換個裝置參數重跑一次就好，不用改程式碼。

## 為什麼要這樣測

延遲是**特定硬體組合**的特性（麥克風收音頭 + 音訊介面 + 驅動程式），換了麥克風，這個數字就得重測，不能沿用電腦內建麥克風測出來的結果。所以工具設計成裝置可替換：`--input-device`/`--output-device` 指定要用哪個裝置，不指定就用系統預設。

## 用法

先看有哪些裝置可以選：

```bash
cd 學習用/
source score_to_reference/.venv/bin/activate
python3 -m experiments.latency_test.calibrate --list-devices
```

會列出類似這樣的東西：

```
  0 iPhone 6s Plus麥克風, Core Audio (1 in, 0 out)
> 1 MacBook Air的麥克風, Core Audio (1 in, 0 out)
< 2 MacBook Air的揚聲器, Core Audio (0 in, 2 out)
```

跑校準（不指定裝置的話用系統預設，也就是現在測電腦內建麥克風的方式）：

```bash
python3 -m experiments.latency_test.calibrate --clicks 10 --interval 1.0 \
  --save-result latency_calibration.json \
  --save-wav recording.wav
```

**之後真正的麥克風接上以後**，用 `--list-devices` 找到它的編號或名稱，一樣的指令換個裝置參數重跑：

```bash
python3 -m experiments.latency_test.calibrate --input-device 3 --output-device 2 \
  --clicks 10 --interval 1.0 \
  --save-result latency_calibration_real_mic.json
```

會印出：
- 每個 click 真實時間 vs 偵測到的時間，逐一列出
- 平均延遲、jitter(標準差)——用 median absolute deviation 抓離群值(背景雜音誤觸發)並排除，避免單一次雜音把整個統計數字拉歪
- `--save-result` 存的 json 檔會記錄裝置名稱、延遲、jitter，給之後串接 `scoring` pipeline 時用

## 這個延遲數字要怎麼用

`scoring.ScoringConfig` 的預設容忍度 `tol_ms` 通常是 50ms 這個量級。如果系統延遲有 100+ms，之後把麥克風偵測到的音符餵進 `scoring` 之前，要先把每個 onset 時間**減掉**這個延遲值做修正，不然每個音符都會被誤判成 `timing_off`（因為整批音符的時間都系統性地偏移了同一個方向，這其實不是使用者彈得不準，是感測器本身的延遲）。

## 已知限制

- 只測時間（onset 偵測延遲），不測音高——因為這裡假設偵測到的音符集合本身音高是已知的(例如來自 MIDI 鍵盤或琴鍵感測器)，麥克風只是拿來抓「什麼時候」，不是「彈了哪個音」
- click track 用固定 2000Hz 短音爆發模擬敲擊聲，跟真實鋼琴的音色/衰減曲線不同，onset 偵測器對兩者的反應速度可能略有差異——這個校準值是「系統對一般清晰瞬態聲音的反應時間」的估計，不是「對鋼琴聲音」的精確測量
- 需要 `sounddevice`（底層用 PortAudio）能抓到你指定的裝置；如果是透過 USB 或特殊音訊介面接的感測器，可能需要額外的驅動程式才會出現在 `--list-devices` 的清單裡
