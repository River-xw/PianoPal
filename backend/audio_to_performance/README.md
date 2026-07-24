# audio_to_performance

把单人单钢琴的麦克风录音，转成 [scoring](../scoring) 引擎吃的 `performance.json`。跟先前 `latency_test` 那套用通用 onset 侦测（librosa spectral flux）的做法不同——这里用 Spotify 的 **basic-pitch**，一个真正训练过的复音钢琴转谱神经网络，而不是「有没有声音突然变大声」这种通用方法。

## 目前的建议用法：已知曲谱时，评分学生录音改用 `grade_audio_reference_constrained.py`

**评分「学生录音 vs 已知曲谱」这个主要场景，现在改用 `scripts/grade_audio_reference_constrained.py --mode reference-dtw`（不经过 basic-pitch），不再用 `scripts/grade_audio.py`。**（`reference-grid` 模式仍在，但已不是 production 缺省——见下方「`reference-grid` 换成 `reference-dtw`」一节。）

原因：这台 BF-3738C 电子琴的音色跟 basic-pitch 训练用的真钢琴差很多，一直有「多余音符」(harmonic bleed 误判成新音符)的问题，就算加了 `suppress_harmonic_extras` 之类的heuristic 也只能减少、不能根除。

实测拿曲库里5首完全落在22个白键范围内的歌(其余6首含黑键/超出范围，用keybank合成会不公平)，各自合成成真实音色音档，同一份音档分别跑两条路径评分：

| 曲目 | refgrid分数 | bp分数 | refgrid(对/错音/漏/多) | bp(对/错音/漏/多) |
| --- | --- | --- | --- | --- |
| 10_little_indians | 92.96 | 90.49 | 66/0/5/0 | 69/0/2/5 |
| alabama | 95.10 | 87.37 | 97/0/5/0 | 95/5/2/9 |
| pachelbel_canon_bpno | 96.15 | 93.97 | 100/0/4/0 | 102/0/2/2 |
| silent_night_easy | 100.00 | 93.79 | 74/0/0/0 | 72/0/2/1 |
| twinkle_twinkle | 97.10 | 92.17 | 67/0/2/0 | 69/0/0/4 |
| **合计(438个音符)** | | | **404/0/16/0** | **407/5/8/21** |

`reference-grid` 每一首歌分数都比 basic-pitch 高，而且**5首歌加总 0 个 extra、0 个 wrong_pitch**——不是单一首歌的偶然结果。basic-pitch 抓到的音符总数略多(漏音较少)，但代价是 21 个 extra + 5 个 wrong_pitch，这就是一直存在的「泛音误判成新音符」问题；`reference-grid` 完全不会有这个毛病，因为它从头到尾只在已知候选音高集合里验证，不会凭空多冒出音符。

`reference-grid` 模式（`reference_constrained.py` 的 `transcribe_reference_constrained`）完全不猜音高——已知曲谱的每个音符各自在对应时间点的音档窗口里验证「参考音高的证据够不够强」，不会像 basic-pitch 那样把泛音误判成独立新音符。漏掉的16个音，一部分是已知的 F3 硬件特性(基频弱)这类个别键的问题，其余属于还可以调参数优化的范围(见下方)，不是新 bug。

## `reference-grid` 换成 `reference-dtw`：真人录音的节奏浮动(rubato)问题

`reference-grid` 对着上面表格里**合成音档**(节奏跟 MIDI 一模一样、零浮动)表现很好，但拿真人在树莓派上实际弹奏的录音测试时，发现分数异常低(30-45分)、`missed` 数量异常高，一度怀疑是门槛(`min_ref_score_ratio`/`min_winner_confidence`)设太严——实测扫过整个门槛范围(0.65 到 0.05)，「弹对」跟「刻意弹错」两份录音的分数差距始终在 ±4.3 分以内，证实**门槛不是问题**。

真正原因：`reference-grid`(`_estimate_time_alignment`) 只用**一条全域线性时间缩放**把参考谱的每个音符投影到音档时间，再开一个固定 ±0.16 秒的窗口验证音高。真人弹奏一定有节奏浮动(忽快忽慢)，浮动累积起来很容易让后面的音符整个投影到音档里错误的位置，窗口验证的其实是不相干的音档片段——这才是漏弹率长期异常偏高的根本原因，不是门槛。

