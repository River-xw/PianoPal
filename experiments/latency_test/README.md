# latency_test

量「喇叭 → 空气 → 麦克风 → onset 侦测」这整条路径的系统延迟。跟设备无关——现在先用电脑内置麦克风测，之后真正的麦克风/音频传感器接上以后，同一支程序换个设备参数重跑一次就好，不用改代码。

## 为什么要这样测

延迟是**特定硬件组合**的特性（麦克风收音头 + 音频接口 + 驱动程序），换了麦克风，这个数字就得重测，不能沿用电脑内置麦克风测出来的结果。所以工具设计成设备可替换：`--input-device`/`--output-device` 指定要用哪个设备，不指定就用系统缺省。

## 用法

先看有哪些设备可以选：

```bash
cd 学习用/
source score_to_reference/.venv/bin/activate
python3 -m experiments.latency_test.calibrate --list-devices
```

会列出类似这样的东西：

```
  0 iPhone 6s Plus麦克风, Core Audio (1 in, 0 out)
> 1 MacBook Air的麦克风, Core Audio (1 in, 0 out)
< 2 MacBook Air的扬声器, Core Audio (0 in, 2 out)
```

跑校准（不指定设备的话用系统缺省，也就是现在测电脑内置麦克风的方式）：

```bash
python3 -m experiments.latency_test.calibrate --clicks 10 --interval 1.0 \
  --save-result latency_calibration.json \
  --save-wav recording.wav
```

**之后真正的麦克风接上以后**，用 `--list-devices` 找到它的编号或名称，一样的指令换个设备参数重跑：

```bash
python3 -m experiments.latency_test.calibrate --input-device 3 --output-device 2 \
  --clicks 10 --interval 1.0 \
  --save-result latency_calibration_real_mic.json
```

会印出：
- 每个 click 真实时间 vs 侦测到的时间，逐一列出
- 平均延迟、jitter(标准差)——用 median absolute deviation 抓离群值(背景杂音误触发)并排除，避免单一次杂音把整个统计数字拉歪
- `--save-result` 存的 json 档会记录设备名称、延迟、jitter，给之后串接 `scoring` pipeline 时用

## 这个延迟数字要怎么用

`scoring.ScoringConfig` 的缺省容忍度 `tol_ms` 通常是 50ms 这个量级。如果系统延迟有 100+ms，之后把麦克风侦测到的音符喂进 `scoring` 之前，要先把每个 onset 时间**减掉**这个延迟值做修正，不然每个音符都会被误判成 `timing_off`（因为整批音符的时间都系统性地偏移了同一个方向，这其实不是用户弹得不准，是传感器本身的延迟）。

## 已知限制

- 只测时间（onset 侦测延迟），不测音高——因为这里假设侦测到的音符集合本身音高是已知的(例如来自 MIDI 键盘或琴键传感器)，麦克风只是拿来抓「什么时候」，不是「弹了哪个音」
- click track 用固定 2000Hz 短音爆发仿真敲击声，跟真实钢琴的音色/衰减曲线不同，onset 侦测器对两者的反应速度可能略有差异——这个校准值是「系统对一般清晰瞬态声音的反应时间」的估计，不是「对钢琴声音」的精确测量
- 需要 `sounddevice`（底层用 PortAudio）能抓到你指定的设备；如果是通过 USB 或特殊音频接口接的传感器，可能需要额外的驱动程序才会出现在 `--list-devices` 的清单里
