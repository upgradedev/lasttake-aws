# Releases and acceptance evidence

This page is for the release owner, and for a reviewer checking whether the live URL serves current, accepted code. It covers release verification: how the frontend and the backend each reach AWS, what the public acceptance receipt proves and what it does not, what runs on a schedule against the live service, and which evidence is only history. It expands [README, What is deployed, and what it costs](../README.md#what-is-deployed-and-what-it-costs). The two release lanes are drawn in [Infrastructure, Release paths](infrastructure.md#release-paths).

## Current automated acceptance

[Current automated acceptance](https://d3kf6hquzlli8g.cloudfront.net/acceptance.html) compares the frontend and backend commits the site serves now with the latest public aggregate receipt, [/acceptance.json](https://d3kf6hquzlli8g.cloudfront.net/acceptance.json). Missing, malformed, mismatched or older-than-24-hour proof cannot establish a current pass.

Human UAT remains `NOT_RUN`. That status means no person has completed the 22-case manual UAT testbook: all 22 cases in [frontend/UAT.testbook.json](../frontend/UAT.testbook.json) record `human_signoff` as `NOT_RUN`. It is separate from automated acceptance, and an automated pass never changes it.

The page reads `/release.json`, `/healthz`, the commit marker in the root HTML, `/acceptance.json` and the per-run copy that the receipt names. It then reads the three identity sources a second time, in case a release lands during the check. The verdict comes from the `assess` function in [frontend/public/acceptance.js](../frontend/public/acceptance.js):

| Status | When the page shows it |
| --- | --- |
| `CURRENT_AUTOMATED_PASS` | The receipt is valid, matches its per-run copy, names the frontend and backend commits served now, and was observed no more than 24 hours ago. |
| `HISTORICAL` | A valid receipt names a different frontend or backend commit, or was observed more than 24 hours ago (`frontend/public/acceptance.js:53`). |
| `PENDING` | No receipt is published. |
| `UNKNOWN` | The served commits are unreadable or disagree with each other, the receipt is malformed or differs from its per-run copy, its observation time is more than 5 minutes in the future, or the release changed while the page was checking. |

The page ships with every frontend release, and it answered HTTP 200 on 2026-09-14 at 06:54 GMT. Source CI builds the page and tests its refusal states, but it never publishes a receipt. Only the main-branch publisher described below does.

On 2026-09-14 at 06:52 GMT, `/acceptance.json` recorded run [34771631979](https://github.com/upgradedev/lasttake-aws/actions/runs/34771631979) attempt 1: 26 tests, 26 passed, observed at 2026-09-13T17:50:50Z, for frontend `ab0a1d35cb41510af42fe9b7982b01e081e15b04` and backend `a3e3d390489382708f4b32a020ea4c9c5293e576`. Under the 24-hour rule that receipt stops counting as current at 2026-09-14T17:50:50Z unless a newer run replaces it, so read the page itself rather than this paragraph.

## Frontend release and live acceptance on every push to main

Every push to `main` starts [frontend-deploy.yml](../.github/workflows/frontend-deploy.yml) ([run list on GitHub Actions](https://github.com/upgradedev/lasttake-aws/actions/workflows/frontend-deploy.yml)). That includes a merged pull request and a change to documentation only, because the workflow has no path filter (`frontend-deploy.yml:2-5`). It can also be started by hand. It runs three jobs in order:

| Job | What it does | AWS credentials |
| --- | --- | --- |
| `verify` | Runs the `verify` job of [frontend-ci.yml](../.github/workflows/frontend-ci.yml) (`frontend-deploy.yml:14-15`), described under [Source CI](#source-ci-the-lambda-package-and-the-http-handler). | None |
| `release` | Main only. Stops unless the dependency lock is committed and the `FRONTEND_RELEASE_ROLE_ARN` repository variable is set. Builds from the lock, publishes with `infra/frontend_publish.py`, then checks the served commit, assets, headers and API errors with `infra/frontend_smoke.py` (`frontend-deploy.yml:16-64`). | The GitHub OIDC role `lasttake-frontend-release`, which only the `main` branch can assume |
| `acceptance` | Calls [aws-uat.yml](../.github/workflows/aws-uat.yml) with the pushed commit (`frontend-deploy.yml:65-74`). | None in the browser job; the publisher job uses the same OIDC role |

The site bucket and CloudFront distribution must already exist. No workflow deploys the `lasttake-frontend` stack rendered by `infra/frontend_stack.py`; the owner provisions it. No file in this repository creates the GitHub OIDC provider that its release role trusts. Without the stack and the role variable, the release job stops with "Provision infra/frontend_stack.py and set FRONTEND_RELEASE_ROLE_ARN first." (`frontend-deploy.yml:40`).

`infra/frontend_publish.py` never deletes an object. It uploads `index.html` after every other file, writes `release.json`, and invalidates `/`, `/index.html` and `/release.json` (`infra/frontend_publish.py:3-4`, `:82`, `:95-96`). It refuses to upload `acceptance.json` or anything under `acceptance/` (`:42-43`), so a frontend release cannot overwrite a receipt.

**One release at a time.** The whole workflow holds the concurrency group `lasttake-frontend-release` with `cancel-in-progress: false` and `queue: max` (`frontend-deploy.yml:9-12`). The lock stays held until acceptance finishes, and a later push waits in the queue instead of interrupting a running test. The release job and the receipt publisher also share the group `lasttake-frontend-write` (`frontend-deploy.yml:19-22`, `aws-uat.yml:114-117`).

**What live acceptance checks.** The `acceptance` job in `aws-uat.yml` tests the exact commit that was just published:

1. Preflight requires a full 40-character commit, reads `/release.json`, `/healthz` and the root HTML, and runs the smoke check against that commit (`aws-uat.yml:42-49`).
2. The journeys run with `npm run test:e2e -- --forbid-only` against `https://d3kf6hquzlli8g.cloudfront.net/` (`aws-uat.yml:32`, `:57-60`). `--forbid-only` fails the run if a focused `test.only` was committed. The hero, journeys and workspaces specs also fail on any uncaught browser error (`frontend/tests/e2e/hero.spec.ts:42`, `journeys.spec.ts:60`, `workspaces.spec.ts:129`).
3. Postflight repeats the smoke check and the identity reading (`aws-uat.yml:61-68`), so a release that changed during the journeys fails.

**What each run keeps.** The artifact `aws-acceptance-<run>-<attempt>` holds the HTML and JUnit reports, traces, screenshots, failure videos and the UAT testbook for 90 days (`aws-uat.yml:86-98`; trace, screenshot and video settings in `frontend/playwright.config.ts:7`). The step summary records the commit and the three stage results, and states that human UAT is `NOT_RUN` (`aws-uat.yml:76-85`).

**What a failure does.** It turns the workflow run red. It does not revert the merge, and no step restores the previous site. If the new site was published and acceptance then failed, the acceptance page shows the older receipt as `HISTORICAL`, because its frontend commit no longer matches `/release.json`. Backend deployment is a separate process, described next.

**Manual reruns.** `frontend-deploy.yml` can be dispatched by hand (`frontend-deploy.yml:5`), and so can `aws-uat.yml`, with the full commit that `/release.json` reports (`aws-uat.yml:9-14`). A dispatched acceptance stops at preflight unless it runs on `main` and that commit is also the current head of `main` (`infra/frontend_acceptance.py:91-98`). Automated results never set human UAT signoff to PASS: a receipt whose `human_uat` is anything other than `NOT_RUN` is refused (`infra/frontend_acceptance.py:155`).

## Backend release by manual dispatch

[deploy.yml](../.github/workflows/deploy.yml) changes the backend stack only when an owner dispatches it with the action `deploy` (`deploy.yml:12-18`, `:38`). Source pushes cannot start that job.

The workflow also lists pushes to `main` that touch `src/**`, `corpus/**` or `infra/stack.yaml` (`deploy.yml:19-26`). Such a push creates a run, but every job's condition needs a dispatch input (`deploy.yml:38`, `:447`, `:655`), so every job is skipped. Runs [34478083003](https://github.com/upgradedev/lasttake-aws/actions/runs/34478083003) on 2026-09-10 and [34571476397](https://github.com/upgradedev/lasttake-aws/actions/runs/34571476397) on 2026-09-11 both concluded `skipped`. Merged backend code reaches the live service only at the next dispatched deploy, so the live backend can be older than `main`. `/healthz` reports the live commit: on 2026-09-14 at 06:52 GMT it was `a3e3d390489382708f4b32a020ea4c9c5293e576`.

The split keeps stack updates and real Bedrock calls out of ordinary merges. It is not an approval step on ordinary work: code still merges, and the frontend still releases automatically.

**Credentials.** The deploy, lifecycle and teardown jobs use the long-lived access keys of the IAM user `lasttake-ci`, stored as repository secrets (`deploy.yml:66-71`). The owner creates that user and its keys by running `infra/setup_ci_identity.py` once, by hand. Until the secrets exist, the deploy job writes a summary and does nothing (`deploy.yml:45-64`). What that user may do is set out in [Infrastructure, Least privilege, as deployed](infrastructure.md#least-privilege-as-deployed).

**What a dispatched deploy does**, in order:

| Step | What happens | Lines in `deploy.yml` |
| --- | --- | --- |
| Build | Installs arm64 Python 3.12 wheels for `strands-agents`, `pydantic` and `psycopg`, copies `src/lasttake` and `corpus/*.json`, and deletes `boto3` and `botocore`, which the Lambda runtime already provides. | 87-105 |
| Upload | Uploads the ZIP, named by the first 16 hex characters of its SHA-256, to the `lasttake-deploy-<account>-<region>` bucket, creating that bucket if it is missing. | 107-124 |
| Apply | Replaces a stack stuck in `ROLLBACK_COMPLETE` or `REVIEW_IN_PROGRESS`, removes an orphaned data bucket only if it is empty, then applies `infra/stack.yaml` as `lasttake-app` with the commit as a parameter. | 126-204 |
| Health | The HTTP API endpoint must answer 200, and `/healthz` must report `ok` and a `run_state_store` of `aurora-dsql`. | 206-228 |
| Interrupt across containers | `POST /api/checkpoint` must stop the run for the 1st AD with 31 beats covered. A configuration change then retires every warm container. `POST /api/approve` must be served by a different container (`c1 != c2`), with the pickup event accepted by the bus. Late take and rights resolution follow. | 230-331 |
| Blocked runs | `GET /api/blocked` must return a JSON body with a `blocked` key (`deploy.yml:342`). The step then prints the run id and counts of up to ten rows, which fails only if a row lacks those fields. An empty list passes. | 333-347 |
| Bedrock | Runs `lasttake doctor --bedrock` and `lasttake checkpoint --bedrock` on the GitHub runner with the `lasttake-ci` keys, not with the Lambda execution role. It requires 34 model-touched findings with `bedrock:` model identifiers and confidence below 1.0, 34 required beats, and no more than 31 covered. One direct `aws bedrock-runtime converse` call follows, also from the runner, despite its step name. | 356-429 |

Every HTTP check in the deploy job calls the HTTP API endpoint that the stack publishes as its `LiveUrl` output, not the CloudFront URL (`deploy.yml:194-197`). The interrupt check is explained in [Interrupt and resume across process death](strands-interrupt-resume.md#on-lambda-two-requests-two-containers-historical).

The `lifecycle` and `teardown` actions are dispatched the same way; see [Infrastructure, Lifecycle and teardown](infrastructure.md#lifecycle-and-teardown). A credential-free code package built by branch CI is described under [Source CI](#source-ci-the-lambda-package-and-the-http-handler). It does not start this workflow and does not establish AWS acceptance.

## What the public receipt requires

`infra/frontend_acceptance.py build` writes the receipt inside the `acceptance` job. The publisher and the acceptance page check it again. A receipt exists only when every rule below holds; the line numbers refer to [infra/frontend_acceptance.py](../infra/frontend_acceptance.py).

**All three stages passed, against one release.** Preflight, journeys and postflight must all report success (`:179`). The frontend commit must be the release under test both before and after the journeys, and the backend commit must not change between them (`:181-182`). The frontend and backend commits may legitimately differ from each other; the receipt records the exact pair observed.

**The served site proves its own identity.** `/release.json` must name the tested commit. `/healthz` must report `ok`, `aurora-dsql` and a full backend commit. The root HTML must carry exactly one `application-commit` marker, equal to the tested commit (`:78-88`). A manifest alone cannot establish identity, so a partial release or a rollback that leaves a different `index.html` in place is refused.

**JUnit totals are complete.** The JUnit file, `frontend/test-results/e2e.xml`, supplies the totals. Every suite's counts must match its cases, with no failures, errors or skips, and the root totals must agree. Duplicate, nested, empty and unnamed cases are refused. There must be at least 20 product cases (`MIN_PRODUCT_CASES`, `:26`; checked at `:101-124`).

**The same run's Playwright JSON report agrees.** The JSON report, `frontend/test-results/e2e-results.json`, must list no errors and exactly two projects, `desktop` and `mobile`, each with no retries and no repeats. Its expected count must equal the JUnit total, with nothing unexpected, skipped or flaky, and every test must pass on its single attempt. That refuses retries, repeated cases, skipped cases, expected failures and any disagreement with JUnit (`:125-148`).

**The receipt has a fixed shape.** It has exactly 22 fields (`:30`, `:153`), and several values are fixed (`:154-157`):

- `environment` is `live_aws`, and `execution_mode` is `synthetic_data_scripted_planner_lexical_interpreter`.
- `human_uat` is `NOT_RUN`, and `retry_count` is 0.
- `preflight`, `journeys` and `postflight` are `success`.
- `workflow_status` is `NOT_ASSERTED`. That means the receipt makes no claim that the whole workflow run succeeded; it records only the three stages above.

Totals must show at least 20 tests, all passed. Preflight and the final observation must be at most 20 minutes apart. When the receipt is built or published, its observation must be no more than 24 hours old and no more than 5 minutes in the future (`:170-174`).

**No raw test data is published.** The fields hold commits, run identity, times, counts, fixed labels and a SHA-256 of the JUnit file. None holds scenario text, credentials or personal information. The raw Playwright JSON report stays in the CI evidence artifact and is never published to the site bucket; only `acceptance-receipt.json` is exported to the publisher (`aws-uat.yml:99-106`).

**A publisher-only retry keeps the original attempt.** If only the publish job is re-run, it downloads the artifact named by the acceptance job's output and uses that job's attempt number (`aws-uat.yml:124`, `:130-133`; `infra/frontend_acceptance.py:284-285`). The published receipt keeps the run and attempt that actually executed the journeys.

## How the receipt is published

`aws-uat.yml` splits the work across three jobs, so the job that drives a browser against the live site never holds cloud credentials.

| Job | Credentials | What it does |
| --- | --- | --- |
| `acceptance` | `contents: read` only (`aws-uat.yml:26-27`) | Runs preflight, journeys and postflight, parses the current run's product JUnit into sanitized totals, and exports the receipt as the artifact `acceptance-public-<run>-<attempt>` (`aws-uat.yml:42-106`). |
| `publish` | The OIDC role `lasttake-frontend-release`; runs on `main` only, and only after `acceptance` succeeds (`aws-uat.yml:107-137`) | Runs `infra/frontend_acceptance.py publish` with the checks listed below (`aws-uat.yml:138-141`). |
| `verify-public-proof` | `contents: read` only (`aws-uat.yml:142-149`) | Opens `/acceptance.html` and the receipt as an anonymous visitor in desktop, mobile and compact mobile browsers. It requires `CURRENT_AUTOMATED_PASS`, the same commit pair, this run and attempt, the counts and `NOT_RUN` (`aws-uat.yml:169-171`, `frontend/acceptance-tests/live.spec.ts`). |

The publisher writes only after these checks, in this order (line numbers in `infra/frontend_acceptance.py`):

1. The run is on `main` in this repository, and the checked-out commit equals both the release and the current head of `main`. Otherwise it stops as a stale dispatch (`:91-98`).
2. The receipt bytes are valid, canonical and still fresh, and they name this release, run and attempt (`:218-220`).
3. The bucket and URL come from the `lasttake-frontend` stack outputs, and must match the expected bucket name pattern and the CloudFront URL (`:221-224`).
4. The served site still shows the tested frontend, `/healthz` still shows the recorded backend, and `release.json` in the bucket itself names the tested commit (`:230-236`). A changed backend refuses publication.
5. `/acceptance/runs/<run-id>-<attempt>.json` is written create-only. If it already exists, the stored bytes must be identical, so a retry cannot rewrite history (`:237-245`).
6. An `/acceptance.json` observed later than this receipt is never replaced, and one with the same observation time must be byte-identical (`:246-251`).
7. The identity checks run once more. Then `/acceptance.json` is replaced conditionally: only if its ETag is unchanged, or create-only when it does not exist yet (`:254-258`).
8. CloudFront invalidates `/acceptance.json`, `/acceptance.html`, `/acceptance.js` and the per-run path (`:259-260`).

Earlier per-run receipts stay in the bucket, because the publisher never deletes and a frontend release refuses to touch `acceptance/` (see [the frontend release](#frontend-release-and-live-acceptance-on-every-push-to-main)).

Source-only fault fixtures for the acceptance page have their own Playwright configuration and JUnit file (`frontend/playwright.proof.config.ts`, which writes `test-results/proof-junit.xml`), so they never enter the public product-journey counts. The same holds for the WebKit subset, which writes `test-results/webkit-junit.xml` (`frontend/playwright.webkit.config.ts`).

The publisher and the page are tested in CI:

| Command | Where it runs | What it exercises |
| --- | --- | --- |
| `python infra/test_frontend_acceptance.py` | `aws-hosting-ci.yml:28-29`, on pull requests and on pushes to `main` or `codex/**` when they touch the paths listed at `aws-hosting-ci.yml:3-7`, or by hand (`aws-hosting-ci.yml:8`) | Malformed and false JUnit, the 20-case minimum, retries and expected failures, a changed pair, stale dispatch, old or future proof, immutable collisions, a release change during publication, a newer latest receipt, publisher retries, root HTML markers and conditional publication |
| `npx playwright test --config playwright.proof.config.ts` | `frontend-ci.yml:240-243` | The anonymous acceptance page's refusal states, from source-only fixtures |
| `python infra/frontend_acceptance.py inspect-junit` | `frontend-ci.yml:244-246` | The receipt parser on the source run's own JUnit. Its output is marked `SOURCE_CI_ONLY`, meaning it describes a source run and is never published. |

## Scheduled checks on the live surface

Two scheduled workflows call the live service, and a third reads the source. None of them holds AWS credentials. "The HTTP API endpoint" below is the API Gateway address that the backend stack publishes as its `LiveUrl` output; calls to it bypass CloudFront.

| Workflow | When | Target | What it checks | On failure |
| --- | --- | --- | --- | --- |
| [uptime.yml](../.github/workflows/uptime.yml) | Daily at 07:17 and 19:17 UTC, or by hand (`uptime.yml:14-20`) | The HTTP API endpoint, then the CloudFront URL | `tools/uptime_check.py` walks a longer journey than the backend deploy: checkpoint, pickup approval, late take, rights resolution, evaluate, decide, wrap and turnover. It creates runs on the live stack. `tools/judge_url_check.py` then requires `/acceptance.json` to name the commit `/release.json` serves, with journeys and postflight passed. It also scans the served bundles for sentences the product may not say, checks that the scene preview says it is fictional, and runs the smoke check. | Opens an issue labelled `uptime`, or comments on the open one, and closes it after the next success (`uptime.yml:54-121`) |
| [live-surface.yml](../.github/workflows/live-surface.yml) | Daily at 08:17 UTC; on pushes to `main` that touch `src/lasttake/app/**`, `web/**`, `tools/dast_probe.py` or the workflow; or by hand (`live-surface.yml:11-21`) | The HTTP API endpoint only | `tools/dast_probe.py` sends 34 scripted hostile bodies, including prompt-injection text. The endpoint runs the offline interpreter, so no model is probed. The `web/tests` Playwright suite runs 21 tests against the legacy page the Lambda serves at that endpoint, not the React workspace. | The run fails, and a failed browser job keeps its trace for 90 days (`live-surface.yml:62-67`). No issue is opened. |
| [codeql.yml](../.github/workflows/codeql.yml) | Mondays at 05:41 UTC; on pushes and pull requests to `main`; or by hand (`codeql.yml:30-37`) | The Python source, not the live service | CodeQL with the `security-extended` queries (`codeql.yml:75-78`) | Where code scanning is not enabled, the SARIF file is kept as an artifact and any finding fails the job (`codeql.yml:87-133`) |

## Journey counts, each with its date and source

A journey count describes one suite on one date. The suite grew between these dates, so the numbers are not a trend.

| Count | What it counts | Date | Source |
| --- | --- | --- | --- |
| 8 | Every test in the live acceptance suite at that time, desktop and mobile | 2026-09-09 | Run [34327806494](https://github.com/upgradedev/lasttake-aws/actions/runs/34327806494), whose job log prints "Running 8 tests using 1 worker" and "8 passed (5.4m)" |
| 20 | The fewest product cases a public receipt accepts; a smaller total is refused | In force at this commit of the repository | `MIN_PRODUCT_CASES` in `infra/frontend_acceptance.py:26`, and the same minimum in `validateReceipt` in `frontend/public/acceptance.js` |
| 26 | The 13 `test()` entries in `frontend/tests/e2e` (hero 2, journeys 5, reliability 2, workspaces 4), each run once in the `desktop` and `mobile` projects of `frontend/playwright.config.ts:8` | Observed 2026-09-13T17:50:50Z | Run [34771631979](https://github.com/upgradedev/lasttake-aws/actions/runs/34771631979) attempt 1, as recorded in `/acceptance.json` when read on 2026-09-14 at 06:52 GMT |
| 21 | Playwright tests against the legacy page at the HTTP API endpoint (handover 6, intake 8, journey 7). Not part of any receipt. | Daily, and on matching pushes | `web/tests`, run by `live-surface.yml` |

Before stating a current figure, read `/acceptance.json` and apply the 24-hour rule. Every push to `main` that passes live acceptance publishes a newer receipt.

## Historical release evidence

Everything in this section is history. None of it describes the release served today.

**2026-09-09: 8 journeys on an earlier frontend.** [Live AWS acceptance run 34327806494](https://github.com/upgradedev/lasttake-aws/actions/runs/34327806494), dispatched by hand on `main`, passed all 8 desktop and mobile journeys against CloudFront, Lambda, S3 and Aurora DSQL. The tested frontend was `1f10d39c8b2b22474f64b1c057851eb2057665e7`. This is automated synthetic acceptance, not a practising supervisor's signoff. The run predates the dashboard and cockpit, so it does not validate them. Today's release identity is at `/release.json`, and today's backend identity is at `/healthz`.

**2026-09-09: the accepted run that was archived.** Frontend release run [34359050749](https://github.com/upgradedev/lasttake-aws/actions/runs/34359050749), a push to `main` at `78e91cbad29f1511c4e7be2b5eac4f55e308acd6`, produced the acceptance artifact `10107569851`, created at 2026-09-09T13:57:41Z. Read on 2026-09-14, the GitHub API gave its expiry as 2026-09-23T13:57:31Z.

Later that day the `archive-previous-acceptance` job (job 102548285970) copied that artifact's bytes, unextracted, into archive artifact [10113819181](https://github.com/upgradedev/lasttake-aws/actions/runs/34375838628/artifacts/10113819181), which expires on 2026-12-08. The job succeeded inside frontend-ci run [34375838628](https://github.com/upgradedev/lasttake-aws/actions/runs/34375838628) on the branch `codex/reliable-workflows-20260909`; the run as a whole concluded `failure`, because its `verify` job failed. The archive's `manifest.json` records the original run and artifact identifiers, the artifact name, head commit and creation time, the artifact digest, and the SHA-256 and size of the archived ZIP (`frontend-ci.yml:109-116`).

Archival is now manual opt-in. The job runs only on a `workflow_dispatch` with `archive_previous_acceptance` set to true (`frontend-ci.yml:13-17`, `:72`), and it skips when an unexpired archive already exists (`frontend-ci.yml:93-98`). Ordinary verification does not repeat it.

**Other history.** Earlier observations in `frontend/UAT.testbook.json` and the artifacts of failed runs remain dated history, not current acceptance. Current acceptance comes only from the live acceptance run after each push to `main`, described in [Current automated acceptance](#current-automated-acceptance).

## Source CI: the Lambda package and the HTTP handler

Repository validation runs in GitHub Actions. The source workflows below check code and build artifacts; they deploy nothing and publish no acceptance receipt.

- [ci.yml](../.github/workflows/ci.yml) runs on pushes to `main`, `build/**` and `codex/**`, on every pull request, and on manual dispatch (`ci.yml:5-18`). Its `hero` job, shown in Actions as `interrupt survives process death` (`ci.yml:254-255`), has no condition of its own and runs the interrupt across two processes; see [Interrupt and resume across process death](strands-interrupt-resume.md#in-ci-two-processes-and-a-negative-control). Its `evaluation-parent` job is separate from release: it can assume an OIDC role only on a gated manual dispatch, and no code in this repository provisions that role.
- [frontend-ci.yml](../.github/workflows/frontend-ci.yml) runs on pushes to `main` and `codex/**`, on pull requests, by hand, and as the `verify` job of every frontend release (`frontend-ci.yml:2-18`).
- [aws-hosting-ci.yml](../.github/workflows/aws-hosting-ci.yml) runs on pull requests and on pushes to `main` or `codex/**` when they touch the hosting paths it lists, or by hand (`aws-hosting-ci.yml:2-8`). It tests the frontend stack template and renders it, but does not deploy it.

**The HTTP handler, exercised by frontend-ci.yml.** The `verify` job has `contents: read` and sets `AWS_EC2_METADATA_DISABLED`, so it has no AWS identity and needs no model credentials (`frontend-ci.yml:126-134`). In order, it:

- resolves a dependency lock only when `frontend/package-lock.json` is absent, and uploads the lock (`frontend-ci.yml:147-157`)
- builds the React app and uploads `frontend/dist` (`frontend-ci.yml:162-171`). That artifact exists even when later checks fail, so it is diagnosis material, not a release.
- audits npm dependencies (`frontend-ci.yml:172-186`)
- runs the Python regression suite with at least 85% coverage (`frontend-ci.yml:187-189`), component tests with coverage (`frontend-ci.yml:190-193`), functional contracts (`frontend-ci.yml:194-197`) and the hero-measurement instrument fixtures (`frontend-ci.yml:198-201`)
- drives desktop and mobile Chromium against the real Python HTTP handler with local durable adapters (`frontend-ci.yml:236-239`). Playwright starts the handler with `python -m lasttake.app.local_server --state-dir .lasttake-ui` and serves the build with `npm run preview` (`frontend/playwright.config.ts:9-12`). Vite's proxy sends `/api` and `/healthz` to `127.0.0.1:8765` (`frontend/vite.config.ts:3`).
- checks the acceptance page's refusal states and the receipt parser (`frontend-ci.yml:240-246`)
- runs the critical mobile journeys on WebKit, with a separate JUnit file (`frontend-ci.yml:252-260`)
- scans the whole history for secrets and runs the prose gate (`frontend-ci.yml:261-273`)

Publishing to AWS happens only in the `release` job of `frontend-deploy.yml`, described [above](#frontend-release-and-live-acceptance-on-every-push-to-main).

**The Lambda package, built by ci.yml.** The `lambda-package` job builds a Python 3.12 arm64 Lambda ZIP from source, without AWS credentials (`ci.yml:153-186`).

- It runs only on two branches, `codex/security-boundaries-20260910` and `codex/history-pagination-20260910`, after the `test` and `hero` jobs pass (`ci.yml:156-157`). It does not run on `main`.
- It resolves arm64 wheels for `strands-agents`, `pydantic`, `psycopg` and `boto3` (`ci.yml:169-177`). [tools/package_lambda.py](../tools/package_lambda.py) then writes `lasttake.zip` with `src/lasttake`, `corpus/*.json`, those dependencies and a `_lasttake_build.json` manifest (`tools/package_lambda.py:71-113`). The artifact is kept for 90 days as `lasttake-lambda-arm64-<sha>-<attempt>` (`ci.yml:180-186`).
- The manifest records the source commit, the git trees of the source, backend and corpus, the workflow run, each dependency's name and version, the dependency report hash, and a SHA-256 for every source and corpus file (`tools/package_lambda.py:40-46`, `:91-104`). A separate `build-receipt.json` adds the ZIP's SHA-256, the base64 Lambda code checksum, and byte and file counts (`:120-123`).
- It refuses to package when:
  - the checkout differs from the workflow commit or is not clean (`:33-39`)
  - `boto3`, `botocore`, `strands`, `pydantic` or `psycopg` is missing (`:18`, `:75-77`)
  - a native library is not 64-bit little-endian arm64 ELF (`:57-68`)
  - the unpacked size exceeds 250 MiB (`:16`, `:107-108`)
  - the zipped size exceeds 50 MiB (`:17`, `:118-119`)
  - the ZIP fails its integrity test (`:114-116`)

The code is cross-compiled and never executed on arm64 or on AWS; the manifest says so with `verification_scope` set to `SOURCE_ONLY_CROSS_COMPILED_NOT_EXECUTED_ON_ARM64_OR_AWS` (`:101`). The artifact does not deploy, does not update `LASTTAKE_COMMIT_SHA`, and proves nothing about live acceptance. Its `runtime_environment_commit` of `NOT_OBSERVED_OR_CHANGED` means the job neither read nor changed the commit the live function reports (`:102`). A release owner rolling it out must verify the code checksum and `LASTTAKE_COMMIT_SHA` separately (`:103`). Current AWS status stays on `/acceptance.html`.

This branch package and the dispatched deploy package differ. The branch ZIP bundles `boto3` and `botocore`, recorded as `dependency_mode` `bundled-including-boto3-botocore-and-distribution-metadata` (`tools/package_lambda.py:95`). The package that `deploy.yml` ships deletes both, because the Lambda runtime provides them (`deploy.yml:100-101`).
