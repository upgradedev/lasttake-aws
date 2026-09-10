import {defineConfig,devices} from '@playwright/test';
export default defineConfig({testDir:'./benchmark-tests',fullyParallel:false,workers:1,retries:0,repeatEach:10,
  maxFailures:0,timeout:90000,globalTimeout:1140000,expect:{timeout:20000},
  outputDir:'test-results/hero-benchmark-playwright',reporter:[['list'],['json',{outputFile:'test-results/hero-benchmark/playwright.json'}]],
  use:{baseURL:'http://127.0.0.1:4173',trace:'off',screenshot:'off',video:'off',serviceWorkers:'block'},
  projects:[{name:'desktop',use:{...devices['Desktop Chrome'],viewport:{width:1440,height:1000}}},
    {name:'mobile',use:{...devices['iPhone 13'],defaultBrowserType:'chromium',viewport:{width:375,height:812}}}],
  webServer:[{command:'python ../tools/hero_benchmark_server.py',url:'http://127.0.0.1:8765/healthz',reuseExistingServer:false,timeout:60000},
    {command:'npm run preview',url:'http://127.0.0.1:4173',reuseExistingServer:false,timeout:60000}]
});
