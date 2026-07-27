# PianoPal

PianoPal 是一个钢琴陪练/评分系统：一台 37 键电子琴（BF-3738C）+ WS2812 灯条做即时按键引导，麦克风录音拿去跟乐谱比对算出音准/节奏分数，选配的手腕 IMU 传感器可以额外算一个手型/姿势分数，全部集成在一个网页前端里。

## 核心体验

前端（`frontend/viewer/`）是整个系统的入口，架构是：

```text
引导页（姓名 + Slogan）
  -> 主页（近期总结 + 三张导览卡片）
      ├ 学习模式：选歌 -> 灯光引导 + 录音 -> 宽松评分报告（存入历史）
      ├ 演奏模式：选歌 -> 无灯光、只录音 -> 严格评分报告（存入历史）
      └ 我的：历史纪录列表、用户画像、分数趋势图、多笔比对、导出
```

学习模式跟演奏模式**共用同一套评分引擎**（`backend.scoring`），差别纯粹是权重参数（见下方评分算法）跟要不要点灯。细节见 [frontend/viewer/README.md](frontend/viewer/README.md)。

## Current Data Flow

```text
POST /api/session/start（树莓派原生 orchestrator：edge/practice_server.py）
  -> ws2812_guide_song.py：LED 引导 + 麦克风录音（演奏模式用 --no-leds）
  -> posture_capture.py（选配，需要 BLE IMU 传感器才会启动）：即时手型姿势分类 -> 一个 0-100 分数
  -> scripts/grade_audio_reference_constrained.py
       -> backend.audio_to_performance（麦克风录音 -> 音符清单，reference-dtw 模式吸收真人节奏浮动）
       -> backend.scoring（符号音乐对齐 + 评分公式，见下方）
  -> data/formal_assessments/sessions/<用户>/<session_id>/result.json + backend.db.sqlite（practice_sessions 表）
  -> GET /api/history, /api/history/<id> 给前端「我的」页面
```

没有装评分依赖的树莓派可以用 `scripts/session_server.py`（SSH 遥控备案）取代 `edge/practice_server.py`，跑在开发机上、通过 SSH 遥控树莓派的灯光引导+录音。

## 评分算法（目前验证过的版本）

`backend.scoring` 做的是「符号音乐对齐」——把参考乐谱跟实际弹奏的音符清单，用两阶段 DTW 对齐起来：

1. 先用一轮音高优先的粗略对齐找出「确实弹对音高」的锚点，在这些锚点上用稳健回归（Theil-Sen）分段拟合一条**分段线性节奏曲线**，吸收用户整体变速或中途变速（rubato）——不会被误判成每个音都抢拍/拖拍。
2. 再用真正的对齐成本函数做第二轮 DTW，把每个演奏音符跟参考音符配对，分类成 `correct`/`timing_off`/`wrong_pitch`/`missed`/`extra`。

总分是最多四个子分数的**重新正规化加权平均**——某个子分数因为维度关闭（权重=0）或该次传感不可用而是 `null` 时，不会直接当 0 分拖低总分，而是把它的权重份额从分母移除、其余子分数按比例补回 1.0：

| 子分数 | 公式 | 说明 |
| --- | --- | --- |
| 音准（pitch） | (correct+timing_off) / 全部 × 100 | 音高弹对的比例 |
| 节奏（rhythm） | 音准 × correct/(correct+timing_off) | 音高对的里面，时间点准的比例，再乘音准做覆盖率修正 |
| 节奏稳定度（timing_stability） | 音准 × 100/(1+std(offset_ms)/tol_ms) | 缺省权重 0，不计算/不显示——真人麦克风录音上杂讯太大不可靠 |
| 手型（hand_shape） | 外部传入(IMU 姿势分类器) | 这个模块本身不做任何传感——见下方 |

学习模式（宽松：旋律/动作权重高、节奏均匀度不计）跟演奏模式（严格：三者均衡）**用同一个评分函数**，只是 `edge/practice_server.py`/`scripts/session_server.py` 的 `MODE_SCORE_WEIGHTS` 传不同的权重进去。详细公式、`tol_beat`/`ignore_timing`/泛音假信号过滤等选项，见 [backend/scoring/README.md](backend/scoring/README.md)。

**手型评分**：`edge/practice_server.py` 有设置 BLE IMU 设备时，`edge/posture_capture.py` 会即时分类手型姿势、把「正常姿势时间窗比例」换算成分数喂进评分公式；BLE、设置档或模型不可用时这个子分数是 `null`，套用上面的正规化逻辑排除，不会用固定占位分顶替，也不挡练习流程。分类器本身（`edge/raspi_runtime/posture.py`）跟训练数据/脚本见 [backend/sensors/README.md](backend/sensors/README.md)。

