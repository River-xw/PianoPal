# viewer

給 [backend.scoring](../../backend/scoring) 模組輸出的 `result.json` 用的網頁檢視器。純前端、不需要後端——把檔案讀進瀏覽器記憶體就直接畫圖，沒有任何資料離開你的電腦。

## 執行

```bash
cd frontend/viewer
npm install
npm run dev
```

打開 `http://localhost:5173`。如果 `frontend/viewer/public/result.json` 已經存在（例如用 [`../../scripts/grade.py`](../../scripts/grade.py) 跑過），會自動載入顯示；不然點右上角「Load result.json」手動選一份 `python -m backend.scoring ... -o result.json` 產生的檔案。

## 畫面看到什麼

**上方摘要卡片**：總分、三個子分數（音高準確率／節奏準確率／節奏穩定度）、全域速度比例（`global_tempo_ratio`）、越彈越快/越彈越慢的趨勢，以及各分類（正確/時間偏差/彈錯音/漏彈/多彈）各幾個。

**Notation（五線譜）**：對彈奏者來說比 MIDI 風格的方格圖直觀很多——用真正的高音/低音譜表（右手→高音譜號、左手→低音譜號）畫出每個音符，依小節分行、依評分結果著色（顏色規則跟下面 Piano roll 一致）。音符時值是從 `dur_beats` 量化成最接近的標準音符（四分、八分…），所以節奏複雜的段落畫出來會略為簡化，不是逐拍精確的原始記譜。

**評語**：白話文列出「哪幾小節有什麼問題」，依影響音符數量由多到少排序，例如：

> 第 56-60 小節：明顯搶拍(彈太早)，平均偏差約 90 毫秒，共 95 個音符受影響。

這段文字完全是前端自己算出來的（`src/utils/feedback.js`），把連續、同類型的錯誤小節合併成一個範圍，不需要呼叫任何 AI/後端。

**Piano roll（鋼琴捲軸）**：x 軸是時間、y 軸是 MIDI 音高，灰色直線是小節分界。每個音符依評分結果著色：

| 顏色 | 狀態 | 畫法 |
| --- | --- | --- |
| 綠 | `correct` | 實心色塊，畫在參考位置 |
| 橘 | `timing_off` | 實心色塊，畫在**實際彈奏**的時間點，並標示 ← / → 箭頭與偏差毫秒數 |
| 紅 | `wrong_pitch` | 實心色塊畫在**實際彈到**的音高，虛線連到上方/下方期望音高的位置，兩者都能看到 |
| 灰（空心虛線框） | `missed` | 畫在參考位置，代表「應該有這個音但沒彈」 |
| 紫（菱形） | `extra` | 畫在實際彈奏的位置，用不同形狀跟其他狀態區分「這是多彈出來的」 |

滑鼠移到任一個音符上會跳出提示框，顯示期望音高/時間、實際音高/時間、偏差毫秒數、小節、左右手。（Notation 面板目前沒有做這個 hover 提示——出錯的細節交給「評語」跟 Piano roll 負責。）

**Timing drift over time（下方小圖）**：每個有時間資料的音符，x 軸是它在曲子裡的順序、y 軸是 `offset_ms`。如果這條線整體往下滑，代表使用者演奏中途開始搶拍（越彈越快）；往上滑則是拖拍。

## 顏色從哪裡來

狀態顏色不是隨便挑的，是套用專案內建的 dataviz 色票規則：`correct`/`timing_off`/`wrong_pitch` 對應色票裡保留給「good/warning/critical」狀態用的固定色（不會跟其他圖表的分類色衝突）；`extra` 沒有對應的第四個狀態色，所以借用了分類色票裡最接近紫色的 violet 色階。淺色/深色模式都有對應的數值，寫在 `src/index.css` 的 CSS variables 裡（跟著系統的深色模式設定自動切換）。Notation 面板用 `getComputedStyle` 在畫圖當下讀出這些變數目前解析出來的顏色，所以也會跟著深色模式切換。

## 檔案結構

| 檔案 | 作用 |
| --- | --- |
| `src/App.jsx` | 最外層：檔案選取、自動載入 `/result.json`、把資料分派給各個面板 |
| `src/components/SummaryPanel.jsx` | 總分/子分數/計數摘要卡片 |
| `src/components/NotationView.jsx` | 用 [VexFlow](https://www.vexflow.com/) 畫的五線譜視圖 |
| `src/components/FeedbackPanel.jsx` | 「評語」文字面板 |
| `src/utils/feedback.js` | 把錯誤音符分組、合併小節範圍、產生中文評語的邏輯 |
| `src/components/PianoRoll.jsx` | 鋼琴捲軸視覺化 |
| `src/components/TimingStrip.jsx` | 節奏漂移小圖 |
| `src/index.css` | Tailwind 進入點 + 顏色/介面用的 CSS variables(含深色模式) |

## 已知限制

- `result.json` 沒有拍號資訊，所以 Notation 面板不畫時間記號，也不驗證每小節的拍數是否補滿——單純把每個音符依量化後的時值排進去
- `extra`（多彈的音）沒有參考小節可以對應，Notation 面板會把它們掛在「時間上最接近的前一個音符」所在的小節，只是視覺上的近似安排
- Notation 面板的音符一律用升記號拼寫（不會自動改用降記號），如果樂曲調性偏好用降記號，畫出來的音高沒錯，但拼字不是最直覺的那種
- 目前只支援本機選檔或 `frontend/viewer/public/result.json` 自動載入，沒有做後端 API 串接
