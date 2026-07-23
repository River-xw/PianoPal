# PianoPal Posture Scoring Result

- Source: `imu_predictions(1).jsonl`
- Hand: L
- Time range: 0.114s - 36.078s
- Posture score: **13.19/100**
- Normal ratio: 14.47%
- Confidence-weighted normal ratio: 13.19%
- Report confidence threshold: >= 0.4768 (adaptive_85th_percentile_error_confidence)
- Standard threshold prediction count: 0 at >= 0.7

## Summary

- total_predictions: 152
- normal: 22
- posture_error_predictions: 130
- high_confidence_predictions: 21
- high_confidence_errors: 21
- posture_error_events: 3

## Label Distribution

- finger_collapse: 8
- high_lift_tap: 120
- normal: 22
- wrist_shake: 2

## High-Confidence Errors

| Error Label | Windows | Start | End | Duration | Mean Confidence | Max Confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| high_lift_tap | 12 | 2.478s | 6.962s | 4.484s | 0.5073 | 0.5256 |
| high_lift_tap | 8 | 19.222s | 22.634s | 3.412s | 0.4913 | 0.5153 |
| high_lift_tap | 1 | 31.054s | 32.874s | 1.82s | 0.4814 | 0.4814 |

## Interpretation

The most prominent posture issue is `high_lift_tap`. The posture score is based on the share of confidence assigned to `normal`. The model was not very confident overall, so this report used an adaptive threshold and should be read as a trend diagnosis rather than a strict final judgment.
