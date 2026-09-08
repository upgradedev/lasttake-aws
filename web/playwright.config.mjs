// One browser, one worker, against the deployed site. There is nothing to
// parallelise: the tests share a live backend and the last one walks a whole
// shoot day through it.
export default {
  testDir: "./tests",
  timeout: 240_000,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
};
