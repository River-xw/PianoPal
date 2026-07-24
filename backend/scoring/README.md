# scoring

把用户弹的东西（一串音符）拿去跟 [score_to_reference](../score_to_reference) 产生的「正确答案」JSON 做比对，算出弹得准不准、准时不准时，回传一份结构化的评分结果。

假设是**理想、零延迟环境**：没有传感器、没有 onset 侦测，用户弹奏出来的就是一份干净、精准的音符清单（就像直接从 MIDI 键盘录下来的一样）。所以这整个模块做的事情，本质上是「符号音乐对齐」（symbolic music alignment）——用 DTW/edit-distance 把两串音符对起来，而不是处理音频或做 onset detection。

---

## 1. 核心设计：为什么要「先抓节奏曲线，再看个别音符」

用户练琴时常常会「整首都弹快了/慢了」，或是「弹到一半速度变了」（rubato、弹到熟悉的段落加速…）——这些都不是错误，只是选了不同的节奏。如果不处理这件事，一个弹得很稳、只是速度不同（或中途变速）的演奏，会被误判成每个音都迟到或抢拍。

所以评分分两层：

1. **节奏曲线（tempo curve）**：先用一轮粗略的「音高优先」DTW 找出「音高确实对得上」的音符当锚点，再用稳健回归（Theil-Sen，不是普通最小平方法，才不会被少数几个抓错的音符带偏）在这些锚点上分段（滑动窗口，`tempo_window_notes`/`tempo_window_step`）拟合出一条**分段线性**的节奏曲线（`align.TempoCurve`），而不是单一一条全域直线。这样真的中途变速（rubato、弹熟的段落加速）会被曲线吸收掉，不会被硬套一条全域直线后产生一堆虚假的残差。`global_tempo_ratio`（回传给前端显示的那个数字）是所有锚点的整体稳健回归斜率，纯粹给人看整体快慢用；实际拿来分类每个音符对错的，是这条曲线在该处的局部预测值，不是这个单一数字。
2. **局部误差（local error）**：每个音符实际弹奏时间，减掉节奏曲线在该处的预测值，剩下的残差才是这个音符真正的「抢拍/拖拍」误差（`offset_ms`）。

如果你已经知道用户是对着哪个 BPM 的节拍器弹的（`target_bpm`），就不用拟合节奏曲线了——直接把参考乐谱换算到那个 BPM（用 `backend.score_to_reference.to_seconds`），残差就是绝对值，不做回归（`global_tempo_ratio` 这时是 `null`）。

---

## 2. 安装

```bash
cd scoring
python3 -m venv .venv   # 或沿用 score_to_reference/.venv，两个套件装在同一个环境更方便
source .venv/bin/activate
pip install -r requirements.txt
```

**重要**：`backend.scoring` 依赖 `backend.score_to_reference`（用来调用 `to_seconds`）。运行时的**工作目录**请放在仓库根目录，这样 `import backend.score_to_reference` 才找得到路径：

```bash
cd <repo根目录>          # 不是 cd backend/scoring/
python -m backend.scoring ...
```

---

## 3. 当作 Python 套件使用

```python
from backend.scoring import score_performance, ScoringConfig
import json

reference = json.load(open("reference.json"))      # score_to_reference 产生的 JSON
performance = json.load(open("performance.json"))    # 用户弹的音符清单

result = score_performance(reference, performance)
print(result.summary.score)          # 0-100 总分
print(result.summary.sub_scores)     # {"pitch":.., "rhythm":.., "timing_stability":.., "hand_shape":..}
print(result.summary.global_tempo_ratio)  # 例如 0.95 = 整体弹快了一点（target_bpm 有给的话是 None）
```

如果用户是对着已知 BPM 的节拍器弹的：

```python
result = score_performance(reference, performance, target_bpm=90)
```

自订门槛/权重全部集中在 `ScoringConfig`（不用改代码）。**注意两组容易混淆的字段**：`w_pitch`/`w_time`/`gap_penalty` 是 DTW **对齐**的成本函数（决定哪个演奏音符对应哪个参考音符），跟 `score_weight_pitch` 这组**评分**权重（决定总分怎么加权三/四个子分数）是完全不同的两件事：

