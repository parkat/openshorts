import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Shared proxy: forward API/media/render calls to the sibling containers so the
// whole app lives on one origin (openshorts.parkat.us) behind Cloudflare Access.
const proxy = {
  '/api':        { target: 'http://backend:8000', changeOrigin: true },
  '/videos':     { target: 'http://backend:8000', changeOrigin: true },
  '/thumbnails': { target: 'http://backend:8000', changeOrigin: true },
  '/gallery':    { target: 'http://backend:8000', changeOrigin: true },
  '/video':      { target: 'http://backend:8000', changeOrigin: true },
  '/render':     { target: 'http://renderer:3100', changeOrigin: true },
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Dev server (LAN only: `npm run dev`).
  server: {
    watch: { usePolling: true, interval: 300 },
    allowedHosts: ['openshorts.app', 'www.openshorts.app', 'openshorts.parkat.us'],
    proxy,
  },
  // PRODUCTION serving (`vite preview`) — this is how the GPU-box container runs.
  // The dev server ships @vite/client, whose HMR websocket can't pass Cloudflare
  // Access, so the client reload-loops every ~minute and wipes in-progress edits.
  // The built bundle has no such client. Vite 4 preview does not host-check, so
  // no allowedHosts is needed here.
  preview: {
    proxy,
  },
})
