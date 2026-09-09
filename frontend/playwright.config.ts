import {defineConfig,devices} from '@playwright/test';
export default defineConfig({testDir:'./tests/e2e',fullyParallel:false,workers:1,retries:0,timeout:90000,
  expect:{timeout:20000}, reporter:[['list'],['html',{open:'never'}],['junit',{outputFile:'test-results/e2e.xml'}]],
  use:{baseURL:process.env.LASTTAKE_UI_URL ?? 'http://127.0.0.1:4173',trace:'on',screenshot:'on',video:'retain-on-failure'},
  projects:[{name:'desktop',use:{...devices['Desktop Chrome'],viewport:{width:1440,height:1000}}},{name:'mobile',use:{...devices['iPhone 13'],defaultBrowserType:'chromium'}}],
  webServer:process.env.LASTTAKE_UI_URL ? undefined : [
    {command:'python -m lasttake.app.local_server --state-dir .lasttake-ui',url:'http://127.0.0.1:8765/healthz',reuseExistingServer:false,timeout:60000},
    {command:'npm run preview',url:'http://127.0.0.1:4173',reuseExistingServer:false,timeout:60000}
  ]
});
