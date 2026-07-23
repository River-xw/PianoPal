# PianoPal Posture Scoring Result

- Source: `imu_predictions3.jsonl`
- Hand: L
- Time range: 0.103s - 69.675s
- Posture score: **10.53/100**
- Normal ratio: 11.04%
- Confidence-weighted normal ratio: 10.53%
- Report confidence threshold: >= 0.7 (standard)
- Standard threshold prediction count: 19 at >= 0.7

## Summary

- total_predictions: 308
- normal: 34
- posture_error_predictions: 274
- high_confidence_predictions: 19
- high_confidence_errors: 19
- posture_error_events: 1

## Label Distribution

- finger_collapse: 25
- high_lift_tap: 141
- normal: 34
- wrist_arch: 28
- wrist_collapse: 23
- wrist_shake: 57

## High-Confidence Errors

| Error Label | Windows | Start | End | Duration | Mean Confidence | Max Confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| finger_collapse | 19 | 30.203s | 36.035s | 5.832s | 0.8023 | 0.9306 |

## Interpretation

The most prominent posture issue is `finger_collapse`. The posture score is based on the share of confidence assigned to `normal`.
