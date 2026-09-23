import { defineConfig, devices } from '@playwright/test'

// Runs against the full local stack: `docker compose up -d --build` (see e2e/README in the runbook).
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  retries: 0,
  failOnFlakyTests: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
})