`reference-dtw`(`transcribe_reference_dtw`)的做法：先侦测音档里**真实的**起音时间点(不假设格子时间)，再用 DTW 把参考谱的音符事件(和弦视为一个事件)对齐到侦测到的起音——对齐的成本主要看每个起音的音高证据撑不撑得起参考音符期望的音高，时间只当作极弱的「大概同一个相对位置」提示，用来消歧 Twinkle Twinkle 这种大量重复同一音高的曲子，不是像 `reference-grid` 那样的硬窗口。对齐完之后把结果丢回既有的 `score_performance()`(`backend/scoring/align.py`)，让它自己的 DTW+分段节奏曲线去做最终的 correct/timing_off 判断——这部分逻辑不用重写，本来就是为了处理真人演奏节奏浮动设计的。

实测（4份树莓派真人录音，69音符的 Twinkle Twinkle，漏弹数）：

| 录音 | reference-grid 漏弹 | reference-dtw 漏弹 |
| --- | --- | --- |
| normal(正常弹) | 44 | 3 |
| fast(弹快) | 29 | 6 |
| mistake(故意弹错) | 37 | 2-4 |
| right(只弹右手) | 38 | 17-18(本来就只弹一半，合理) |

`--emit-wrong-pitch`(现在缺省打开，用 `--no-emit-wrong-pitch` 关掉)让「弹错的音」不再被吞成笼统的 `missed`，而是明确标出「弹了什么」——实测对着 mistake 录音里刻意弹错的位置（第 1 小节的 G4 弹成了 F4），debug 输出精准对上：`pitch_ref=67(G4) → pitch_perf=65(F4), status=wrong_pitch`。（这个对应的确切 ref_index 会随节奏曲线/DTW 算法微调而变动——上面这组数字是照目前这版验证过的，不是写死的常数；有疑问时直接重跑 debug JSON 核对最准。）

代价：对着上面表格那种零浮动的干净合成音档，`reference-dtw` 分数比 `reference-grid` 略低(twinkle_twinkle: 97.1→91.1)，因为 DTW 自己重新拟合的节奏曲线在完全规律的输入上反而引入一点点杂讯；相对于真人录音的漏弹率大幅改善，这个取舍是值得的。

**这条路线原本有三个严重 bug 已修好**：

1. 时间对齐原本用一个粗略的「音档哪里有声音」RMS 门槛估计，28秒的曲子会累积将近0.7秒的误差，导致后半首歌大量误判成 `missed`（分数曾经只有42分）。改成用模块里已有的 onset 侦测去对齐第一个/最后一个音符的时间，才修正回 95分以上。
2. `synthesize_reference_from_keybank.py` 原本把整首歌的音符全部混进**同一个长 buffer**——但每个 keybank 样本的自然衰减(常常超过1秒)比大部分歌曲的音符间距(常常0.5-0.6秒)长很多，导致连续听整首歌会有明显的残响堆栈、「一前一后」的黏糊感(耳朵听得出来，但单一和弦的攻击时间点本身是对的，物理量测也量不太出明显差异)。改成**照小节切开、每个小节独立合成再首尾接起来**(见下方)之后，5首歌整体评分也从399→404对、43→21个basic-pitch的extra，听感更干净。
3. **完全没人弹琴的录音，曾经被判成大部分音符都「弹对」**（真实案例：一段纯环境杂音的录音，102个音符里84个被判对，分数82分）。原因是 `confidence`/`ref_ratio` 这两个判定指标**只比较候选音高彼此之间的相对占比**，纯杂讯在约9个候选音高之间本来就会随机分配不均，随便一个「运气好」拿到 0.22-0.38 的相对占比太正常了，刚好超过 `min_winner_confidence=0.18` 这个门槛——从头到尾没有检查过「这里到底有没有真的发出声音」的绝对音量。修法：加一个 `_estimate_energy_floor()`，用这份录音自己「参考谱最后一个音之后」的真实静音尾段校准本次录音的杂讯水准，音符窗口的能量没有明显超过这个杂讯水准就直接判 `missed`(标记 `below_noise_floor`)，不管候选音之间的相对比例好不好看。拿同一份纯杂讯录音重测：102个全部正确判成漏弹，分数变回0分；拿真的有弹奏的合成音档重测，5首歌的分数/对错数字完全没变，证实这个门槛没有误伤真正弹对的音符。

