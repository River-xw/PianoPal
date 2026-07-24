# benchmarks

一次性、跑在目标硬件上的性能测试，不是可重复导入的函数库——结果记在这里跟对话纪录里，不是断言在测试套件里。

## `basic_pitch_pi_bench.py`：决定 basic-pitch 转谱能不能搬到树莓派上跑

目前 `audio_to_performance/` 假设转谱跑在笔电/云端，不是树莓派本身。但这是一个 AIoT 项目，展示时还要依赖笔电，跟「IoT设备自己做事」的故事有点矛盾。在真的把架构改成「树莓派自己转谱」之前，先测一下树莓派的推论速度够不够快。

刻意只用**轻量**推论后端（ARM 上合理的选择）：优先 `tflite-runtime`，不行就退到 ONNX Runtime，都不行只剩全套 TensorFlow SavedModel 的话会印出明显警告——那正是这个测试想避开的重量级后端。

## 在树莓派 5(Debian 13 trixie, Python 3.13, aarch64)上实测遇到的安装问题

这部分值得记下来，因为坑不小：

1. **basic-pitch 在 Linux 上的 `install_requires` 直接要求 `tensorflow<2.15.1`**（Mac 上这条规则因为 `platform_system != "Darwin"` 的条件被排除，所以 Mac 装 `basic-pitch[onnx]` 完全没事，但 Linux 上这是硬性条件，不管你装不装 tf extras）。而 `tensorflow<2.15.1` 没有支持 Python 3.13 的 aarch64 wheel（TF 是最近的 2.19+ 才加上 3.13 支持，版本已经超过 `<2.15.1` 的上限），导致 `pip install basic-pitch` 直接失败，还会让 pip 的 resolver 往回探索更旧的 basic-pitch 版本，一路挖到 `numpy<1.24`（连 numpy 都得从没有 wheel 的旧 sdist build，在新版 Python 上会因为 `setuptools.build_meta` 相关问题整个炸掉）。

   **解法**：跳过 basic-pitch 自己的依赖解析，只装它实际「推论」路径真正需要的东西：
   ```bash
   pip install --no-deps basic-pitch==0.4.0
   pip install numpy librosa resampy pretty_midi scipy mir_eval
   ```
   这里特意不装 `tensorflow`、`scikit-learn`——检查过 `basic_pitch/inference.py` 跟 `note_creation.py`(predict() 实际会走到的代码)完全没 import 这两个，那些只有 `models.py`/`nn.py`/`train.py`/`visualize.py`(训练/可视化用，不会被 `predict()` 碰到)才需要。basic_pitch 自己的 `__init__.py` 对 tflite/onnx/tf/coreml 都是 try/except 包起来的，缺了不会真的坏掉——**除非一个后端都不装**：那样 `_default_model_type` 完全没被赋值，连 `import basic_pitch` 都会 `NameError`，所以至少要装一个推论后端才能用。

2. **`tflite-runtime` 在这个平台/Python版本组合完全没有可用的发布版本**(`pip install tflite-runtime` 直接回报 "Could not find a version that satisfies the requirement... from versions: none")——这是已知问题，Google 很长一段时间没有再为新版 Python/ARM 组合发布 wheel。代码里的 fallback 逻辑正是为了这个情况设计的：自动退到 `onnxruntime`(有 cp313 aarch64 wheel，正常装)。

3. 网络速度不稳(这台机器连接速度时快时慢，numpy 15MB 一度花了 2.5 分钟)，纯粹是这次测试环境的问题，跟代码无关。

## 实测结果(Raspberry Pi 5 Model B Rev 1.1, 8GB RAM, Debian 13 trixie, Python 3.13.5, ONNX Runtime 后端)

| 音档长度 | 平均推论时间 | RTF(real-time factor) | 峰值内存 | 结论 |
| --- | --- | --- | --- | --- |
| 5s | 0.121s | 0.02 | 266MB | 比即时快超过40倍 |
| 10s | 0.211s | 0.02 | 270MB | 比即时快超过40倍 |
| 20s | 0.400s | 0.02 | 279MB | 比即时快超过40倍 |
| 30s | 0.594s | 0.02 | 289MB | 比即时快超过40倍 |

**结论：完全可行，而且远远超乎预期。** RTF 稳定在 0.02 左右(转谱时间只占音档本身长度的2%)，内存也只用了不到300MB(树莓派5有8GB)——不只是「可以做批量处理」，是连即时/近即时回馈都绰绰有余。这个数字是 Pi 5 + ONNX Runtime 后端测出来的，跟晚一辈的 Pi(3/4，内存更少、CPU更弱)不能直接类推——如果之后要在更旧型号上部署，需要重新跑一次这个 benchmark。

完整原始报告：`pi5_benchmark_report.json`(在对话的 scratchpad 里，未加入这个 git repo，因为是单次测试结果不是代码)。

## 用法

```bash
python -m benchmarks.basic_pitch_pi_bench --durations 5 10 20 30 --runs 3 -o report.json
```

32比特系统会直接印错误退出(TF/ONNX 的 ARM wheel 在32比特上常常装不上或装了会坏，与其在依赖错误里越挖越深，不如直接换64比特映像档)。
