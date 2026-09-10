import {defineConfig, devices} from '@playwright/test';

// Source-only receipt fault injection. Never included in live product JUnit totals.
export default defineConfig({
  testDir: './proof-tests', workers: 1, retries: 0, maxFailures: 1, timeout: 30000,
  captureGitInfo: {commit: true, diff: false},
  outputDir: 'test-results/proof',
  reporter: [['list'], ['html', {outputFolder: 'proof-report', open: 'never'}],
    ['junit', {outputFile: 'test-results/proof-junit.xml'}]],
  use: {baseURL: 'http://127.0.0.1:4173', trace: 'on', screenshot: 'on'},
  projects: [
    {name: 'desktop', use: {...devices['Desktop Chrome'], viewport: {width: 1440, height: 1000}}},
    {name: 'mobile', use: {...devices['iPhone 13'], defaultBrowserType: 'chromium'}},
  ],
  webServer: {command: 'npm run preview', url: 'http://127.0.0.1:4173', reuseExistingServer: false},
});
