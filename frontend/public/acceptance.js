// Public receipt data is rendered as text. It cannot supply markup or arbitrary URLs.
const SHA = /^[0-9a-f]{40}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const NUMBER = /^[1-9][0-9]*$/;
const KEYS = 'schema_version application environment frontend_commit backend_commit backend_commit_basis run_id run_attempt run_url observed_at preflight_at preflight journeys postflight totals retry_count human_uat execution_mode limits workflow_status junit_sha256 receipt_path'.split(' ').sort();
const LIMITS = 'Automated Chromium desktop/mobile journeys on fictional data. No human UAT, staff identity, live model evaluation, real messages or downstream delivery claim.';
const sameKeys = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());
const matches = (value, pattern) => typeof value === 'string' && pattern.test(value);
const time = value => {
  if (!matches(value, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)) return NaN;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && new Date(parsed).toISOString().replace('.000Z', 'Z') === value ? parsed : NaN;
};

export function validateReceipt(r) {
  if (!sameKeys(r, KEYS) || r.schema_version !== 1 || r.application !== 'lasttake' || r.environment !== 'live_aws' ||
      !matches(r.frontend_commit, SHA) || !matches(r.backend_commit, SHA) || !matches(r.junit_sha256, DIGEST) ||
      !matches(r.run_id, NUMBER) || !matches(r.run_attempt, NUMBER) || r.human_uat !== 'NOT_RUN' ||
      r.backend_commit_basis !== 'GET /healthz before and after journeys; unchanged observed commit' ||
      r.execution_mode !== 'synthetic_data_scripted_planner_lexical_interpreter' || r.limits !== LIMITS ||
      r.workflow_status !== 'NOT_ASSERTED' || r.retry_count !== 0 || ['preflight', 'journeys', 'postflight'].some(key => r[key] !== 'success') ||
      r.run_url !== `https://github.com/upgradedev/lasttake-aws/actions/runs/${r.run_id}/attempts/${r.run_attempt}` ||
      r.receipt_path !== `/acceptance/runs/${r.run_id}-${r.run_attempt}.json`) throw new Error('Malformed or refused receipt');
  const totals = r.totals;
  if (!sameKeys(totals, ['tests', 'passed', 'failed', 'skipped']) ||
      Object.values(totals).some(n => !Number.isSafeInteger(n) || n < 0) || totals.tests < 20 ||
      totals.passed !== totals.tests || totals.failed !== 0 || totals.skipped !== 0) throw new Error('Incomplete JUnit aggregate');
  const duration = time(r.observed_at) - time(r.preflight_at);
  if (!Number.isFinite(duration) || duration < 0 || duration > 20 * 60 * 1000) throw new Error('Invalid observation time');
  return r;
}

const canonical = value => JSON.stringify(value, (key, item) => item && typeof item === 'object' && !Array.isArray(item) ?
  Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);

export function assess(release, health, receipt, immutable, now = Date.now(), servedFrontend) {
  if (!matches(release?.commit, SHA) || !matches(health?.commit, SHA) || health.ok !== true || health.run_state_store !== 'aurora-dsql' || servedFrontend !== release.commit) {
    return {status: 'UNKNOWN', reason: 'Current root HTML, frontend manifest or backend identity could not be verified as a consistent release.'};
  }
  if (!receipt) return {status: 'PENDING', reason: 'No published receipt is available. Current acceptance is not established.'};
  try {
    validateReceipt(receipt);
    validateReceipt(immutable);
    if (canonical(receipt) !== canonical(immutable)) throw new Error('Latest and immutable receipt differ');
  } catch {
    return {status: 'UNKNOWN', reason: 'The receipt is malformed, incomplete, refused, or does not match its immutable record.'};
  }
  if (receipt.frontend_commit !== release.commit || receipt.backend_commit !== health.commit) {
    return {status: 'HISTORICAL', reason: 'The recorded frontend/backend pair differs from the deployed pair. It cannot authorize this release.'};
  }
  const age = now - time(receipt.observed_at);
  if (age < -5 * 60 * 1000) return {status: 'UNKNOWN', reason: 'The observation time is in the future.'};
  if (age > 24 * 60 * 60 * 1000) return {status: 'HISTORICAL', reason: 'The last observation is older than 24 hours. A fresh acceptance run is needed.'};
  return {status: 'CURRENT_AUTOMATED_PASS', reason: 'The recorded preflight, browser journeys and postflight passed for the frontend/backend pair observed now. Human UAT remains NOT_RUN.'};
}