**没有被取代的部分**：`transcribe.py`/`pipeline.py`/`preprocess.py`/`postprocess.py` 这些 basic-pitch 模块保留，`validation/roundtrip.py` 等内部验证工具还在用它们做「合成音档反向验证 MIDI 转谱」这件事，跟「评分学生录音」是不同用途。`grade_audio.py` 本身也还在，没有删除，只是不再是评分学生录音的缺省工具。

## 为什么要换掉之前的方法

之前用 `latency_test` 测试过两首完全不同的曲子（Für Elise 真实演奏、Bach前奏曲排除rubato变因），都得到同样的结果：**72% 的音符完全没被侦测到**，而且从头到尾没有音高信息（只能判断「有没有声音、什么时候」，判断不了「弹了哪个音」）。这是通用 onset 侦测方法在复音、连续钢琴音乐上的已知天花板，不是调参数能解决的。

basic-pitch 是不一样量级的工具：它是专门训练来做「polyphonic automatic music transcription」的模型，同时输出音高、起始时间、结束时间。在这个模块的端对端测试里（合成一段C大调分解和弦），4个真实音符全部被正确辨识成 `correct`（音高、时间都对），`missed: 0`——相较之前的72%漏侦测，是质的差异。

## 安装（注意：需要 Python 3.11，不是 3.14）

`basic-pitch` 的依赖链（主要是 `resampy`/`numpy` 的原代码包）在 Python 3.14 上编译不起来，因为里面用到已经被移除的 `pkgutil.ImpImporter`。这个项目其他模块能在 3.14 上跑，但这个模块需要自己的 Python 3.11 虚拟环境：

```bash
brew install python@3.11   # 如果还没装
cd <repo根目录>
python3.11 -m venv backend/audio_to_performance/.venv
source backend/audio_to_performance/.venv/bin/activate
pip install -r backend/audio_to_performance/requirements.txt
pip install music21   # backend.scoring 会 import backend.score_to_reference，间接需要这个
```

**另一个安装陷阱**：`setuptools` 从某个版本开始把 `pkg_resources` 整个移除了（resampy 还在用这个旧 API），所以 `requirements.txt` 里特别钉住 `setuptools<81`。如果你自己手动升级过 setuptools，可能又会踩到这个错误，消息长这样：

```
ModuleNotFoundError: No module named 'pkg_resources'
```

重新 `pip install "setuptools<81"` 就能解决。

## 用法

### CLI

```bash
python -m backend.audio_to_performance 录音.wav -o performance.json --save-midi 转谱结果.mid
```

加上前处理（缺省全部关闭，见下方说明）：

```bash
python -m backend.audio_to_performance 录音.wav -o performance.json \
  --denoise --bandpass --normalize \
  --onset-thresh 0.6 --frame-thresh 0.4
```

### 当 Python 套件用

```python
from backend.audio_to_performance import transcribe, AudioToPerformanceConfig

# 从文件
performance = transcribe(wav_path="录音.wav")

# 从内存里的 numpy array(例如即时录音的 buffer，不用先写档)
performance = transcribe(audio=my_audio_array, samplerate=44100)
```

`performance` 的格式跟 `scoring.midi_io.midi_to_performance()` 输出的完全一样——因为内部就是直接调用那个函数，两条输入路径（真的 MIDI 键盘 vs. 麦克风转谱）共用同一份「什么是一个 performance 音符」的定义，没有另外发明一套 schema。

## 前处理为什么缺省关闭

`denoise`(降噪)、`bandpass`(限制在钢琴音域 27.5-4186Hz)、`normalize`(音量正规化)都做了，但缺省**全部关闭**。原因：basic-pitch 是拿相对干净的原始音频训练的，这些前处理步骤可能会削弱或扭曲音符起始瞬间的瞬态信号——而模型正是靠这个瞬态判断「这里有一个新的音符开始了」。降噪尤其容易把攻击瞬间磨平。想打开前，建议先关/开各自测一次，比较实际转谱结果，不要缺省「处理过的音频一定比较好」。

## 转谱出来的「多余音符」问题（`--suppress-harmonics`）

