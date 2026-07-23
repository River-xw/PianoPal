# PianoPal Posture Scoring Result

- Source: `imu_predictions2.jsonl`
- Hand: L
- Time range: 0.011s - 69.026s
- Posture score: **35.92/100**
- Normal ratio: 38.26%
- Confidence-weighted normal ratio: 35.92%
- Report confidence threshold: >= 0.45 (adaptive_85th_percentile_error_confidence)
- Standard threshold prediction count: 0 at >= 0.7

## Summary

- total_predictions: 311
- normal: 119
- posture_error_predictions: 192
- high_confidence_predictions: 26
- high_confidence_errors: 26
- posture_error_events: 2

## Label Distribution

- finger_collapse: 48
- high_lift_tap: 73
- normal: 119
- wrist_arch: 71

## High-Confidence Errors

| Error Label | Windows | Start | End | Duration | Mean Confidence | Max Confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| wrist_arch | 13 | 0.011s | 4.374s | 4.363s | 0.4683 | 0.5124 |
| high_lift_tap | 13 | 60.718s | 67.542s | 6.824s | 0.499 | 0.539 |

## Interpretation

The most prominent posture issue is `high_lift_tap`. The posture score is based on the share of confidence assigned to `normal`. The model was not very confident overall, so this report used an adaptive threshold and should be read as a trend diagnosis rather than a strict final judgment.
