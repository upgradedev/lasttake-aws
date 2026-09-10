import {defineConfig, devices} from '@playwright/test';

// Read-only public proof verification after publication, in a credential-free job.
export default defineConfig({
  testDir: './acceptance-tests', workers: 1, retries: 0, maxFailures: 1, timeout: 30000,
  captureGitInfo: {commit: true, diff: false},
  outputDir: 'test-results/acceptance-page',
  reporter: [['list'], ['html', {outputFolder: 'acceptance-report', open: 'never'}],
    ['junit', {outputFile: 'test-results/acceptance-page/junit.xml'}]],
  use: {baseURL: process.env.LASTTAKE_UI_URL, trace: 'on', screenshot: 'on'},
  projects: [
    {name: 'desktop', use: {...devices['Desktop Chrome'], viewport: {width: 1440, height: 1000}}},
    {name: 'mobile', use: {...devices['iPhone 13'], defaultBrowserType: 'chromium'}},
  ],
});
