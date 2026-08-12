import { defineConfig, devices } from '@playwright/test';

/** UI tests run against an already-running app: `BASE_URL=... npx playwright test`.
 *
 * They deliberately do not start a server — the app needs PostgreSQL and seeded content, so
 * the caller points them at a local instance or the deployment.
 */
export default defineConfig({
  testDir: './tests',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8899',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