async function json(path, missingIsPending = false) {
  const response = await fetch(path, {cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(15000)});
  if (missingIsPending && [403, 404].includes(response.status)) return null;
  if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Evidence unavailable');
  const body = await response.text();
  if (body.length > 1000000) throw new Error('Evidence too large');
  return JSON.parse(body);
}

async function rootCommit() {
  const response = await fetch('/', {cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(15000)});
  if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('Root HTML unavailable');
  const body = await response.text();
  if (body.length > 1000000) throw new Error('Root HTML too large');
  const markers = [...body.matchAll(/<meta name="application-commit" content="([0-9a-f]{40})">/g)];
  if (markers.length !== 1) throw new Error('Root release marker missing or ambiguous');
  return markers[0][1];
}

export async function refresh(document) {
  const set = (id, value) => { document.getElementById(id).textContent = value; };
  const verdict = document.getElementById('verdict');
  const button = document.getElementById('refresh');
  const details = document.getElementById('details');
  button.disabled = true;
  details.hidden = true;
  set('verdict', 'PENDING');
  verdict.dataset.status = 'PENDING';
  set('reason', 'Checking the deployed revisions and recorded evidence.');
  for (const id of ['current-frontend', 'current-backend', 'recorded-frontend', 'recorded-backend']) set(id, 'Unknown');
  try {
    const [release, health, receipt, htmlCommit] = await Promise.all([json('/release.json'), json('/healthz'), json('/acceptance.json', true), rootCommit()]);
    if (matches(release?.commit, SHA)) set('current-frontend', release.commit);
    if (matches(health?.commit, SHA)) set('current-backend', health.commit);
    let immutable = null;
    if (receipt) {
      validateReceipt(receipt);
      set('recorded-frontend', receipt.frontend_commit);
      set('recorded-backend', receipt.backend_commit);
      immutable = await json(receipt.receipt_path);
    }
    // A release can change during fetching: compare the second identity read too.
    const [current, backend, currentHTML] = await Promise.all([json('/release.json'), json('/healthz'), rootCommit()]);
    set('current-frontend', matches(current?.commit, SHA) ? current.commit : 'Unknown');
    set('current-backend', matches(backend?.commit, SHA) ? backend.commit : 'Unknown');
    let result = assess(current, backend, receipt, immutable, Date.now(), currentHTML);
    if (release.commit !== current.commit || health.commit !== backend.commit || htmlCommit !== currentHTML) result = {status: 'UNKNOWN', reason: 'The deployed revision changed while checking. Check again.'};
    set('verdict', result.status);
    verdict.dataset.status = result.status;
    set('reason', result.reason);
    if (receipt && ['CURRENT_AUTOMATED_PASS', 'HISTORICAL'].includes(result.status)) {
      details.hidden = false;
      set('observed', `Recorded observation: ${receipt.observed_at}`);
      set('stages', `Recorded stages: preflight ${receipt.preflight}; journeys ${receipt.journeys}; postflight ${receipt.postflight}. Overall workflow result: not asserted.`);
      set('counts', `JUnit browser cases: ${receipt.totals.tests} total; ${receipt.totals.passed} passed; ${receipt.totals.failed} failed; ${receipt.totals.skipped} skipped.`);
      document.getElementById('receipt-link').href = receipt.receipt_path;
      document.getElementById('run-link').href = receipt.run_url;
    }
  } catch {
    set('verdict', 'UNKNOWN');
    verdict.dataset.status = 'UNKNOWN';
    set('reason', 'Evidence is unavailable or malformed. No current pass is established. Check again when the release and receipt are reachable.');
  } finally { button.disabled = false; }
}

if (typeof document !== 'undefined' && document.getElementById('verdict')) {
  document.getElementById('refresh').addEventListener('click', () => refresh(document));
  void refresh(document);
  setInterval(() => { if (!document.getElementById('refresh').disabled) void refresh(document); }, 60000);
}
