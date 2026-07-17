# PianoPal

PianoPal 是一个面向钢琴练习反馈的项目，当前仓库已经包含三条核心链路：

1. micro:bit 采集手部传感器数据，并由 Raspberry Pi 通过 BLE 接收。
2. 麦克风录音转成演奏音符序列，用于节奏和音准判断。
3. 将标准谱面、实际演奏和评分结果展示到前端 viewer。

未来的 AI 手势识别、音准判断模型和数据库服务，可以沿用现在的分层继续接入。

## Current Data Flow

```text
micro:bit sensors
  -> Raspberry Pi BLE receiver
  -> future gesture model
  -> backend scoring / result schema
  -> database / API
  -> frontend viewer

microphone audio
  -> backend.audio_to_performance
  -> backend.scoring
  -> frontend viewer
```

## Repository Structure

```text
.
├── backend/                 # Python runtime modules: score parsing, audio transcription, scoring, validation
│   ├── audio_to_performance/ # Mic audio -> performance note list
│   ├── score_to_reference/   # MusicXML/MIDI score -> canonical reference JSON
│   ├── scoring/              # Compare reference vs performance and produce result.json
│   └── validation/           # Round-trip validation for transcription quality
├── edge/                    # Device-side and Raspberry Pi code
│   └── microbit_rpi_comm/    # micro:bit BLE sender + Raspberry Pi BLE receiver
├── experiments/             # Calibration and one-off experiments
│   └── latency_test/         # Microphone latency / rhythm tests
├── frontend/
│   └── viewer/               # Vite + React local scoring-result viewer
├── models/                  # Future trained AI model files and inference adapters
├── data/                    # Local datasets / references / generated samples
├── docs/                    # Architecture notes and demo screenshots
└── scripts/                 # Developer-facing wrapper scripts
```

## Useful Commands

Run the all-in-one local grading wrapper:

```bash
python3 scripts/grade.py reference.musicxml performance.mid --bpm 90
```

Convert a score to reference JSON:

```bash
python -m backend.score_to_reference score.musicxml -o reference.json
```

Convert microphone audio to `performance.json`:

```bash
python -m backend.audio_to_performance recording.wav -o performance.json
```

Score a performance:

```bash
python -m backend.scoring reference.json performance.json -o result.json
```

Run the frontend viewer:

```bash
cd frontend/viewer
npm install
npm run dev
```

## Notes For Future Work

- Put Raspberry Pi and micro:bit acquisition code under `edge/`.
- Put model artifacts, model loading code, and inference adapters under `models/`.
- Keep reusable backend pipelines under `backend/`; avoid importing directly from `experiments/`.
- Keep local device configuration such as BLE MAC addresses in ignored files like `edge/microbit_rpi_comm/raspberry/config.json`.
- When adding a real database/API layer, create it under `backend/` and wire the existing scoring result schema into it.


---

# IMU Data Collection Specification

## Overview

本项目采用 **3 个 IMU（Accelerometer + Gyroscope）** 采集钢琴演奏时的手部运动数据。

数据流如下：

```text
Finger IMU
        │
Hand IMU
        ├──> micro:bit ──Bluetooth UART──> Raspberry Pi
Wrist IMU
```

其中：

* **Finger IMU**：安装于手指第一关节
* **Hand IMU**：安装于手背
* **Wrist IMU**：安装于手腕

micro:bit 负责采集三个 IMU 的原始数据，并通过 Bluetooth UART 实时发送至 Raspberry Pi。

Raspberry Pi 负责：

* Session 管理
* 数据存储
* 数据过滤
* 数据可视化
* 后续机器学习训练

---

# Sensor Configuration

每个 IMU 采集以下六轴数据：

| Sensor | Description        | Unit |
| ------ | ------------------ | ---- |
| ax     | Acceleration X     | g    |
| ay     | Acceleration Y     | g    |
| az     | Acceleration Z     | g    |
| gx     | Angular Velocity X | °/s  |
| gy     | Angular Velocity Y | °/s  |
| gz     | Angular Velocity Z | °/s  |

每个 IMU 共 **6 个特征**。

三个 IMU 共：

```
3 × 6 = 18 Features
```

---

# Sensor Placement

