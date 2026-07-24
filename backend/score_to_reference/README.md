# score_to_reference

把一份乐谱（MIDI / MusicXML）转换成一份**单一、标准化的 JSON 参考答案**，给 AIoT 钢琴陪练系统的三个下游模块共用：

1. WS2812B LED 指法灯光提示
2. 网页前端的音符掉落节奏游戏
3. 节奏 / 音高评分（DTW）

核心设计理念：**拍数（beats）才是唯一真相，秒数只是衍生值**。因为用户会用节拍器在不同 BPM 下练习，所以每个音符只需要存「第几拍」，真正播放用的秒数可以随时针对任何目标速度重新算出来。

---

## 1. 安装

```bash
cd score_to_reference
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

需要 Python 3.11。相依套件：

- [`music21`](https://www.music21.org/)：解析 MusicXML，能读出五线谱的谱号、调性、拍号等信息
- [`pretty_midi`](https://craffel.github.io/pretty-midi/)：解析 MIDI
- [`mido`](https://mido.readthedocs.io/)：`pretty_midi` 的底层依赖

---

## 2. 支持的输入格式

| 扩展名 | 说明 |
|---|---|
| `.mid`, `.midi` | 标准 MIDI 档 |
| `.musicxml`, `.xml`, `.mxl` | MusicXML（含压缩格式 `.mxl`） |
| `.pdf` | **不支持**。会丢出 `OpticalMusicRecognitionNotSupportedError`，提示你先在 MuseScore 里把 PDF 导入、辨识后，导出成 `.musicxml` 或 `.mid` 再转 |
| 其他任何扩展名 | 丢出 `UnsupportedFormatError` |

---

## 3. 当作 Python 套件使用

### 3.1 `convert(path) -> dict`

后端调用的主函数，读一个文件路径，回传一份可以直接 `json.dumps()` 的 dict。

```python
from backend.score_to_reference import convert

reference = convert("我的乐谱.musicxml")
print(reference["title"], reference["tempo_bpm"], len(reference["notes"]))
```

### 3.2 `to_seconds(reference, bpm) -> dict`

用户要用其他速度（例如节拍器设 90 BPM）练习时，用这个函数重新算出所有音符的秒数，**不会改到原本传进去的 reference**（回传的是深拷贝）。

```python
from backend.score_to_reference import convert, to_seconds

reference = convert("我的乐谱.musicxml")     # 乐谱原始速度，例如 120 bpm
slow_practice = to_seconds(reference, bpm=60)  # 慢一半速度练习
# slow_practice 里每个音符的 onset_sec / dur_sec 都变成原本的两倍
```

原理很单纯：`秒 = 拍数 × 60 / bpm`，所以速度加倍、秒数就直接减半，跟乐谱原本有没有变速无关。

### 3.3 `save_to_db(reference)`

目前是**尚未实作的 stub**，调用会直接丢 `NotImplementedError`。要接上真正的后端数据库时，打开 [`db.py`](db.py)，把里面标示 `TODO(backend)` 的地方换成实际的 SQLAlchemy model / session import，再照着文件内附的范例代码实作 insert 逻辑。

### 3.4 例外处理

```python
from backend.score_to_reference import (
    convert,
    UnsupportedFormatError,
    OpticalMusicRecognitionNotSupportedError,
    ScoreParsingError,
)

try:
    reference = convert(path)
except OpticalMusicRecognitionNotSupportedError:
    print("请先用 MuseScore 导出 .musicxml 或 .mid")
except UnsupportedFormatError:
    print("扩展名不支持")
except ScoreParsingError as e:
    print(f"文件格式对，但内容解析失败：{e}")
```

---

## 4. 命令行（CLI）使用

```bash
# 转换并印到终端机
python -m backend.score_to_reference 我的乐谱.musicxml

# 转换并存成文件
python -m backend.score_to_reference 我的乐谱.musicxml -o ref.json