拿真实录音实测发现：转谱结果里有不少 `extra`(参考乐谱里没有对应的音符)，但这些不是随机幻觉。实际比对一份 Bach 前奏曲的录音发现：

- 84% 的 extra 音符，都出现在某个「真的、被正确配对」的音符附近(150毫秒以内)
- 其中 58% 跟那个真音符差一个八度、完全五度、或完全四度——古典的泛音/共鸣音程
- extra 音符的音量中位数(50)明显比真音符(73)小、拖长时间也短很多(0.28s vs 0.86s)

也就是说：多数 extra 是钢琴自己的泛音、或延音踏板的共鸣，被 basic-pitch 误判成一个新按下的音符，不是转谱逻辑乱猜。

一开始想用单纯的音量门槛滤掉，但发现 extra 跟真音符的音量分布重叠太多——设门槛滤掉六成 extra，也会误杀一成真音符。所以改成更精准的条件（`postprocess.py`）：**只有同时满足「时间够近」+「音程是八度/五度/四度」+「音量明显比旁边那个真音符小」，才会被丢掉**。这样可以放过：单独弹的小声音符（没有旁边音符可比较）、真的刻意八度加倍的和弦（两个音量差不多大）。

实测效果（同一份录音，同一份转谱结果，只是套用这个过滤器）：extra 从 358 降到 264(-26%)，总分从 60.69 提升到 62.4。不是完美解法（真音符也会被误杀一些，`correct` 从451掉到437），但净效益是正的。

缺省关闭，用 `--suppress-harmonics` 打开：

```bash
python -m backend.audio_to_performance 录音.wav -o performance.json --suppress-harmonics
```

## 限制式验证(`constrained_verification.py`)：用已知的参考谱缩小搜索范围

basic-pitch 是自由(不受限)的复音转谱——在整个钢琴音域里自己猜每个音是什么。这正是八度误判的根源：2*f0 在物理上就跟高八度的音重叠，钢琴的非谐性(inharmonicity)在低音区还可能让泛音比基音更强，模型有时候会挑到泛音而不是基音。但既然我们通过 `reference.json` 已经知道「这个时间点应该是哪个音」，就不需要每次都做开放式转谱——可以只在一个很小的候选音高集合里（预期音高本身 + 最可能搞混的几个音）比对原始音频证据，而不是照单全收 basic-pitch 给的猜测。

这是叠加在既有 pipeline **之上**的一层，不是取代它：只重新查看 `result.json` 里已经被标记 `wrong_pitch`/`missed` 的音符。

- **候选集合**(`get_candidates`)：参考音高本身 + `±1、±2、±12、±24` 半音——涵盖近似音跟一/二个八度的误判。等实体键盘到了，把 `keyboard_range=(最低音, 最高音)` 设进 `ConstrainedVerificationConfig`，可以滤掉物理上键盘根本弹不出来的候选音(见代码里的 TODO)。
- **泛音感知评分**(`score_candidate`)：从 CQT 读每个候选音基频位置的能量，如果某候选音刚好是集合里另一个候选音的高八度、而且自己的能量明显比那个低音候选音弱(缺省门槛：不到 0.4 倍)，就大幅打折——代表这很可能只是泛音，不是真的独立按下的音。
- **逐音重新验证**(`reverify_note`)：赢家 = 参考音高 → 改判 `corrected_octave_or_harmonic_error`；赢家 = 原本 basic-pitch 猜的音 → 维持原状(证实真的弹错/没侦测到)；赢家是集合里其他候选音 → 改判 `reverified_different_pitch`；没有候选音的信心度(占全部候选音能量的比例)超过门槛 → 维持原状，标 `reverification_inconclusive`，绝不乱猜。
- **独立的「未预期起音」扫描**(`scan_unexpected_onsets`)：上面的方法结构上只会去参考谱「预期有音符」的地方找证据，看不到完全不在预期范围内的音符。这里改用最单纯的 onset-strength 包络线(不管音高)扫过整段录音，找出离所有已知起音(参考谱 + `result.json` 里已经配对过的起音)都太远(缺省 >0.2秒)的起音，标成 `possible_unscored_extra_onset`——纯信息性质，不会自己生一个配了分的音符，因为我们还不够确定它的音高。

## 音色不符实体乐器：改用实体按键录音的样本比对(`keybank.py` / `keyboard_profile.py`)