```
      Finger IMU
           │
      ───────────
      │ Finger │
      ───────────

         Hand IMU
      ┌───────────┐
      │ Hand Back │
      └───────────┘

         Wrist IMU
      ─────────────
          Wrist
```

各 IMU 的主要检测目标如下：

| IMU        | Main Purpose                                   |
| ---------- | ---------------------------------------------- |
| Finger IMU | Finger posture, finger collapse, raised finger |
| Hand IMU   | Palm posture, palm rotation                    |
| Wrist IMU  | Wrist posture, wrist movement                  |

---

# Dataset Structure

建议每次采集作为一个独立 Session。

```
dataset/

    session_0001/
        imu.csv
        metadata.json

    session_0002/
        imu.csv
        metadata.json

    ...
```

---

# CSV Format

建议每一行表示 **同一时间点三个 IMU 的同步数据**。

```csv
timestamp,
finger_ax,finger_ay,finger_az,
finger_gx,finger_gy,finger_gz,
hand_ax,hand_ay,hand_az,
hand_gx,hand_gy,hand_gz,
wrist_ax,wrist_ay,wrist_az,
wrist_gx,wrist_gy,wrist_gz,
label
```

Example:

```csv
0,
-0.02,0.13,0.98,
1.20,-0.80,0.40,
0.05,0.18,0.97,
0.60,-1.50,0.20,
0.01,0.10,0.99,
0.30,-0.50,0.10,
0
```

---

# Metadata Format

每个 Session 保存对应元数据。

```json
{
    "session_id": "session_0001",
    "piece": "demo_song",
    "hand": "left",
    "sample_rate": 100,
    "sensor_type": "3x IMU",
    "start_time": "2026-07-17T14:30:00",
    "collector": "user01"
}
```

---

# Label Definition

钢琴演奏姿态标签如下：

| Label ID | Category | Label            |
| -------- | -------- | ---------------- |
| 0        | Normal   | Standard Posture |
| 1        | Wrist    | Wrist Drop       |
| 2        | Wrist    | High Wrist       |
| 3        | Wrist    | Wrist Swing      |
| 4        | Palm     | Palm Collapse    |
| 5        | Palm     | Palm Rotation    |
| 6        | Finger   | Finger Collapse  |
| 7        | Finger   | Raised Finger    |
| 8        | Finger   | Finger Stiffness |
| 9        | Arm      | Arm Lift         |

---

# IMU Responsibility

不同 IMU 对应不同的检测任务：

| IMU        | Main Labels                                      |
| ---------- | ------------------------------------------------ |
| Finger IMU | Finger Collapse, Raised Finger, Finger Stiffness |
| Hand IMU   | Palm Collapse, Palm Rotation                     |
| Wrist IMU  | Wrist Drop, High Wrist, Wrist Swing, Arm Lift    |

三个 IMU 的数据将在 Raspberry Pi 上同步，并作为机器学习模型的输入特征。

---

# Bluetooth UART Packet Format

micro:bit 通过 Bluetooth UART 向 Raspberry Pi 实时发送数据。

建议数据格式如下：

```text
DATA,
timestamp,
finger_ax,finger_ay,finger_az,finger_gx,finger_gy,finger_gz,
hand_ax,hand_ay,hand_az,hand_gx,hand_gy,hand_gz,
wrist_ax,wrist_ay,wrist_az,wrist_gx,wrist_gy,wrist_gz
```

Example:

```text
DATA,
125,
-0.02,0.13,0.98,1.2,-0.8,0.4,
0.05,0.18,0.97,0.6,-1.5,0.2,
0.01,0.10,0.99,0.3,-0.5,0.1
```

Raspberry Pi 负责：

1. 解析 Bluetooth 数据包
2. 添加 Session 信息
3. 添加 Label
4. 保存 CSV
5. 数据过滤
6. 绘制曲线
7. 提供机器学习训练数据

---

# Data Collection Workflow

```
Start Session
        │
        ▼
Select Label
        │
        ▼
micro:bit collects IMU data
        │
        ▼
Bluetooth UART
        │
        ▼
Raspberry Pi
        │
        ├── Save imu.csv
        ├── Save metadata.json
        ├── Filter abnormal packets
        └── Generate visualization
```

