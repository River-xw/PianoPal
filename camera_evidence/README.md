# camera_evidence

用镜头看到的「指尖在哪个琴键上」，当作跟音频完全独立的第二证据来源，去解决 `audio_to_performance`/basic-pitch 的**八度误判**问题。

## 为什么需要这个模块

音频本身有个先天模糊性：一个音符跟它高八度、完全五度的泛音，在频谱上长得很像，basic-pitch 偶尔会把泛音误判成主音（或反过来）。`validation/roundtrip.py` 已经证实这个问题确实存在（详见该模块的验证报告）。

但物理上的琴键位置完全没有这个模糊性——C4 跟 C5 是键盘上两个不重叠的像素区域，镜头看到手指压在哪里，不会有「泛音」这种东西。所以：音频负责「什么时候弹了、听起来是哪个音」，镜头负责「这个时间点手指压在哪个键上」，两者对不上的时候，镜头的空间证据可以帮忙判断音频到底是不是八度误判。

**目前没有镜头硬件**，所以这个模块完全用合成的指尖位置数据开发跟测试（`SyntheticFingertipSource`），等硬件到了再接上真的 MediaPipe 手部侦测（`MediaPipeFingertipSource`，目前只是一个会丢 `NotImplementedError` 的 stub）。

## 范围：只做「这个时间点手指在哪」，不做「有没有按下去」

镜头**不**负责侦测按键的 onset 时间点——那个仍然由音频/IMU 负责。镜头只回答一个很单纯的空间查找：「在某个时间戳记，手指位置对应到哪个琴键」。这个范围限制很重要，直接影响到 `missed` 音符的处理方式：镜头看到手指压在正确的键上，只能说「有手指在那里」，不能证明「真的按下去发出声音了」（可能只是手指悬停、或按得太轻音频没收到）。所以对 `missed` 音符，这个模块只会加注记（`camera_suggests_missed_detection`），**不会**自己生出一个音频从未确认过的音符。

## 用法

### 1. 校准镜头（`calibration.py`）

一次性设置，镜头位置不变就不用重做。给定键盘可见范围的四个像素角点，加上这个范围涵盖的 MIDI 音高范围：

```python
from camera_evidence import calibrate, save_calibration

calibration = calibrate(
    top_left=(120, 80), top_right=(1050, 60),
    bottom_left=(100, 420), bottom_right=(1080, 400),
    lowest_pitch=48, highest_pitch=84,  # 37键键盘范例
    camera_id="raspi-cam-1",
)
save_calibration(calibration, "calib.json")
```

角点不需要是正方形——内部用完整的透视变换（homography）处理摄影机角度造成的透视变形，不是简单假设轴对齐矩形。白键在校准宽度内平均分布；黑键用标准钢琴排列（E-F、B-C 之间没有黑键）算出较窄的区域，且只占琴键深度前面一部分（`black_key_depth_ratio`，黑键摸不到键盘最前缘）。

```python
from camera_evidence import pixel_to_pitch, load_calibration

calibration = load_calibration("calib.json")
pitch = pixel_to_pitch(x=530, y=150, calibration)  # -> 一个 MIDI pitch，或 None（超出键盘范围）
```

### 2. 指尖位置来源（`fingertip_source.py`）

`FingertipSource` 是一个抽象接口（`get_position(timestamp_sec) -> (x, y) | None`），这样真正的镜头实作接上时，下游的比对逻辑完全不用改。

- **`SyntheticFingertipSource`**（现在用这个测试）：吃一份 `reference.json`，在每个参考音符的 onset 时间点「假装」手指压在正确的键上（经过 calibration 转成像素座标），可以加像素杂讯（`noise_px`）跟故意注入错误位置的几率（`error_rate`，仿真 MediaPipe 侦测失误）。
- **`MediaPipeFingertipSource`**：还没做，没镜头硬件可以测。等硬件到了再实作（追踪 MediaPipe Hands 的食指指尖 landmark，缓存 (timestamp, x, y)，`get_position()` 查最近的一笔）。

