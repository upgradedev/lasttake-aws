import base from "./playwright.config.mjs";

// The full legacy suite plus isolated regression controls use offline adapters.
// Force the loopback target even if a caller inherited a live LASTTAKE_URL.
process.env.LASTTAKE_URL = "http://127.0.0.1:8765/";
export default {
  ...base,
  testDir: ".",
  testMatch: ["tests/*.spec.mjs", "source-tests/*.spec.mjs"],
  retries: 0,
  outputDir: "test-results/source",
  reporter: [["list"], ["junit", { outputFile: "test-results/source-junit.xml" }]],
  webServer: {
    command: "python -m lasttake.app.local_server --state-dir .lasttake/legacy-source",
    url: "http://127.0.0.1:8765/healthz",
    reuseExistingServer: false,
    timeout: 60000,
  },
};