# 转换同时换算成指定练习速度（例如 90 bpm）
python -m backend.score_to_reference 我的乐谱.mid -o ref.json --bpm 90
```

失败时会印 `Error: ...` 到 stderr，并回传 exit code 1（可用于 shell script 判断成功与否）。

---

## 5. 输出 JSON 结构

```jsonc
{
  "title": "Maple Leaf Rag",
  "tempo_bpm": 100,
  "tempo_map": [{"beat": 0.0, "bpm": 100.0}],   // 若乐谱中途变速，这里会有多笔
  "time_signature": "2/4",
  "key": "A- major",
  "duration_beats": 168.5,                        // 全曲总拍数（衍生秒数用的来源）
  "duration_sec": 101.1,                           // = duration_beats 换算出来的秒数
  "notes": [
    {
      "pitch": 60,            // MIDI 音高编号 (0-127)
      "name": "C4",           // 音名 + 八度
      "onset_beats": 0.0,     // 从第几拍开始（与速度无关，这是「唯一真相」）
      "onset_sec": 0.0,       // 依 tempo_bpm 算出来的秒数（衍生值）
      "dur_beats": 1.0,       // 音符长度，以拍为单位
      "dur_sec": 0.5,         // 音符长度，以秒为单位（衍生值）
      "velocity": 80,         // 力度 0-127
      "hand": "R",            // "R" = 右手/高音谱号，"L" = 左手/低音谱号
      "measure": 1            // 第几小节
    }
  ]
}
```

`notes` 保证依 `(onset_beats, pitch)` 排序，所以同一份乐谱每次转换出来的音符顺序都一样（deterministic），方便 DTW 比对或做差异测试。

### 左右手（hand）怎么判断？

- **MusicXML**：优先看该声部的谱号（Clef）——高音谱号 → `R`，低音谱号 → `L`；如果完全没有谱号信息，就用声部顺序（第一声部 `R`，其余 `L`）当备援
- **MIDI**：MIDI 本身没有谱号概念，只能用「第几轨」猜——第 0 轨 `R`，其余 `L`。如果来源 MIDI 的轨道顺序跟左右手对不上，这个字段可能不准，需要人工确认

---

## 6. 运行测试

```bash
cd score_to_reference
source .venv/bin/activate
python -m pytest tests -v
```

测试会用 `music21` **现场产生**一份极简双手小乐谱（不需要任何外部文件），验证：

- 音高 / 起始拍点抽取是否正确
- 拍数 → 秒数的换算（在原始乐谱速度下）
- 换速（`to_seconds`）：BPM 加倍时 `onset_sec` 是否正确减半
- 左右手标记（通过谱号）
- 音符排序是否具决定性（deterministic）
- PDF 输入 / 不支持扩展名的错误是否正确抛出

---

## 7. 文件结构速查

| 文件 | 作用 |
|---|---|
| `__init__.py` | 套件对外接口：导出 `convert` / `to_seconds` / `save_to_db` 与各种错误类别 |
| `errors.py` | 类型化错误定义 |
| `musicxml_parser.py` | 用 music21 解析 MusicXML，抽出音符、谱号、调性、拍号、速度 |
| `midi_parser.py` | 用 pretty_midi 解析 MIDI，抽出音符与速度变化 |
| `core.py` | `convert()` 与 `to_seconds()` 主逻辑：集成两种 parser 的输出、排序、拍数↔秒数换算 |
| `db.py` | `save_to_db()` stub，等待接上真正后端 DB |
| `__main__.py` | CLI 入口（`python -m backend.score_to_reference ...`） |
| `requirements.txt` | 相依套件清单 |
| `tests/` | pytest 测试，现场产生测试乐谱 |

---

## 8. 已知限制

- PDF 乐谱完全不支持光学辨识（OMR），需要先用 MuseScore 转出 `.musicxml`/`.mid`
- MIDI 档的左右手标记是用轨道顺序猜的，不保证准确
- `save_to_db()` 尚未接上真正的数据库，目前调用必定丢例外
