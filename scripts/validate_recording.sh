#!/bin/bash
# 給組員用的一鍵驗證腳本：選歌、給錄音檔，其餘（跑評分、開前端、開瀏覽器）全自動。
# 用法：在終端機打開這個 repo 資料夾，執行：
#   ./scripts/validate_recording.sh
# 然後照畫面提示做就好，不需要輸入其他指令。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/backend/audio_to_performance/.venv/bin/python3"
PROFILE="$REPO_ROOT/data/bf3738c_keybank/bf3738c_white_profile.json"
PUBLIC_DIR="$REPO_ROOT/frontend/viewer/public"
DEV_PORT=5173

echo "=== PianoPal 錄音驗證 ==="
echo ""
echo "請選擇你彈的是哪一首歌："
echo "  1) 小星星 (twinkle_twinkle)"
echo "  2) 十個小印第安人 (10_little_indians)"
echo "  3) Alabama"
echo "  4) 帕赫貝爾卡農 (pachelbel_canon)"
echo "  5) 平安夜簡易版 (silent_night_easy)"
read -rp "輸入數字 (1-5): " CHOICE

case "$CHOICE" in
  1) MIDI="docs/piano_music/twinkle_twinkle.mid" ;;
  2) MIDI="docs/piano_music/10_little_indians.mid" ;;
  3) MIDI="docs/piano_music/alabama.mid" ;;
  4) MIDI="docs/piano_music/pachelbel_canon_bpno.mid" ;;
  5) MIDI="docs/piano_music/silent_night_easy.mid" ;;
  *) echo "沒有這個選項，重新執行一次腳本。"; exit 1 ;;
esac

echo ""
echo "請把錄音檔拖進這個視窗（或直接輸入路徑），然後按 Enter："
read -rp "錄音檔: " RAW_PATH

# 拖曳進終端機常常會自動加引號、跳脫空白，這裡處理掉
AUDIO_PATH="${RAW_PATH%\"}"
AUDIO_PATH="${AUDIO_PATH#\"}"
AUDIO_PATH="${AUDIO_PATH//\\ / }"

if [ ! -f "$AUDIO_PATH" ]; then
  echo "找不到這個檔案：$AUDIO_PATH"
  exit 1
fi

echo ""
echo "評分中，請稍候..."
RESULT_JSON="$(mktemp).json"
DEBUG_JSON="$(mktemp).json"

"$PYTHON" scripts/grade_audio_reference_constrained.py \
  "$MIDI" \
  "$AUDIO_PATH" \
  --keyboard-profile "$PROFILE" \
  --white-keys-only \
  --mode reference-dtw \
  -o "$RESULT_JSON" \
  --debug-output "$DEBUG_JSON" 2>&1 | grep -v "Warning\|warn" || true

cp "$RESULT_JSON" "$PUBLIC_DIR/result.json"
cp "$DEBUG_JSON" "$PUBLIC_DIR/last_debug.json"

SCORE=$("$PYTHON" -c "import json; print(json.load(open('$RESULT_JSON'))['summary']['score'])")
echo ""
echo "評分完成，總分：$SCORE 分"
echo ""

# 啟動前端 dev server（如果還沒在跑的話），然後自動開瀏覽器
cd "$REPO_ROOT/frontend/viewer"
if ! curl -s -o /dev/null "http://localhost:$DEV_PORT/"; then
  echo "啟動前端頁面..."
  nohup npm run dev -- --port "$DEV_PORT" > /tmp/pianopal_viewer.log 2>&1 &
  for _ in $(seq 1 20); do
    if curl -s -o /dev/null "http://localhost:$DEV_PORT/"; then break; fi
    sleep 0.5
  done
fi

open "http://localhost:$DEV_PORT/" 2>/dev/null || xdg-open "http://localhost:$DEV_PORT/" 2>/dev/null || true

echo "瀏覽器應該已經自動打開，看不到的話手動開這個網址：http://localhost:$DEV_PORT/"
echo "(逐音符詳細判定存在 $PUBLIC_DIR/last_debug.json，一般不用看)"
