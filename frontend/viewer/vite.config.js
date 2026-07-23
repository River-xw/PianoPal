import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The app calls its backend with same-origin relative paths (/api/*,
// /result.json, /last_debug.json) so the production build works unmodified
// when served BY the Pi's edge/practice_server.py. In dev (方式 B: `npm run
// dev` on a separate machine from a session_server), those relative paths
// would otherwise hit Vite's own port -- so proxy them to the orchestrator.
// Override the target with SESSION_SERVER=host:port when it isn't localhost:8900.
const sessionServer = process.env.SESSION_SERVER || 'localhost:8900'
const proxyTarget = `http://${sessionServer}`

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
      '/result.json': { target: proxyTarget, changeOrigin: true },
      '/last_debug.json': { target: proxyTarget, changeOrigin: true },
    },
  },
})