**黑键/超出范围音符**：BF-3738C 键盘只校准了 22 个白键（`data/bf3738c_keybank/`），乐谱里任何黑键或超出范围的音符会被 `scripts/grade_audio_reference_constrained.py`（`--white-keys-only`）整个从评分排除——不计分、也不算漏弹（`missed`），LED 引导（`edge/ws2812_guide_song.py`）同样只对有对应 LED 的白键点灯。这让含黑键的乐曲也能拿来练习，只是黑键部分不参与引导与计分。

## Repository Structure

```text
.
├── backend/                 # Python 函数库：乐谱解析、音频转谱、评分、验证
│   ├── audio_to_performance/ # 麦克风录音 -> 演奏音符清单（reference-dtw 对齐麦克风音准转录）
│   ├── score_to_reference/   # MusicXML/MIDI 乐谱 -> 标准化参考 JSON
│   ├── scoring/               # 参考 vs 演奏比对 -> result.json（详见上方算法说明）
│   ├── db/                    # 本地 SQLite 索引（用户/曲目/练习纪录/文件路径）
│   ├── sensors/               # IMU 封包格式、CSV 解析、关键时间窗切割
│   └── validation/            # 转谱品质的往返验证
├── camera_evidence/         # 用镜头看指尖位置，当作解决音准转谱八度误判的第二证据来源（目前没有镜头硬件，只用合成数据测过）
├── edge/                    # 设备端/树莓派代码
│   ├── practice_server.py    # 前端实际在用的树莓派原生 orchestrator（LED 引导+录音+评分+历史）
│   ├── ws2812_guide_song.py  # WS2812 灯条引导 + 录音
│   ├── posture_capture.py    # 练习期间的即时手型姿势评分 subprocess
│   ├── microbit_rpi_comm/    # micro:bit BLE 固件 + 树莓派 BLE 接收端
│   └── raspi_runtime/        # 独立的传感器/音频「采集」runtime，用来收集姿势分类器的训练数据
├── experiments/             # 校准跟一次性实验
│   ├── latency_test/          # 麦克风延迟/节奏验证
│   └── benchmarks/            # 树莓派硬件性能测试
├── frontend/
│   └── viewer/                # Vite + React：整个练习流程的前端（见上方核心体验）
├── models/                  # 训练好的手型姿势分类器
├── data/                    # 本地数据集、SQLite、练习录音/结果暂存
├── docs/                    # 曲库 MIDI、架构笔记、录音验证指南
└── scripts/                 # 开发者用的包装脚本（评分、训练、验证）
```

## Useful Commands

一条命令启动完整开发环境（Pi 原生 orchestrator + Vite 前端；Ctrl-C 会一起关闭）：

```bash
python3 scripts/start_pianopal.py
```

没有 BLE 姿势传感器时可用 `--without-motion`；要使用开发机经 SSH 遥控树莓派的备案 orchestrator，改用 `--backend ssh`。只做启动健康检查后自动退出：

```bash
python3 scripts/start_pianopal.py --without-motion --check
```

用真人录音验证评分算法准不准（给不熟这个项目的组员用的一键脚本，见 [docs/VALIDATION_GUIDE.md](docs/VALIDATION_GUIDE.md)）：

```bash
./scripts/validate_recording.sh
```

跑目前的正式评分流程（乐谱 + 录音 -> 评分结果，`reference-dtw` 模式）：

```bash
python3 scripts/grade_audio_reference_constrained.py reference.mid recording.wav \
  --keyboard-profile data/bf3738c_keybank/bf3738c_white_profile.json --white-keys-only \
  -o result.json
```

乐谱转成参考 JSON：

```bash
python -m backend.score_to_reference score.musicxml -o reference.json
```

单纯评分（reference.json + performance.json，不经过音频转谱）：

```bash
python -m backend.scoring reference.json performance.json -o result.json
```

启动树莓派原生 orchestrator（前端实际会连的那个）：

```bash
python3 edge/practice_server.py
```

启动前端（dev 模式，通过 SSH 备案 orchestrator）：

```bash
cd frontend/viewer
npm install
npm run dev
```

各模块更完整的指令/CLI 参数说明，见对应文件夹的 README。

## Notes For Future Work

- Raspberry Pi 跟 micro:bit 采集端代码放 `edge/` 底下。
- 训练好的模型文件放 `models/` 底下。
- 可重用的后端流程放 `backend/` 底下；`experiments/` 是一次性脚本，不要被其他模块 import。
- 本机设备设置（BLE MAC 地址等）放在 `.gitignore` 排除的文件里，例如 `edge/microbit_rpi_comm/raspberry/config.json`。
- 手型评分目前只接了 `edge/practice_server.py`；`scripts/session_server.py`（SSH 备案）还没接，因为 BLE 只存在树莓派端，备案需要多一层「录完 IMU 数据再抓回开发机」的逻辑才能接上。
