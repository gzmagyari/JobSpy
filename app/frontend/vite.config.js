import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// In dev, proxy /api to the FastAPI backend so the frontend can use relative
// URLs (same as production, where FastAPI serves the built app).
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8077',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