```python
config = ScoringConfig(
    tol_ms=30,                      # 分类容忍度收紧到 30ms
    score_weight_pitch=0.5,         # 总分里「音高准确率」的权重
    score_weight_hand_shape=0.25,   # 打开手型评分维度（见第 5 节）
)
result = score_performance(reference, performance, config=config, hand_shape_score=92.0)
```

其他值得知道的 `ScoringConfig` 选项：

- `tol_beat`：用「几分之几拍」而不是固定毫秒数当容忍度（例如 `1/16`），会依当下 BPM 换算成有效的 `tol_ms`（`effective_tol_ms()`）；给了就会盖过 `tol_ms`。
- `ignore_timing`：设 `True` 直接整个关掉节奏这个维度——音高对就一律是 `correct`（不会有 `timing_off`），`offset_ms`/`timing`都是 `None`，`timing_stability` 也不计算，总分只剩音高+节奏准确率两项（权重自动重新正规化成加总 1.0）。拿真人麦克风录音诊断「音高/转谱准不准」时很好用——演奏者天生的节奏弹性不然会盖过真正想看的问题。
- `suppress_harmonic_extras`（缺省开）：麦克风转谱常常在正确音符的高八度/高八度+五度/高两个八度同时听到一个泛音假信号，被判成「多弹」——这个选项会在对齐**之后**（只动已经被分类成 `extra` 的音符，不可能误删真正对上参考谱的音符）把这类泛音杂讯滤掉，被滤掉的数量记在 `summary.harmonic_extras_removed`。

### 从 MIDI 录音产生 performance.json

```python
from backend.scoring import midi_to_performance

performance = midi_to_performance("用户录音.mid")
```

---

## 4. CLI

```bash
python -m backend.scoring reference.json performance.json -o result.json
python -m backend.scoring reference.json performance.json -o result.json --bpm 90
```

---

## 5. 输出结构（result.json）

```jsonc
{
  "summary": {
    "score": 77.19,                 // 总分 0-100
    "sub_scores": {
      "pitch": 82.35,               // 音高准确率
      "rhythm": 78.57,              // 节奏准确率（已依音高覆盖率打折，见下方公式）
      "timing_stability": 64.1,     // 节奏稳定度（同样已依覆盖率打折）；权重=0 时是 null，不是 0
      "hand_shape": null            // 手型/姿势评分；没有外部传入分数或权重=0 时是 null
    },
    "global_tempo_ratio": 0.95,     // 整体速度比例；target_bpm 有给的话这里是 null
    "tempo_trend": "accelerating",  // accelerating(越弹越快) / steady / decelerating
    "counts": {"correct": 11, "timing_off": 3, "wrong_pitch": 1, "missed": 1, "extra": 1},
    "harmonic_extras_removed": 2,        // 被滤掉的泛音假信号数量（见第 3 节 suppress_harmonic_extras）
    "octave_slips_in_wrong_pitch": 1      // wrong_pitch 里刚好差整数个八度的数量（常是转谱的八度误判）
  },
  "notes": [
    {
      "ref_index": 2, "perf_index": 2,
      "pitch_ref": 64, "pitch_perf": 63,       // 应该弹 64，实际弹了 63
      "name": "E4",
      "onset_ref_sec": 1.2, "onset_perf_sec": 1.14,
      "offset_ms": 0.0,
      "status": "wrong_pitch",                  // 见下方分类说明
      "timing": "accurate",                     // 音高错了，但时间点是准的
      "measure": 1, "hand": "R",
      "dur_beats": 1.0                          // 来自参考乐谱的音符长度（拍）；extra 音符没有这个值
    }
  ]
}
```

`dur_beats` 是给 `viewer` 画五线谱用的（要知道画四分音符还是八分音符）。只有 `correct`/`timing_off`/`wrong_pitch`/`missed`（都有对应的参考音符）会带这个值；`extra` 音符没有参考答案可以对，这个字段会是 `null`。

### 分数公式（都写在 `score.py` 的 docstring 里，这里摘要）

