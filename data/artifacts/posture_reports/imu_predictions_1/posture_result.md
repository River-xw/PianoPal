# PianoPal 姿势评分结果

- 数据源: `imu_predictions(1).jsonl`
- 使用手: 左手 L
- 时间范围: 0.114s - 36.078s
- 姿势评分: **13.19/100**
- Normal 占比: 14.47%
- 置信度加权 Normal 占比: 13.19%
- 本报告高置信阈值: >= 0.45
- 常规高置信阈值 >= 0.7 的预测数: 0

## 汇总

- total_predictions: 152
- normal: 22
- posture_error_predictions: 130
- high_confidence_predictions: 23
- high_confidence_errors: 23
- posture_error_events: 3

## 类别分布

- finger_collapse: 8
- high_lift_tap: 120
- normal: 22
- wrist_shake: 2

## 高置信错误

| 错误类别 | 出现次数/片段 | 开始 | 结束 | 持续 | 平均置信度 | 最高置信度 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| high_lift_tap | 13 | 2.254s | 6.962s | 4.708s | 0.5029 | 0.5256 |
| high_lift_tap | 8 | 19.222s | 22.634s | 3.412s | 0.4913 | 0.5153 |
| high_lift_tap | 2 | 30.83s | 32.874s | 2.044s | 0.4747 | 0.4814 |

## 解释

这次模型置信度整体偏低，最高只有 0.5256；因此结果可以作为姿势趋势参考，但不应当当作最终严格判定。高置信部分主要集中在 high_lift_tap，说明这次测试中模型最明确看到的是“抬指/敲击过高”相关姿势。
