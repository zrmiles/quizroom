/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Именно 127.0.0.1, а не localhost: Node может сначала пойти по IPv6 (::1)
// и попасть в другой процесс на том же порту — uvicorn слушает только IPv4.
const api = process.env.API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Для проверки с телефона можно явно запустить npm run dev -- --host.
    host: '127.0.0.1',
    cors: false,
    proxy: {
      '/api': api,
      '/ws': { target: api.replace(/^http/, 'ws'), ws: true },
    },
  },
  test: {
    environment: 'node',
  },
})
