# Frontend

Frontend applications for PianoPal.

- `viewer/`: Vite + React app -- the whole practice-facing frontend now (引导页/主页/学习模式/演奏模式/我的), not just a `result.json` viewer anymore, though loading one manually is still supported. See [viewer/README.md](viewer/README.md) for the page architecture, dual-mode scoring, and the practice-session API it talks to (`edge/practice_server.py`/`scripts/session_server.py`).