### 3. 交叉验证（`cross_validate.py`）——核心逻辑

吃 `scoring/` 产生的 `result.json` + 一个 `FingertipSource` + calibration，对每个 `wrong_pitch` 音符（尤其是差整数个八度的）跟每个 `missed` 音符做查找：

```python
from camera_evidence import apply_camera_evidence, SyntheticFingertipSource, load_calibration
import json

result = json.load(open("result.json"))
reference = json.load(open("reference.json"))
calibration = load_calibration("calib.json")
source = SyntheticFingertipSource(reference, calibration, error_rate=0.0)

augmented = apply_camera_evidence(result, source, calibration)
```

每个音符会多一个（可为 `None` 的）`camera_evidence` 字段，`status` 依情况可能被改写：

| 状况 | `status` 变化 | `camera_evidence.flag` |
| --- | --- | --- |
| `wrong_pitch`，镜头同意参考谱 | 改成 `camera_corrected_octave_error`，`pitch_perf` 覆写成 `pitch_ref` | `camera_corrected_octave_error` |
| `wrong_pitch`，镜头同意音频听到的音 | 不变（真的弹错，不是误判） | `camera_confirms_wrong_pitch` |
| `wrong_pitch`/`missed`，镜头证据跟两边都对不上（或没读到） | 不变（不乱猜） | `camera_evidence_inconclusive` |
| `missed`，镜头看到手指在对的键上 | 不变（镜头不能证明真的按下去了） | `camera_suggests_missed_detection` |

`summary.counts` 会依实际（可能被改写过的）状态重新统计，另外加一个 `summary.camera_evidence_summary` 统计各种镜头判决的数量。

### CLI

```bash
python -m camera_evidence result.json --calibration calib.json \
  --synthetic --reference reference.json --error-rate 0.1 --noise-px 5 \
  -o augmented_result.json
```

`--synthetic` 现在是唯一能跑的模式（没镜头硬件）；不加的话会尝试用 `MediaPipeFingertipSource`，直接印出清楚的错误消息说明还没做。

## 运行测试

```bash
python -m pytest camera_evidence/tests -v
```

全部用合成数据，不需要镜头：

- `test_calibration.py`：角点对应到范围两端音高、超出范围回传 `None`（含边缘容忍度）、黑键/白键在相邻像素解析成不同音高、标准排列（E-F、B-C 没黑键）
- `test_fingertip_source.py`：`error_rate=0` 时一定落在正确的键上
- `test_cross_validate.py`：+12 八度误判被镜头纠正、非八度的真实弹错音不会被误「纠正」、镜头证据矛盾时原状不动、`missed` 音符镜头支持时只加注记不生新音符

## 文件结构

| 文件 | 作用 |
| --- | --- |
| `config.py` | `CameraEvidenceConfig`：哪些状态触发镜头查找、校准边缘容忍度、黑键几何参数 |
| `calibration.py` | 像素角点 -> homography -> 白键/黑键版面，`pixel_to_pitch()` / `pitch_to_pixel()` |
| `fingertip_source.py` | `FingertipSource` 接口、`SyntheticFingertipSource`、`MediaPipeFingertipSource`（stub） |
| `cross_validate.py` | 核心比对逻辑，吃 `result.json` 吐出加注 `camera_evidence` 的版本 |
| `cli.py` / `__main__.py` | `python -m camera_evidence ...` |
| `tests/` | 见上 |

## 重要限制

- 镜头只做空间查找，不做 onset 侦测——这条界线是刻意的，不要在这个模块里加「自动补一个音符」的逻辑
- 目前完全没有真实镜头数据验证过；`SyntheticFingertipSource` 假设的杂讯/误判模型是合理猜测，等真的 MediaPipe 接上后，这里的杂讯参数需要用真实数据重新校准
- calibration 假设键盘是一个平面（单一 homography）跟标准钢琴黑白键排列，如果镜头角度太刁钻或看不到完整键盘，这个模型可能不够用