旧版 `timbre_fingerprint.py`（每个键的 CQT 指纹、比对候选音）已移除，改用另一套机制：直接录一段「从左到右弹过全部37个键」的音档，按物理顺序切成一段一段的样本(`train_keybank_from_scale.py` → `keybank.py`)，不靠音高侦测去猜每一段是哪个音——因为这台琴的音色本来就容易让音高侦测器(pYIN、basic-pitch)误判，用弹奏顺序当标签才可靠。

- **`keybank.py`**：从左到右的音阶录音侦测 onset、依序切割粘贴 midi 标签，同时算每个键的泛音能量统计；额外用 pYIN 做一个「诊断用」复核，跟物理顺序标签差超过 0.75 半音就标记 `pyin_octave_or_pitch_disagrees_with_order_label`——但这只是诊断信息，不影响标签本身。
- **`keyboard_profile.py`**：把 keybank 的每键泛音统计整理成一份可重复使用的「这台琴听起来长怎样」的 profile。
- **`constrained_verification.py` 的 `keyboard_profile` 参数**：候选音评分时，如果这个候选音在 profile 里有记录，会用观测到的泛音能量分布跟 profile 模板做 cosine 相似度，加权叠加到原本的 CQT 能量分数上(不是整个切换，是额外加分)。
- **`synthesize_reference_from_keybank.py`**：直接照参考谱的音高、时间，从 keybank 找对应样本原音重播混音，不做任何 pitch-shift。**缺省照 `measure` 字段切成一个个小节分开合成、再首尾接起来**(没有 measure 信息时退回整首歌一次合成)，而不是把整首歌塞进同一个长 buffer——每个小节自己的音符「下一个音在哪」决定自己的尾音要收多短(`--legato-overlap-sec`，缺省0.08秒)，小节边界互不影响，也各自独立做 peak normalize。`--tail-sec` 只补在最后一个小节结尾。

### 另一条路：完全不用 basic-pitch 的「音对音」比对(`audio_reference.py` / `reference_constrained.py`)

上面的 `keyboard_profile` 只是叠加在 basic-pitch 转谱结果上的加分项，录音本身还是得先过一次 basic-pitch。这里是另一套独立机制，完全跳过 basic-pitch：

- **`reference_constrained.py`**：`_candidate_pitches()` 直接把候选音高锁死在 22 个白键(或整个键盘范围)——不是拿 basic-pitch 的猜测结果来筛选，而是从一开始就只在这个小集合里评分，`ReferenceConstrainedConfig` 可设 `allowed_pitches=WHITE_KEY_MIDIS` 限定白键模式。白键模式下，乐谱里不在 `allowed_pitches` 内的音符（黑键/超出范围）在转谱阶段就标成 `unsupported_pitch` 跳过；`scripts/grade_audio_reference_constrained.py` 的 `--white-keys-only` 进一步把这些音符从送进 `backend.scoring` 的参考音符清单整个剔除，所以它们不计分、也不会被算成 `missed`——而不只是转不出音而已。
- **`audio_reference.py`**：
  - `build_audio_reference()`：直接对一段「范例录音」做 onset 侦测 + 上面的候选音高评分，产生一份音频原生的参考谱(不需要对应的 MIDI/乐谱档)——`scripts/build_demo_audio_reference.py` 的实作。
  - `grade_student_against_demo()`：把学生录音一样做 onset+候选音评分，直接拿去跟这份「范例录音」的参考谱比对评分——完全是音档对音档，两边都不经过 basic-pitch——`scripts/grade_against_demo_audio.py` 的实作。
- **`train_keyboard_profile.py`**：另一种训练 profile 的方式，直接对任意录音跑 pYIN 抓稳定音高段落分组平均，不需要像 `keybank.py` 那样照顺序弹一次音阶（两者输出的 profile JSON 格式兼容）。
- **`scripts/grade_audio_reference_constrained.py`**：`grade_audio.py` 的替代品——用符号化参考谱(MIDI/MusicXML)+候选音限制的方式评分麦克风录音，同样完全不经过 basic-pitch。

**跟前面 `keyboard_profile` 叠加机制的差别**：前者仍然信任 basic-pitch 的转谱，只在它猜错时用泛音相似度去修正；这里是从根本上不信任 basic-pitch，只在已知候选音高集合里挑一个最像的。

