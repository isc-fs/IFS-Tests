/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': api, '/auth': api, '/media': api, '/healthz': api },
  },
  build: { assetsDir: 'assets', sourcemap: false },
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'jsdom',
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/api/**', 'src/main.tsx', 'src/test/**', '**/*.test.*'],
      thresholds: { lines: 80, branches: 70, functions: 75 },
    },
    setupFiles: ['./src/test-setup.ts'],
    css: false,
  },
})
