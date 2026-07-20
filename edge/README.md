# Edge

Device-side code for sensor acquisition and Raspberry Pi integration.

- `microbit_rpi_comm/`: micro:bit BLE sender code and Raspberry Pi BLE receiver code.
- `raspi_runtime/`: Raspberry Pi acquisition runtime that connects BLE hand sensors, microphone recording, speaker feedback, local SQLite artifact registration, and real-time IMU posture inference.

## Raspberry Pi / Computer Split

The Raspberry Pi owns real-time work:

```text
micro:bit BLE IMU packets
  -> local raw JSONL
  -> local sliding-window posture inference
  -> local prediction JSONL
  -> speaker feedback
  -> SQLite session/artifact/model-run records

microphone
  -> local audio.wav
```

The computer owns heavier after-session analysis:

```text
audio.wav from Raspberry Pi
  -> backend.audio_to_performance
  -> backend.scoring
  -> result.json / augmented_result.json
  -> frontend viewer / LLM feedback
```

Run a local smoke test without hardware:

```bash
python -m edge.raspi_runtime --mode simulate --duration-sec 3 \
  --user-id u_local_001 --piece-id piece_demo --piece-title Demo
```

Run on Raspberry Pi with BLE, microphone, and speaker command adapters:

```bash
python -m edge.raspi_runtime \
  --mode ble \
  --ble-config edge/microbit_rpi_comm/raspberry/config.json \
  --audio-command "arecord -f cd -t wav {output}" \
  --speaker-command "espeak {message}" \
  --user-id u_local_001 \
  --piece-id piece_fur_elise \
  --piece-title "Fur Elise"
```
