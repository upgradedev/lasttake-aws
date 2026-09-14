# Using the LastTake workspace

This page is for a judge or tester who wants to walk the live site in depth, and for whoever runs the human UAT testbook. It covers how the workspace behaves and how it recovers; how to check which release is live is in [Releases and acceptance evidence](release-and-acceptance.md). The live application is the [LastTake React workspace](https://d3kf6hquzlli8g.cloudfront.net/). The short version of the walk is in the [README, Try it without installing anything](../README.md#try-it-without-installing-anything).

## What the live workspace is and is not

The live workspace runs the scripted planner `offline-scripted/1.0.0` and the offline lexical interpreter `offline-lexical/1.0.0`. It makes real Strands Agents SDK tool calls, resumes Strands sessions from S3, and gates each decision by demo role. The hosted HTTP path always runs this way: it has no Bedrock switch (`src/lasttake/app/handler.py:146, 169`).

Only three requests go through the Strands agent: the checkpoint, the pickup answer, and the wrap request and its answer (`/api/checkpoint`, `/api/approve`, `/api/wrap`). Evidence intake reruns the checks directly (`src/lasttake/app/ingest.py:318-330`). **Review wrap readiness** calls the gate tool directly, and **Publish approved turnover** calls the turnover tool directly (`handler.py:497-505, 548-566`).

It does not:

- analyse footage or audio
- send emails or make payments
- establish legal sufficiency
- authenticate staff. A demo role is something you pick on the page, not a login.

The top bar says the same in one line: "Synthetic demo · No footage/audio analysis or legal clearance. Demo roles are not staff authentication." (`frontend/src/App.tsx:97`).

Handoff provides the turnover, receipts with an evidence summary, and delivery status. Together they export:

- the sources and their digests
- the current human decisions
- the script revision and package digest
- the model identifiers serialized on each finding
- delivery and recovery status
- the stated limits

(`src/lasttake/domain/turnover.py`, `src/lasttake/domain/receipt.py`). Hashes identify bytes, not truth.

## The walk, step by step

This is the four-step journey the automated test follows (see [What the walk is tested against](#what-the-walk-is-tested-against)). Words in bold are the exact button, field and page names on screen. Change roles with the **Demo role** menu at the top of the page.

| Step | Demo role | Page | Done when |
|---|---|---|---|
| 1. Checkpoint | any | Scene review | the wrap board shows counts and a pickup request is waiting |
| 2. Evidence change | 1st AD, then any | Scene review | the pickup is answered and a take and a release are saved |
| 3. Human wrap decision | Script supervisor, DIT / data manager, 1st AD | Scene review | **Wrap decision saved by the server** appears |
| 4. Editorial handoff | any; 1st AD to retry a delivery | Handoff | the turnover is saved and a wrap receipt is prepared |

### Step 1: Checkpoint

1. Open the [workspace](https://d3kf6hquzlli8g.cloudfront.net/) and press **Start this fictional shoot day**. A browser that already owns a run also sees **Continue my saved shoot day**, with that run's status and date. Starting creates a run (`POST /api/reset`) and opens it in **Scene review** (`frontend/src/useWorkspace.ts:74-79`).
2. Press **Run wrap checkpoint**. The button posts to `/api/checkpoint`. That route first publishes `scene.wrap-checkpoint.requested` to record the request, then starts the Strands orchestrator itself in the same request (`src/lasttake/app/handler.py:275-286`). The repository declares no EventBridge rule, so nothing routes the event: `infra/stack.yaml:127-142` declares the bus and nothing that listens to it.
3. Read the wrap board above the script. On the fictional corpus it shows 34 required beats: 31 covered with evidence, 2 raising exceptions and 1 with no release record. `tests/test_corpus_counts.py` asserts those numbers. The gate keeps a separate tally of beats; see [Wrap status](#wrap-status).
4. **Evidence gate** reads **Blocked**. The gate names four causes, one per check: coverage B-17, continuity CR-01, metadata T-013 and rights BG-07. They go to three roles, because the script supervisor owns both coverage and continuity. The command that reproduces this is in the [README numbers table](../README.md#the-numbers-and-the-commands-that-produce-them).
5. Open a take. Each take under a beat is a row that starts with **Slate**. Its table, **Take sidecar and camera report**, puts the take's own media identifier, camera roll and lens beside the independent camera report. A row that disagrees is marked, and a report that was never supplied reads **Missing**. Missing evidence stays missing.
6. The next-step panel now reads "Review the saved pickup request".

### Step 2: Evidence change

1. Optional, so that step 8 has something to show: select **Script supervisor** and record a decision on **continuity · CR-01**, using the form described in step 3.
2. Select **1st AD**. In Scene review the decision pane holds **Pickup & wrap approvals**, showing the saved pickup request with **Approve pickup** and **Decline pickup**. Any other role sees "Waiting for the 1st AD. Select that demo role to review and answer this request."
3. Reload the page before you answer. The request comes back because the Strands run stopped at a real interrupt, and its session is saved on S3. Your answer resumes that run. See [Interrupt and resume across process death](strands-interrupt-resume.md#what-stops-and-what-resumes).
4. Press **Approve pickup** or **Decline pickup**. A pickup decision does not approve wrap: **Wrap** in the status strip still reads **Not approved**. Once the event bus accepts the approved pickup, the B-17 finding is labelled "Pickup approved · stays an exception until a take arrives" (`frontend/src/projection.ts:64-70`).
5. Press **Open guided demo**, then **Add take or release**. The form **Add evidence to this shoot day** opens.
6. Press **Try valid take**. This fills an editable take, T-900 on beat B-17, with camera report values that match it. Edit it if you like, then press **Save evidence & rerun checks**. The take appears under its beat as **Slate 42L/1**.
7. Press **Add take or release** again. Set **Record type** to **Release / licence record**, press **Fill synthetic example** (release REL-900 for BG-07, status executed) and save.
8. If you recorded a continuity decision in step 1, its card now reads "Earlier decision no longer applies: the evidence has changed. Review it again." The new take changed the takes record that the finding cites, so the old decision no longer matches the finding's seal.

**Refusal and correction.** The guided form has three example buttons. Nothing is submitted until you press **Save evidence & rerun checks** (`frontend/src/Intake.tsx:17-24, 45`).

| Button | What it loads | What saving must do |
|---|---|---|
| **Try valid take** | take T-900 on B-17, with a matching camera report | save the take and rerun the checks |
| **Try refused date** | release REL-EDITABLE for BG-07, with expiry date 2026-02-30, a date that does not exist | refuse with HTTP 400 and keep your entries. The package digest and delivery outcomes do not change. |
| **Try corrected date** | the same record identifier, with expiry date 2030-02-28 | save the release; edit it first if you want |

`frontend/tests/e2e/reliability.spec.ts:10-26` runs the refused and corrected pair on a fresh run of its own.

**Using a file instead of the form.**

- **Download input JSON** saves what the form holds as an ordinary `.json` file.
- **Load a JSON record file** reads such a file into the editable **Document JSON** box. Loading only previews it; nothing is saved until you press **Save evidence & rerun checks**.
- The document carries no session or run. Your browser's saved session decides which run it goes to.
- Size and shape limits are in [Bring your own record, Limits on a supplied record](bring-your-own-record.md#limits-on-a-supplied-record).
- Tick **No independent camera report supplied** to save a take with no report. The take saves, but its metadata finding stays missing, because the take's own values are never copied into the report (`reliability.spec.ts:31-37`).

### Step 3: Human wrap decision

1. Select **Script supervisor**. In **Discrepancy & sources**, choose **continuity · CR-01**. In the decision pane, fill **Your name in this demo**, set **Decision** to **Accept the exception**, write the **Reason for this exact evidence** and press **Record decision**.
2. Select **DIT / data manager** and do the same for **metadata · T-013**.
3. Nobody can accept a missing release as an exception. The policy gives no role that power (`src/lasttake/domain/policy.py`, `MAY_ACCEPT_EXCEPTION`). The release you saved in step 2 is what answers BG-07.
4. Select **1st AD** and press **Review wrap readiness** for a current gate result. When the gate reports eligible, **Request wrap approval** appears. Only the 1st AD sees it, and only while nothing is pending and wrap is not yet approved.
5. Press **Request wrap approval**. The run stops at a second Strands interrupt. The pane shows **Wrap approval requested** and **Your exact wrap decision**. Approving records the 1st AD's decision for the evidence in this saved request, and allows the turnover to be published; it does not publish it.
6. Open **Current package fingerprint · SHA-256** to read the package digest the request is bound to. It identifies the package revision the server reported. It is not a Merkle proof or an independent verification.
7. Reload. The saved request comes back. Press **Approve wrap** or **Decline wrap**. After an approval the pane shows **Wrap decision saved by the server**.
8. Eligibility never signs for the human. The wrap board keeps **Evidence gate** and **Human wrap decision** on separate lines. If the evidence changes while a wrap request is waiting, **Approve wrap** is disabled: decline the request, review the new evidence and ask for a fresh approval. The API refuses a stale approval with HTTP 409 (`reliability.spec.ts:62-63`).

### Step 4: Editorial handoff

1. Open **Handoff** and press **Publish approved turnover**. It is enabled only when the evidence is currently eligible and the 1st AD has approved wrap. The button posts to `/api/turnover`, which runs the `publish_turnover` tool directly (`handler.py:548-566`). Nothing in the repository subscribes to the `wrap.ready` event published at approval; this request is what builds the turnover.
2. **Turnover for this run** now shows the saved record. **Download turnover** downloads the stored manifest as JSON. The tested journey checks that the download matches the manifest on screen (`web/video/hero-journey.mjs:108-110`).
3. **Download handoff summary** and **Copy handoff summary** give a text version: the retained exceptions with their next actions, the beat-to-take map and the source digests. The browser builds this text from the manifest, and it is not separately sealed. **Find beat or take in turnover** searches the saved map.
4. Set **Receipt purpose** to **Wrap review** and press **Prepare receipt**. **Receipt ready for review** appears with the recorded approval and every open item. **Download receipt** saves the sealed JSON. **Copy evidence summary** and **Download evidence summary** give its text.
5. Open **Delivery status**. It lists deliveries that can be retried and any delivery the bus did not accept, each with the bus's answer. When every row was accepted, the panel stays closed behind its title (`frontend/src/DeliveryStatus.tsx:17-23`).

| Row says | What it means | What to do |
|---|---|---|
| accepted by the event bus | the bus API took the event. That is not proof anything downstream received it or finished. | nothing |
| no response recorded yet, or outcome unknown | nothing is established | do not resend. Refresh saved state, then give the run and receipt identifiers to the operator. |
| rejected by the event bus | the bus definitely refused it | as 1st AD, press **Retry rejected delivery**, which rechecks the current approval first |

6. Evidence added after a turnover leaves that turnover in place as a **Historical record**, with the reason it stopped being current, and **Download turnover** still works. The next-step panel then offers **Start a fresh shoot-day run** for a new turnover (`frontend/tests/e2e/hero.spec.ts:60-73`).

### When a fresh checkpoint is required

The current policy version is 1.1.0 (`src/lasttake/domain/policy.py:37`). If a run's saved findings were written under a different policy version, the page shows **Fresh checkpoint required** with the server's reason. The run's counts are then history, not current eligibility (`src/lasttake/app/workspace.py:119-126`).

1. If a request is pending, decline it first. The page says "Open the pending approval in Scene review and decline it before checking again."
2. Press **Run fresh checkpoint**.

Existing decisions and receipts stay in history. An old approval request with no saved evidence binding cannot approve new evidence. The tool answers "Refusing: this older request has no saved evidence binding. Request a fresh approval." (`src/lasttake/agents/tools.py:276-278, 342-344`).

## What the walk is tested against

The four steps are the source journey that test LT-HERO in [`frontend/tests/e2e/hero.spec.ts`](../frontend/tests/e2e/hero.spec.ts) runs on desktop and mobile. It drives the rendered controls using the scenes in [`web/video/hero-journey.mjs`](../web/video/hero-journey.mjs), the same script the owner-gated video capture uses. In source CI the browser talks to the offline Python HTTP server, `python -m lasttake.app.local_server`, started by `frontend/playwright.config.ts:9-12`. That server runs the real handler and real Strands sessions on local file adapters, with no AWS or model calls (`src/lasttake/app/local_server.py:1-4`).

| Part of the walk | Test |
|---|---|
| steps 1 to 4, a reload before each approval, and the historical turnover | `hero.spec.ts`, LT-HERO |
| the file download and load, refusals, a missing or foreign session, a duplicate record, a missing camera report | `hero.spec.ts`, LT-FILE |
| **Try refused date**, **Try corrected date** and a missing camera report | `reliability.spec.ts`, LT-RELIABLE-INTAKE |
| a stale wrap review refused with HTTP 409, then decline and a fresh request | `reliability.spec.ts`, LT-RELIABLE-WRAP |

The live acceptance job runs the same specs against the CloudFront URL. `.github/workflows/aws-uat.yml:32, 57-60` sets `LASTTAKE_UI_URL` and runs the `test:e2e` script (`frontend/package.json:12`). With that variable set, `frontend/playwright.config.ts:7-9` targets the live site and starts no local server.

Source CI is not deployment evidence. What the live URL serves depends on the frontend release it runs. [Current automated acceptance](release-and-acceptance.md#current-automated-acceptance) explains how to see which release that is and what automated acceptance covers.

Two statuses stay open:

- The final recording is `NOT_CONFIGURED`: the final demo video capture has not been set up, and it waits for the owner to verify it.
- Human UAT is `NOT_RUN`: no person has completed the testbook. Automated journeys never mark it as passed.

Session authority comes from the browser's saved session handle, never from an imported document. LT-FILE posts a valid document with no session, then with another session's handle, and both get HTTP 403 (`hero.spec.ts:104-110`).

## Pages, links and the testbook

The workspace is a React, TypeScript and Tailwind application in `frontend/`. It builds to `frontend/dist/` with hashed files under `/assets/`, and it reaches the backend only through same-origin `POST /api/*` JSON requests (`frontend/src/api.ts:9`).

Navigation is named after the task (`frontend/src/model.ts:6-7`, `App.tsx:31`):

| Page | Link | What it is for | In the navigation |
|---|---|---|---|
| Wrap status | `#overview`, or `#dashboard` | What still blocks wrap, and who owns it | yes |
| Scene review | `#scene`, or `#workspace` | Lined script, evidence and the human decision | yes |
| Records | `#records` | The supplied takes, beats, findings and releases | yes |
| Handoff | `#history` | Turnover, receipts and saved runs | yes |
| My actions | `#actions` | Decisions for the selected role | no. Saved links still open it, with Scene review highlighted. |
| Architecture | `#architecture` | What is deployed, tier by tier | yes |

How links behave (`frontend/src/model.ts:8-30`, `App.tsx:56-71`):

- Every link above keeps working from saved bookmarks and the testbook. An unknown page name falls back to Wrap status.
- The run, beat, finding, filter, record and search text travel in the hash, so browser back and reload restore the selection.
- The hash wins over a `?page=` or `?tab=` query. Before a run is chosen, the page name travels as `?page=` instead.

The navigation's **Proof of this release** block links **Current automated acceptance** (`/acceptance.html`) and **UAT testbook** (`/UAT.testbook.html`) (`App.tsx:87-91`).

The static UAT testbook is [`frontend/UAT.testbook.html`](../frontend/UAT.testbook.html) and [`frontend/UAT.testbook.json`](../frontend/UAT.testbook.json). `frontend/scripts/copy-testbook.mjs:2` copies both into the build, so the site serves them at `/UAT.testbook.html` and `/UAT.testbook.json`. Human signoff stays `NOT_RUN` until a person completes it. Its cases map to this page as follows:

| Testbook case | Section of this page |
|---|---|
| LT-TRUTH | [What the live workspace is and is not](#what-the-live-workspace-is-and-is-not) |
| LT-HERO, LT-FILE, LT01, LT02, LT03, LT-RELIABLE-INTAKE, LT-RELIABLE-WRAP, LT-RELIABLE-DELIVERY | [The walk, step by step](#the-walk-step-by-step) |
| LT-NAV | [Pages, links and the testbook](#pages-links-and-the-testbook) |
| LT-LANDING, UX-LT-10S | [Starting a run](#starting-a-run) |
| LT-DASH | [Wrap status](#wrap-status) |
| LT-SELECT, LT-COCKPIT, LT-UI, LT-ACCESS | [Scene review](#scene-review) |
| LT03-R1 | [What each chair is holding, and what leaves the building](#what-each-chair-is-holding-and-what-leaves-the-building) |
| LT-RECOVERY, LT-OFFLINE | [Sessions, timeouts and retries](#sessions-timeouts-and-retries) |
| LT-HISTORY | [Saved run history](#saved-run-history) |
| QA-LT-FRESH | [Releases and acceptance evidence](release-and-acceptance.md) |

## Starting a run

The first screen, headed "Know what still blocks wrap.", needs no upload and no account (`frontend/src/Landing.tsx:49-58`). For a returning browser, **Continue my saved shoot day** is the main action, and the page says continuing changes nothing and a fresh shoot day keeps the old one. **New shoot-day run**, at the top of every run page, starts another run of the same fictional scene. Older runs stay listed in Handoff.

**Demo role** offers five roles: Script supervisor, 1st AD, DIT / data manager, Production coordinator and Assistant editor (`frontend/src/model.ts:2`). The browser remembers your choice. It decides which controls the page offers; it is a demonstration, not a login.

Which role may decide which check comes from the authority table the gate enforces. The API sends that table with the scene (`src/lasttake/app/scene_view.py:127-137`).

The take and release forms save through the Python backend (`POST /api/ingest`), which reruns the affected checks.

**Open guided demo** shows **Walk through a fictional shoot day**, five short steps, and adds the labelled example buttons to the intake form. The panel states that these flows run no Bedrock inference, no footage or audio analysis, no email and no payment. It also says the AWS event-bus requests are real, and that bus acceptance does not establish downstream completion (`App.tsx:105`).

The API reports which interpreter it used, and the page shows it in two places:

- **How this demo checks evidence**, in the top bar, reads "Scripted planner · offline-lexical/1.0.0 · Real Strands approvals".
- **Run details & execution labels**, at the foot of each run page, lists the saved run, production and scene, Strands Agents SDK, the planner `offline-scripted/1.0.0`, the interpreter and state store the API reported, and the policy version (`App.tsx:97, 137`).

Real Strands interrupts govern the pickup and wrap approvals. [The orchestrator and its eight tools](how-it-works.md#the-orchestrator-and-its-eight-tools) covers what else the agent does.

## Wrap status

Wrap status metrics describe only the selected run of the single fictional scene. The page says so: "Current scene and selected run only. Saved runs repeat the same fictional corpus; they are not a production portfolio." (`frontend/src/Dashboard.tsx:52-54`).

| Metric | Where the value comes from | What it is not |
|---|---|---|
| Beats covered with evidence | the API's assessment of the required beats | a pass for unassessed beats. Before a checkpoint, or when the value is empty, it reads **Not assessed**. |
| Retained exceptions | distinct findings still on record, including reviewed and accepted exceptions | the eligibility causes under **Priority work**, which are counted separately |
| Beats missing release records | required beats whose outcome is no release record | a count of people, or of legal clearance |
| Supplied takes | the number of take records the API reports | an assessment of audio or footage quality |
| Wrap eligibility | the deterministic gate: **Eligible**, **Blocked** or **Not assessed** | a wrap approval |
| Human wrap approval | the 1st AD's decision: **Approved**, **Pending 1st AD**, **Needs new review** or **Not approved** | anything the gate can set |

Each metric links to the matching records (`frontend/src/projection.ts:40-51`).

The coverage and release numbers come from the rollup the API returns. Wrap eligibility and the causes come from the gate (`src/lasttake/app/workspace.py:181, 190-191`). The gate keeps its own tally of beats, which the turnover manifest carries as `counts`. It counts beats differently from the rollup, so it need not match these tiles (`src/lasttake/domain/policy.py:356-365`, `src/lasttake/domain/rollup.py`).

The rest of the page:

- **Why wrap is blocked**, in the next-step panel, shows up to three causes, each with what was observed, why it blocks wrap and the responsible role's next action.
- **Priority work** shows up to six causes, and any pickup or wrap request that is waiting.
- **Recent activity** shows the five newest events, with **View history** linking to Handoff (`frontend/src/WorkflowNext.tsx:62-65`, `Dashboard.tsx:70-123`).
- The beat coverage matrix gives every required beat one cell, coloured only by the checkpoint's finding for that beat. Before a checkpoint every cell is grey and reads "not assessed", because a take on file is not coverage (`frontend/src/ProductionCharts.tsx:25-35`).

No portfolio trends, savings or reshoot costs are inferred. **Advanced: observed session outcomes** gives counts for the loaded page of saved runs only, and states "Human-active time: unknown. Measured time or financial benefit: unknown." (`Dashboard.tsx:126-136`).

## Scene review

Scene review puts three panes side by side, with jump links named **Script & takes**, **Evidence** and **Decision** (`frontend/src/SceneView.tsx:34-62`):

| Pane | Heading | What it holds |
|---|---|---|
| Script & takes | Scene & script beats | the lined script, **Find a beat**, the **Show** filter, and each beat's takes with the take inspector |
| Evidence | Discrepancy & sources | the finding list, the selected finding's evidence, **Linked script beats** and **Inspect in Records** |
| Decision | Human decision | the Eligibility and Wrap status strip, the decision form, **Pickup & wrap approvals** and **Turnover & receipts** |

The status strip stays visible above the decision form while the form scrolls.

Choosing a finding links back to the beat it is about. A finding matches a beat when its requirement is that beat, the beat's continuity reference, one of the beat's takes, or a person or asset visible in one of those takes. It also matches when a take locator names one of those takes (`frontend/src/model.ts:31-35`). A finding with no requirement identifier never matches a beat that also has no continuity reference.

A shot-plan advisory with no linked beat keeps its source evidence and reads "Unmatched source: this finding has no linked beat in the current script." Its review label is **Advisory, not a wrap blocker**, because the gate skips findings with no requirement identifier (`frontend/src/projection.ts:56-59`).

Source locators and artifact digests appear exactly as the server reported them, under **Source records & digests**. Where a finding has no locator, the page says not to guess a page or take (`frontend/src/Inspector.tsx:22-26`).

The package SHA-256 under **Current package fingerprint · SHA-256** is a fingerprint, not a Merkle proof or an independent verification (`frontend/src/Actions.tsx:42`). A link to a beat or finding that does not match the current evidence shows a warning and offers no decision (`SceneView.tsx:35`).

## Records and Handoff

**Records** shows the scene as the API returns it. **Record type** switches between **Supplied takes**, **Script beats**, **Retained findings** and **Release subjects**, and **Search records** filters the list (`frontend/src/Records.tsx:6, 25`).

This endpoint does not return takes that are not linked to a script beat, or full release documents, and the inspector says so:

- The take list compares the API's take count with the linked takes it can show.
- A release subject shows only whether an executed status was supplied (`Records.tsx:26, 34`).
- An executed status in the ledger does not by itself establish expiry, scope or legal sufficiency. The rights findings carry any concern that was assessed (`Records.tsx:27, 34`).

The metadata check compares the take's media identifier, lens and camera roll with the camera report (`src/lasttake/checks/metadata.py:73-86`). No check reads the sound report and no audio is analysed. The sound roll in the take inspector is shown as supplied, not checked.

**Handoff** holds five panels, in this order (`frontend/src/History.tsx:39-54`):

1. **Turnover for this run**
2. **Delivery status**
3. **Receipt for** the selected role
4. **Saved shoot-day runs**
5. **Recorded events**

A saved turnover survives later evidence changes. It stays downloadable as a **Historical record**, with the reason it is out of date, and it cannot approve the changed package (`frontend/src/Turnover.tsx:50-56, 100-102`).

Three things stay separate: eligibility, a pending wrap request whose evidence has not changed, and the 1st AD's approval. **Approve wrap** is offered only while the first two hold. Publishing needs the first and the third (`Actions.tsx:37`, `Turnover.tsx:108`).

The manifest holds the beat-to-take map, the technical identity report, source digests, human decisions, retained exceptions and the model identifier recorded on each finding. **Inspect saved manifest** shows it as JSON (`src/lasttake/domain/turnover.py`).

**Recorded events** lists the run's stored events, twenty to a page and newest first, with **Newer events** and **Older events**; consecutive events of one type share a row. On AWS every run event reaches the event bus, including one `finding.recorded` per finding (`src/lasttake/adapters/aws/infrastructure.py:258-307`). A stored event is an attempted publication, not a delivery receipt; the bus's answers are under **Delivery status** (`History.tsx:49-53`, `DeliveryStatus.tsx:18`).

## What each chair is holding, and what leaves the building

A script supervisor on the floor and a 1st AD at the truck each need three answers: what do I do, who owns it, and where did it come from. The React workspace spreads those answers across its pages instead of putting them in one summary:

| Where | What it shows |
|---|---|
| Wrap status, **Why wrap is blocked** | up to three blocking causes, each with the observation, why it blocks wrap and the responsible role's next action |
| Wrap status, **Priority work** | up to six causes with their role and location, plus any waiting request |
| My actions (`#actions`) | findings **Assigned to** the selected role, and **Waiting on other roles** with each owner's next action |
| Handoff, **Receipt for** the selected role | the number of open items across all roles, and the ones assigned to the selected role |

Which items are yours is read from the same authority table the deterministic gate enforces. The API sends it with the scene: `src/lasttake/app/scene_view.py:127-137` projects `policy.AUTHORITY` and `policy.MAY_ACCEPT_EXCEPTION`. Moving a check to a different role therefore moves these lists without anyone editing the page.

A single summary ordered by where the cost falls exists only in the older static page, [`src/lasttake/app/static/index.html`](../src/lasttake/app/static/index.html): the `paintMine` panel at lines 938-990, ordered by `COST_ORDER` at line 469. The handler serves that page only at `/` on the HTTP API endpoint; the CloudFront URL serves the React workspace (`handler.py:687`, `infra/frontend_stack.py:15-23`).

The sealed receipt is the packet meant to be read away from the page, so it carries its own context (`src/lasttake/domain/receipt.py:141-226`):

- the run, scene, production and script revision
- the package digest and the policy version
- its own SHA-256, as `record_sha256`
- every still-open item, with its responsible role, next action, what was observed and the source digests it was read from
- any human decision on an item, and a flag when an earlier decision no longer applies
- delivery outcomes, recovery status, and the model identifiers serialized on each finding

**Copy evidence summary** copies the receipt's text, ready to paste into a production email. **Download receipt** saves the sealed JSON. If evidence or decisions change after you prepare a receipt, the page marks it historical and asks for a new one; earlier downloads stay as they were (`frontend/src/History.tsx:41-44`).

An accepted exception travels. It stays under `still_open` with its decision beside it (`receipt.py:16-19, 124-126`). Somebody signed for it, but that does not make it fixed, and a receipt that quietly dropped it is how an approved problem reaches the edit as a surprise. The turnover keeps it too, under **What editorial still needs to know**.

The packet also states what it does **not** say: it is not a statement that the scene is creatively complete, cleared in law, or safe to wrap, and absent evidence in it is a gap rather than a pass.

Its other stated limits:

- An item under `still_open` is open. An accepted exception is a known problem somebody signed for, not a resolved one.
- The counts describe only the records that were read. Anything nobody wrote down cannot appear.
- SHA-256 identifies bytes. It does not prove where they came from, who a person is, or that they are true.
- Bus acceptance is not downstream delivery or completion, and a stored event copy proves only storage.

All of these appear under **Receipt limits & sealed record** (`receipt.py:39-55`).

## Sessions, timeouts and retries

The browser stores only two values: the session handle (`lasttake.session`) and the demo role preference (`lasttake.role`). Records and decisions are stored by the backend (`frontend/src/useWorkspace.ts:43-45`, `App.tsx:47`).

The server creates a random 64-character session handle and stores only its hash. The handle is a bearer capability, not an authenticated identity: anyone holding it can open that session's runs, so keep it private (`src/lasttake/app/workspace.py:3-4, 18-29`). Saved runs belong to that session. Choosing a role is a demonstration, not a staff login.

With browser storage blocked, the tab keeps working from memory and shows "Browser storage is unavailable. You can use this tab, but reloading may start a separate session. Saved records remain on the server." (`frontend/src/storage.ts:1-13`).

| Layer | Time limit | Source |
|---|---|---|
| Browser request | aborts after 35 seconds | `frontend/src/api.ts:7` |
| CloudFront, API origin | read timeout of 30 seconds | `infra/frontend_stack.py:126` |
| API Gateway integration | 30 seconds | `infra/stack.yaml:287` |
| Lambda function | 120 seconds | `infra/stack.yaml:237` |

On the live URL, CloudFront and API Gateway give up on a request at 30 seconds, before the browser's own 35-second limit. The browser sends each request once and never retries it automatically, writes included (`api.ts:5-19`).

A timed-out write may still have been saved, and the page says so: "The request timed out. The server may have saved it. Refresh saved state before retrying a write." (`api.ts:16`). Refresh before you retry any write whose result is uncertain.

When a request fails, the page shows **We couldn't complete that request** with one of two instructions (`App.tsx:108`, `useWorkspace.ts:38`):

| Result | What the page says | What to do |
|---|---|---|
| HTTP 400, a known validation refusal | "The server refused the invalid request. Correct the supplied fields and submit again; your entries are kept." | correct the fields and submit again. No refresh is needed. |
| anything else: a stale or conflicting write, a network failure, an unreadable response, a server failure or a timeout | "Refresh saved state before retrying a write. Your form entries are kept. Displayed evidence may be out of date." | press **Retry loading saved state** or **Refresh saved state** before any other write |

When no run is loaded, the error also offers **Start a separate session** and **Back to the start**.

While a refresh is needed, **Save evidence & rerun checks** is disabled and the form says "Refresh saved state before saving more evidence. You can keep editing or close this form." **Close form** stays available (`frontend/src/Intake.tsx:33, 69-71`). Intake limits, and how the API answers when saved state cannot be read, are in [Bring your own record, Limits on a supplied record](bring-your-own-record.md#limits-on-a-supplied-record).

## Saved run history

**Saved shoot-day runs** in Handoff lists only the runs owned by this browser's session. It loads 10 registrations per page, and the API accepts at most 20 (`src/lasttake/domain/history.py:7-8`, `src/lasttake/app/workspace.py:26`). The server reads that page of registrations before it rebuilds any run in it (`workspace.py:38-51`).

**On Aurora DSQL.** A parameterized keyset query filters the audit table to the owning session. It orders runs newest first, by record time and then entry id, and fetches at most one row more than the page size; that extra row shows whether older runs exist (`src/lasttake/adapters/aws/dsql.py:356-371`). The live stack uses DSQL: the footer's **State store reported by API** reads `aurora-dsql`, and `.github/workflows/deploy.yml:223` fails a backend deploy unless `/healthz` reports it.

**On the S3 or local-file fallback:**

- Each page reads at most a 64 KiB (65,536-byte) window of the existing audit array, as a byte range tied to that file version, and never rewrites the file (`history.py:9, 61-112`, `src/lasttake/adapters/aws/infrastructure.py:194-225`).
- If the file changed between pages, the API answers HTTP 409 with "Saved history changed." and asks for a list refresh (`history.py:57`, `handler.py:757-758`).
- An unreadable or oversized historical record is refused, not skipped. The API answers "Saved state is temporarily unavailable." (`history.py:69-111`, `handler.py:671-676, 759-760`).

A page cursor is bound to its session, so a cursor from another session is refused (`history.py:26-39`).

- **Load older runs** replaces the page shown.
- **Refresh newest runs** starts again from the newest.
- The status line counts the runs on this page and says when older runs are available. If loading fails, the current page stays and the error says to refresh newest runs (`frontend/src/useWorkspace.ts:92-104`, `History.tsx:46-47`).

Counts describe the loaded page, not the total history. Saved handles, direct links to owned runs, and earlier records stay valid. No registration quota is imposed. The database's physical scan and sort cost is not measured, and is not claimed to be bounded by the row limit.