**目前状态**：`reference_constrained.py` 是评分「已知曲谱 + 学生录音」的**缺省工具**，见本文开头。合成音档(零节奏浮动)用 `transcribe_reference_constrained`(`--mode reference-grid`)就已经很准；但真人录音有节奏浮动，production 缺省已改成 `transcribe_reference_dtw`(`--mode reference-dtw`，见上方「`reference-grid` 换成 `reference-dtw`」一节)。

`audio_reference.py` 的 `build_audio_reference()`/`grade_student_against_demo()`（没有已知 MIDI 曲谱，纯粹音档对音档）跟 `transcribe_onset_first`/`transcribe_reference_guided_onsets` 这两个模式，还停留在只跑过自我一致性检查的阶段——这两个模式受限于 `max_pitches_per_onset`(缺省1)，同一个时间点有两个音同时弹(和弦)时只会保留最强的那个，这在小星星这首歌(69个音符里有26个时间点是2音同时)已经证实会漏掉大量音符，还没有调过。

## 曲库预先已知：用单曲音域缩小 basic-pitch 的搜索范围(`song_range.py`)

> **目前状态**：`grade_audio.py` 整包被 Codex 版本覆盖后，暂时没有调用这个模块了(`--no-song-range`/`--ignore-timing` 这两个 CLI 参数也一并消失)。模块本身、测试都还在，下面的 A/B 数据依然成立，只是还没重新接回 `grade_audio.py`。

项目的曲库不是开放式的任意音档——每首歌的参考谱都预先知道，也就知道**这首歌实际会用到哪些音高**。之前测过把 basic-pitch 的 `minimum_frequency`/`maximum_frequency` 绑到整个钢琴音域(27.5-4186Hz)完全没效果，因为那个范围太宽、几乎没缩小到什么。单曲的音域通常窄很多，值得单独测。

拿11首真实曲子(FluidSynth合成音，走完整评分流程)实测扫过几种留白(padding)大小：

| padding | correct | wrong_pitch | missed | extra |
| --- | --- | --- | --- | --- |
| 不设范围 | 995 | 7 | 22 | 60 |
| ±1个八度(12半音) | 995 | 7 | 22 | 60（跟不设一样，留白太宽没缩到东西） |
| ±6半音 | 995 | 6 | 23 | **50** |
| ±3半音 | 995 | 6 | 23 | 50（跟±6一样） |
| 完全不留白(0) | **962** | 11 | **51** | 43（矫枉过正——曲子自己写的音刚好卡在边界也被切掉） |

**缺省用 ±6半音**：extra 从60降到50、wrong_pitch 7→6，代价只有1个添加的missed，干净的净改善。低于6没有额外好处，降到0直接爆掉(correct掉33个、missed多29个)——所以6是实测出来的甜蜜点，不是随便猜的。

`compute_song_frequency_range(reference, pad_semitones=6)`：算出这首歌实际音高范围(留白后)对应的Hz范围，喂给 `AudioToPerformanceConfig(minimum_frequency=..., maximum_frequency=...)`。`grade_audio.py` 缺省会用，`--no-song-range` 关闭。

用法：

```bash
python -m backend.audio_to_performance.constrained_verification result.json 录音.wav \
  --reference reference.json --keyboard-range 21 108 \
  -o augmented_result.json
```

## 运行测试

```bash
source audio_to_performance/.venv/bin/activate
cd 学习用/
python3 -m pytest audio_to_performance/tests -v
```

- `test_preprocess.py`：纯数学，合成 sine wave 测 bandpass/normalize/denoise，不需要真的录音档
- `test_postprocess.py`：纯数学，验证泛音过滤规则(八度/五度/四度+音量差)的各种边界情况
- `test_pipeline.py`：**会真的调用 basic-pitch 做推论**——用加法合成器(sine+泛音+包络线)生一段C大调分解和弦的假钢琴音频，跑完整 pipeline，检查转谱出来的音符数量、音高是否大致吻合(容忍度故意放宽，因为转谱本来就不会100%精确，这里测的是「整条路接得起来」，不是帮 basic-pitch 打分数)
- `test_constrained_verification.py`：全部用手造的假 CQT 能量数组测，不需要真的音频——候选音生成、泛音折扣逻辑(含「真的弹错不会被误压下去」的反例)、三种 reverify 结果、还有一个回归测试专门确认「不确定的时候绝对不会偷偷改状态」

