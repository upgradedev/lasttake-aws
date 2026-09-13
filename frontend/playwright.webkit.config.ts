import {defineConfig,devices} from '@playwright/test';

// QA-WEBKIT: the bounded WebKit matrix. Every mobile journey elsewhere in this
// repository runs Chromium with an emulated iPhone viewport, which proves the
// layout and nothing about the engine a judge's iPhone actually uses. This
// configuration runs the critical journeys on real WebKit: start, the pickup
// approval that must survive a reload, the full evidence-to-turnover walk,
// blocked browser storage, and a transport outage with recovery.
//
// It is deliberately narrow. The Chromium suites and their receipts are
// untouched; this adds an engine, it does not replace one. Cases that need a
// clipboard permission grant are excluded because WebKit refuses
// `grantPermissions(['clipboard-read'])`, and that refusal would read as a
// product failure when it is a test-harness limitation.
//
// Its JUnit is written to its own file so the public acceptance receipt, which
// reads test-results/e2e.xml, keeps counting exactly the Chromium product cases.
export default defineConfig({testDir:'./tests/e2e',fullyParallel:false,workers:1,retries:0,maxFailures:1,timeout:90000,
  captureGitInfo:{commit:true,diff:false},
  grep:/LT01 intake|LT03 saved Strands|navigation keeps session|LT-OFFLINE/,
  outputDir:'test-results/webkit',
  expect:{timeout:20000}, reporter:[['list'],['junit',{outputFile:'test-results/webkit-junit.xml'}],['json',{outputFile:'test-results/webkit-results.json'}]],
  use:{baseURL:process.env.LASTTAKE_UI_URL ?? 'http://127.0.0.1:4173',trace:'on',screenshot:'on',video:'retain-on-failure'},
  projects:[{name:'webkit-mobile',use:{...devices['iPhone 13']}}],
  webServer:process.env.LASTTAKE_UI_URL ? undefined : [
    {command:'python -m lasttake.app.local_server --state-dir .lasttake-ui-webkit',url:'http://127.0.0.1:8765/healthz',reuseExistingServer:false,timeout:60000},
    {command:'npm run preview',url:'http://127.0.0.1:4173',reuseExistingServer:false,timeout:60000}
  ]
});