- **pitch accuracy** = (correct + timing_off) ÷ (correct+timing_off+wrong_pitch+missed+extra) × 100 —— 有弹对音高的比例
- **rhythm accuracy** = pitch_accuracy × correct ÷ (correct + timing_off) —— 音高对的音符里时间点准的比例，再乘上 pitch_accuracy 做覆盖率修正，这样「漏弹大半首、剩下几个音卡得很准」不会被打成节奏满分
- **timing stability** = pitch_accuracy × [100 ÷ (1 + std(offset_ms) / tol_ms)] —— 同样先算误差标准差=0时是100分、标准差=容忍度时是50分，再乘上 pitch_accuracy 做覆盖率修正；`score_weight_timing_stability=0`（缺省）时整个不计算，回传 `null`
- **hand_shape** —— 完全是外部传入的分数（`score_performance(..., hand_shape_score=...)`），这个模块本身不碰任何传感器/影像；`score_weight_hand_shape=0`（缺省）或没有传入分数时回传 `null`。目前唯一会真的算出非 `null` 分数喂进来的调用端是 `edge/practice_server.py`（见该模块说明的 IMU 姿势分类器集成）
- **overall** = 对「当下实际可用」的子分数做**重新正规化**的加权平均——`timing_stability`/`hand_shape` 为 `null`（维度关闭，或该次传感不可用）时，不是直接当 0 分贡献拖低总分，而是把它的权重份额从分母中移除、其余子分数的权重按比例放大凑回 1.0。例如手型传感器没接上、其余三项都满分，`overall` 依然是 100，而不是被扣掉 `score_weight_hand_shape` 那一份权重

### status / timing 分类逻辑

| status | 意思 |
|---|---|
| `correct` | 对齐成功、音高对、时间在容忍度内 |
| `timing_off` | 对齐成功、音高对，但时间点超出容忍度（`timing`字段会标 `rush`抢拍或`drag`拖拍）|
| `wrong_pitch` | 对齐成功但音高不对——**不会**被拆成「漏弹+多弹」两笔，而是保留成一笔「弹错」|
| `missed` | 参考乐谱里有、但用户没弹的音 |
| `extra` | 用户弹了、但参考乐谱里没有对应的音（扣掉被判定是泛音假信号、已经被滤掉的那些） |

---

## 6. 和弦/复音怎么处理

`chord_window_sec`（缺省 30ms）内的音符会被视为同一个「事件」，并且**依音高排序**后才拿去比对——这样就算用户弹和弦时手指落下的顺序跟参考不同，或输入的音符清单顺序不同，也不会被误判成音高错误或漏弹/多弹。细节在 `align.py` 开头的说明。

---

## 7. 运行测试

```bash
cd 学习用/
source backend/audio_to_performance/.venv/bin/activate   # 或你自己装好依赖的环境
python -m pytest backend/scoring/tests -v
```

21 个测试（`test_scoring.py` + `test_tempo_curve.py`）涵盖：满分演奏、整体变速被正确吸收、中途变速（rubato）被分段节奏曲线吸收而非累积成假残差、杂讯越大分数越低、局部抢拍被抓到、删除/插入/改音高分别对应 missed/extra/wrong_pitch、抢拍与拖拍等量对称扣分、输出决定性（同输入同输出）、和弦比对、`tol_beat` 换算、`ignore_timing` 关闭节奏维度后的权重重新正规化。

---

## 8. 文件结构速查

| 文件 | 作用 |
|---|---|
| `align.py` | 核心比对逻辑：事件分组、分段稳健节奏曲线拟合（`fit_tempo_curve`/`TempoCurve`）、两阶段 DTW |
| `score.py` | 把对齐结果转成 status/timing 分类，算出子分数与总分，泛音假信号过滤（`_suppress_harmonic_extras`） |
| `config.py` | 所有门槛/权重集中在 `ScoringConfig` 一个 dataclass |
| `models.py` | 输出用的 dataclass（`NoteResult`、`ScoringSummary`、`ScoringResult`） |
| `midi_io.py` | `midi_to_performance()`：把 MIDI 录音转成 performance.json 格式 |
| `cli.py` / `__main__.py` | `python -m backend.scoring ...` |
| `tests/` | pytest，全部用手写的小型 reference dict，不需要外部文件 |

## 9. 已知限制

- 依赖同层的 `score_to_reference` 套件（见第 2 节的工作目录注意事项），不是独立可安装的套件
- 没有处理任何音频/传感器层面的东西——上游必须先把演奏转成干净的符号音符清单；`hand_shape` 也是纯粹接收外部分数，不做任何姿势推论
- DTW 是 O(N×M) 全表计算，对非常长的曲子（数千个音符以上）会变慢；目前没有做band-限制的优化
