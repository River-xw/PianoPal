#!/usr/bin/env python3
"""Drag-and-drop wrapper for the score_to_reference -> scoring -> viewer pipeline.

Usage:
    python3 grade.py <標準樂譜> <待檢測的檔案> [--bpm 90]

不帶參數執行的話會用問的 -- 把檔案從 Finder 拖進終端機視窗，再按 Enter 就好。

<標準樂譜>：.musicxml / .xml / .mxl / .mid -- 當作正確答案
<待檢測的檔案>：
    .mid            -- 一段錄音（例如 MIDI 鍵盤彈奏錄下來的）
    .musicxml/.mxl  -- 另一份樂譜，拿來跟標準樂譜比較
    .json           -- 已經是 performance.json 格式（[{pitch,onset_sec,...}, ...]）

跑完會自動把前端開發伺服器起起來，並且打開瀏覽器顯示這次的評分結果。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
VIEWER_DIR = PROJECT_ROOT / "viewer"
VIEWER_URL = "http://localhost:5173"

sys.path.insert(0, str(PROJECT_ROOT))

from score_to_reference import convert as convert_score  # noqa: E402
from scoring import ScoringConfig, midi_to_performance, score_performance  # noqa: E402


def _clean_path(raw: str) -> Path:
    raw = raw.strip().strip('"').strip("'")
    raw = raw.replace("\\ ", " ")  # 終端機拖曳檔案時，空白會被跳脫成 "\ "
    return Path(raw).expanduser().resolve()


def _prompt_for_path(label: str) -> Path:
    while True:
        raw = input(f"{label}（把檔案拖進這個視窗，然後按 Enter）：")
        path = _clean_path(raw)
        if path.exists():
            return path
        print(f"  找不到檔案：{path}")


def _load_performance(path: Path) -> list:
    ext = path.suffix.lower()
    if ext in {".mid", ".midi"}:
        return midi_to_performance(str(path))
    if ext in {".musicxml", ".xml", ".mxl"}:
        parsed = convert_score(str(path))
        return [
            {"pitch": n["pitch"], "onset_sec": n["onset_sec"],
             "dur_sec": n["dur_sec"], "velocity": n["velocity"]}
            for n in parsed["notes"]
        ]
    if ext == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    raise ValueError(f"不支援的待測檔案格式：{ext}")


def _server_is_up() -> bool:
    try:
        urllib.request.urlopen(VIEWER_URL, timeout=1)
        return True
    except Exception:
        return False


def _ensure_dev_server_running() -> bool:
    if _server_is_up():
        return True
    print("啟動前端開發伺服器（viewer/ 底下的 npm run dev）...")
    subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(VIEWER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(45):
        if _server_is_up():
            return True
        time.sleep(1)
    print("警告：等了 45 秒前端伺服器還沒起來，請自己到 viewer/ 跑 npm run dev 看看是什麼錯誤")
    return False


def main() -> int:
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    bpm = None
    for a in sys.argv[1:]:
        if a.startswith("--bpm="):
            bpm = int(a.split("=", 1)[1])
        elif a == "--bpm" and sys.argv.index(a) + 1 < len(sys.argv):
            bpm = int(sys.argv[sys.argv.index(a) + 1])

    reference_path = _clean_path(positional[0]) if len(positional) >= 1 else _prompt_for_path("標準樂譜(musicxml/mid)")
    performance_path = _clean_path(positional[1]) if len(positional) >= 2 else _prompt_for_path("待檢測的檔案(mid/musicxml/json)")

    print(f"參考樂譜：{reference_path}")
    print(f"待檢測檔：{performance_path}")

    reference = convert_score(str(reference_path))
    performance = _load_performance(performance_path)

    result = score_performance(reference, performance, ScoringConfig(), target_bpm=bpm)

    output_path = VIEWER_DIR / "public" / "result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n總分：{result.summary.score}")
    print(f"子分數：{result.summary.sub_scores}")
    print(f"計數：{result.summary.counts}")

    if _ensure_dev_server_running():
        webbrowser.open(VIEWER_URL)
        print(f"\n已經在瀏覽器開啟 {VIEWER_URL}，應該會自動顯示這次的評分結果。")
    else:
        print(f"\n伺服器還沒就緒，手動打開 {VIEWER_URL} 看看。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