## 37键实体键盘限制(`keyboard_range`，缺省打开)

项目的键盘只有37键(MIDI 48-84，C3-C6，唯一定义处在 `backend/hardware.py`)。这不是启发式规则而是物理事实：键盘弹不出范围外的音，所以**录「这台键盘」的音档里转谱出范围外的音，百分之百是误判**(通常是真音符的低八度/泛音鬼影)，直接删掉。两个地方都吃这个限制：

- `pipeline.transcribe()`：范围外的转谱音符直接过滤(`config.keyboard_range`，缺省 48-84)
- `constrained_verification`：八度候选音超出键盘范围的不列入考虑——边界效果特别好，例如参考音是最低键48时，往下八度的36/24物理上不存在，低频泛音就没机会赢

**唯一要注意的**：音档不是来自实体键盘时(例如 `validation/roundtrip` 拿任意MIDI合成的音频)必须设 `keyboard_range=None`，不然会把真实存在的范围外音符当误判删掉——`roundtrip.py` 已经自动处理，`scripts/grade_audio.py` 会依「参考谱是否落在键盘范围内」自动决定。如果键盘其实有八度移调(octave shift)设置，改 `backend/hardware.py` 一个地方即可。

## 文件结构

| 文件 | 作用 |
| --- | --- |
| `config.py` | `AudioToPerformanceConfig`：前处理开关 + basic-pitch 参数 + 后处理开关 + 键盘范围，全部集中一处 |
| `preprocess.py` | 降噪/bandpass/正规化，缺省全关 |
| `transcribe.py` | 包装 basic-pitch `predict()`，输出 `pretty_midi.PrettyMIDI` |
| `postprocess.py` | 泛音/延音踏板误判成新音符的过滤器，缺省关闭 |
| `pipeline.py` | 串起来：加载音频 → 前处理 → 转谱 → 存成MIDI → 调用 `scoring.midi_io.midi_to_performance()` → (可选)后处理过滤 |
| `constrained_verification.py` | 叠加层：用参考谱缩小候选音高范围，重新查看 `wrong_pitch`/`missed`，外加独立的未预期起音扫描；也是 `keyboard_profile` 加分机制的所在地 |
| `keybank.py` | 从左到右白键音阶录音训练样本库，供 `synthesize_reference_from_keybank.py` 原音重播用 |
| `keyboard_profile.py` | 把 keybank 的泛音统计整理成可重复使用的音色 profile |
| `reference_constrained.py` | 候选音高从一开始就锁在已知集合(白键/键盘范围)里评分，不信任 basic-pitch 的猜测 |
| `audio_reference.py` | 音对音比对：`build_audio_reference()` 从范例录音产生音频原生参考谱，`grade_student_against_demo()` 拿学生录音直接比对 |
| `cli.py` / `__main__.py` | `python -m backend.audio_to_performance ...` |
| `tests/` | 见上 |

## 重要限制

- **这是一个深度学习模型**——早期假设它太重，只能跑在笔电/云端，树莓派只负责录音+把音档传出去。后来 `experiments/benchmarks/basic_pitch_pi_bench.py` 实测 Pi 5 + ONNX Runtime 跑 basic-pitch 转谱，5-30 秒音档的推论时间只要 0.12-0.6 秒（比即时快 40 倍以上），证实这个顾虑不成立——`edge/practice_server.py`（前端实际在用的树莓派原生 orchestrator）现在就是直接在树莓派上调用 `scripts/grade_audio_reference_constrained.py`（进而调用这里的 `transcribe()`），录音、灯光引导、转谱评分全部在同一台树莓派上跑完，不需要额外的笔电/云端这一段。`scripts/session_server.py`（SSH 备案 orchestrator）仍然保留，给还没在树莓派上装评分依赖的情况用——这时转谱评分才会在 SSH 对面的开发机上跑
- 转谱不是100%准确，尤其是快速圆滑奏、踏板延音、极端音域的段落——这比通用 onset 侦测好非常多，但不是完美的
- 只处理单一钢琴音源，不是多乐器分离(没有用 Spleeter/Demucs 那类工具，也不需要，因为场景就是一台钢琴)
