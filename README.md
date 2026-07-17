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
