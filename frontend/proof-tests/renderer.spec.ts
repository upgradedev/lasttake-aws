import {test, expect} from '@playwright/test';
import fixture from './receipt.fixture.json' with {type: 'json'};

const cases = [
  ['valid', 'CURRENT_AUTOMATED_PASS'], ['missing', 'PENDING'], ['malformed', 'UNKNOWN'],
  ['stale', 'HISTORICAL'], ['frontend mismatch', 'HISTORICAL'], ['backend mismatch', 'HISTORICAL'],
  ['immutable mismatch', 'UNKNOWN'], ['immutable missing', 'UNKNOWN'], ['refusal', 'UNKNOWN'],
  ['failed cases', 'UNKNOWN'], ['skipped cases', 'UNKNOWN'], ['future', 'UNKNOWN'],
  ['unsafe link', 'UNKNOWN'], ['unavailable health', 'UNKNOWN'], ['server error', 'UNKNOWN'],
  ['HTML mismatch', 'UNKNOWN'], ['HTML missing marker', 'UNKNOWN'],
];

for (const [scenario, status] of cases) {
  test(`public proof fixture: ${scenario}`, async ({page}) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const record = structuredClone(fixture);
    const offset = scenario === 'stale' ? -25 * 3600000 : scenario === 'future' ? 6 * 60000 : 0;
    const end = Date.now() + offset;
    record.observed_at = new Date(end).toISOString().replace(/\.\d{3}Z$/, 'Z');
    record.preflight_at = new Date(end - 9 * 60000).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const immutable = structuredClone(record);
    if (scenario === 'refusal') record.postflight = 'failure';
    if (scenario === 'failed cases') record.totals.failed = 1;
    if (scenario === 'skipped cases') record.totals.skipped = 1;
    if (scenario === 'immutable mismatch') immutable.totals = {tests: 3, passed: 3, failed: 0, skipped: 0};
    if (scenario === 'unsafe link') record.run_url = 'javascript:alert(1)';
    await page.route('http://127.0.0.1:4173/', route => route.fulfill({contentType: 'text/html', body:
      scenario === 'HTML missing marker' ? '<html><head></head></html>' :
        `<html><head><meta name="application-commit" content="${['HTML mismatch', 'frontend mismatch'].includes(scenario) ? 'd'.repeat(40) : record.frontend_commit}"></head></html>`}));
    await page.route('**/release.json', route => route.fulfill({json: {commit: scenario === 'frontend mismatch' ? 'd'.repeat(40) : record.frontend_commit}}));
    await page.route('**/healthz', route => scenario === 'unavailable health' ? route.fulfill({status: 503, body: 'unavailable'}) :
      route.fulfill({json: {ok: true, run_state_store: 'aurora-dsql', commit: scenario === 'backend mismatch' ? 'd'.repeat(40) : record.backend_commit}}));
    await page.route('**/acceptance.json', route => {
      if (scenario === 'missing') return route.fulfill({status: 404, body: 'missing'});
      if (scenario === 'server error') return route.fulfill({status: 500, body: 'unavailable'});
      if (scenario === 'malformed') return route.fulfill({contentType: 'application/json', body: '{broken'});
      return route.fulfill({json: record});
    });
    await page.route('**/acceptance/runs/12345-2.json', route => scenario === 'immutable missing' ?
      route.fulfill({status: 404, body: 'missing'}) : route.fulfill({json: immutable}));
    const response = await page.goto('/acceptance.html');
    expect(response?.status()).toBe(200);
    await expect(page.getByTestId('acceptance-status')).toHaveText(status);
    await expect(page.getByText('NOT_RUN', {exact: true})).toBeVisible();
    if (status === 'CURRENT_AUTOMATED_PASS' || status === 'HISTORICAL') {
      await expect(page.locator('#current-frontend')).toHaveText(scenario === 'frontend mismatch' ? 'd'.repeat(40) : record.frontend_commit);
      await expect(page.locator('#recorded-backend')).toHaveText(record.backend_commit);
      await expect(page.getByTestId('acceptance-counts')).toHaveText('JUnit browser cases: 2 total; 2 passed; 0 failed; 0 skipped.');
      await expect(page.getByRole('link', {name: 'Immutable aggregate receipt'})).toHaveAttribute('href', record.receipt_path);
    } else {
      await expect(page.locator('#details')).toBeHidden();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

test('a previously passing page withdraws the pass when refresh sees a changed release', async ({page}) => {
  const record = structuredClone(fixture);
  record.observed_at = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  record.preflight_at = record.observed_at;
  let frontend = record.frontend_commit;
  await page.route('http://127.0.0.1:4173/', route => route.fulfill({contentType: 'text/html', body: `<html><head><meta name="application-commit" content="${frontend}"></head></html>`}));
  await page.route('**/release.json', route => route.fulfill({json: {commit: frontend}}));
  await page.route('**/healthz', route => route.fulfill({json: {ok: true, run_state_store: 'aurora-dsql', commit: record.backend_commit}}));
  await page.route('**/acceptance.json', route => route.fulfill({json: record}));
  await page.route('**/acceptance/runs/12345-2.json', route => route.fulfill({json: record}));
  await page.goto('/acceptance.html');
  await expect(page.getByTestId('acceptance-status')).toHaveText('CURRENT_AUTOMATED_PASS');
  frontend = 'd'.repeat(40);
  await page.getByRole('button', {name: 'Check again'}).click();
  await expect(page.getByTestId('acceptance-status')).toHaveText('HISTORICAL');
  await expect(page.locator('#current-frontend')).toHaveText(frontend);
});
