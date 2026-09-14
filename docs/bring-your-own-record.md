# Bring your own record

This page is for someone putting their own take or release record into LastTake, either through `POST /api/ingest` or through the **Add take or release** form in Scene review. It covers the document shape, what gets refused, the limits, which checks rerun and why, and how a human decision stops applying when its evidence changes. The runnable `curl` example and the HTTP 403 session rules are in [README, Bring your own record](../README.md#bring-your-own-record), where `tests/test_workspace.py` runs that example against the real handler, so they are not repeated here.

## Why intake takes a document

The legacy single page the Lambda still serves at `/` on the HTTP API endpoint has two controls that write a fixed take, T-041, and a fixed release, REL-007, through `POST /api/late-take` and `POST /api/resolve-rights`. Each appears as a guided step and as an inbox button (`src/lasttake/app/static/index.html:511-524`, `:1304-1329`, `src/lasttake/app/handler.py:343-361`, `:400-409`, `:687`). They show which checks rerun, but they write the same two records every time, so nobody can put their own scene through them, which makes them a fixture with a play button. The React workspace has no such control. Intake takes a document instead (`frontend/src/App.tsx:130`).

A request names the run, the `kind` of record and the `document`. The workspace form builds the same document from its fields (`frontend/src/model.ts:41-46`) and sends it to the same route. An accepted document goes through four steps:

1. The handler checks the `run_id` format, then session ownership, then the document shape, all before the run is built (`src/lasttake/app/handler.py:733-750`).
2. The document becomes a package amendment, replayed in memory onto the base scene package. On AWS the base package is the corpus bundled with the Lambda, and amendments are kept in the S3 artifact store (`src/lasttake/app/handler.py:72-115`, `src/lasttake/app/ingest.py:46-87`).
3. The checks listed for the document's event rerun against the amended package. [What reruns, and why](#what-reruns-and-why) explains which ones.
4. Only after that is the amendment written, the new findings stored and the event published (`src/lasttake/app/ingest.py:312-330`).

An amendment is written once, under its own key `amendments/<run>/<NNNN>.json`, and is never updated or deleted (`src/lasttake/app/ingest.py:39-66`). Which run it joins, and whether you may write to that run, come from the `run_id` and the session handle in the request, never from the document. In the browser, that handle is the one the workspace saved (`frontend/src/useWorkspace.ts:84`). A document that carries its own `run_id` or `session_id` is refused, because neither is a field of either shape.

## Document shape and refusals

`kind` is `take` or `rights_record`. Each kind has a fixed set of fields (`src/lasttake/app/ingest.py:96-112`):

| `kind` | Required fields | Optional fields |
| --- | --- | --- |
| `take` | `take_id`, `shot_id`, `beat_ids`, `slate`, `camera_roll`, `sound_roll`, `timecode_in`, `timecode_out`, `lens_mm`, `media_id`, `preferred`, `usable` | `note`, `visible_people`, `visible_assets`, `captured_at`, `camera_report_row` |
| `rights_record` | `record_id`, `subject_id`, `subject_kind`, `document_type`, `scope`, `territory`, `status` | `expires_on` |

Text fields are strings. `lens_mm` is a whole number, and `true` is not accepted as one. `preferred` and `usable` are booleans. `beat_ids`, `visible_people` and `visible_assets` are lists of identifier strings (`src/lasttake/app/ingest.py:140-148`).

`camera_report_row` is the camera report's own record of this take, kept apart from the take's values so the metadata check can compare the two. It holds exactly `take_id`, `media_id`, `lens_mm` and `camera_roll`, and its `take_id` must be the take's own (`src/lasttake/app/ingest.py:232-251`). When no report exists, leave it out or send `null`. In the form that is the **No independent camera report supplied** box. Otherwise the report's media identifier, lens and camera roll come from their own fields, never from the take's (`frontend/src/model.ts:45`).

A refusal is HTTP 400, writes nothing, and says what is wrong instead of failing quietly:

| Refused when | The response includes | Source in `src/lasttake/app/ingest.py` |
| --- | --- | --- |
| `kind` is not `take` or `rights_record` | the error and `accepted_kinds` | 163-167 |
| `document` is not a JSON object | the error and the `expected` shape | 168-169 |
| a required field is missing, or a field is not in the shape | `missing`, `unexpected` and the `expected` shape | 170-183 |
| `take_id`, `record_id`, `subject_id`, `shot_id` or a list entry is not 1 to 128 letters, digits, `.`, `:`, `_` or `-`, starting with a letter or digit | which field is wrong | 124-133, 184-188, 210-213 |
| a field has the wrong type, such as `"lens_mm": "fifty"` or `"beat_ids": "B-17"`, or a text field is longer than 2,000 characters | the field, and the type or length it must have | 190-209 |
| a list repeats an entry or has more than 64 entries | the field | 205-215 |
| `status` is not `executed`, `pending`, `expired` or `withdrawn` | the allowed values and the value given | 158, 217-221 |
| `expires_on` is neither `null` nor a real date written `YYYY-MM-DD` | the error | 223-230 |
| `camera_report_row` names another take, does not hold exactly its four fields, or holds a value of the wrong type or length | for another take, the `given` and `expected` take ids | 232-251 |
| the `take_id` or `record_id` is already in this scene package | the error | 272-283 |

`tests/test_handler.py:568-586` checks the `accepted_kinds`, `missing`, `unexpected` and `expected` fields. `tests/test_handler.py:757-846` covers wrong types, over-long text, a camera report row about another take, a reused identifier and an invented rights status.

A refused document leaves the run as it was. `tests/test_reliable_workflows.py:225-243` sends impossible expiry dates such as `2026-02-30`, checks that the package digest, findings, decisions, audit entries, amendments and events are unchanged, and then accepts the corrected record under the same `record_id`.

The form carries editable examples, so a visitor edits a record rather than reading a schema (`frontend/src/Intake.tsx:36-70`):

- **Fill synthetic example** fills the form for the chosen record type. It appears only after **Open guided demo**.
- **Try valid take**, **Try refused date** and **Try corrected date** load three flows, also only in the guided demo. The refused date must come back refused without saving, and the corrected release reuses the same identifier.
- **Load a JSON record file** puts a file into an editable preview, and **Download input JSON** saves what you entered as a file.
- Nothing is sent until you press **Save evidence & rerun checks**.

The walk that uses these flows is in [Using the LastTake workspace](workspace-guide.md#the-walk-step-by-step).

## Limits on a supplied record

| Limit | Value | Enforced in | Tested in |
| --- | --- | --- | --- |
| Entries in each of `beat_ids`, `visible_people` and `visible_assets` | at most 64, no repeats | `src/lasttake/app/ingest.py:153`, `:205-215` | `tests/test_security_boundaries.py:242-289` |
| Length of any text field | 2,000 characters | `src/lasttake/app/ingest.py:152`, `:203-204` | `tests/test_handler.py:757-788` |
| HTTP request body | 128,000 decoded UTF-8 bytes, base64 gateway bodies included; a larger body gets HTTP 413 | `src/lasttake/app/request_body.py:8`, `:26-34` | `tests/test_security_boundaries.py:291-336` |
| File loaded in the browser | one `.json` record of at most 64 KiB | `frontend/src/evidenceFile.ts:3-12` | `frontend/tests/hero.test.tsx:44` |
| Amendments per run | 200 | `src/lasttake/app/ingest.py:43`, `:50-66` | no test |

- The 64 KiB limit is a browser check on the file picker. The picker also refuses a file whose name does not end in `.json`, and it does not read media, PDFs, images or CSV. A direct API call is bounded by the 128,000-byte request limit instead.
- Repeated or oversized lists are refused before any write. The tests compare every stored byte and the package digest before and after (`tests/test_security_boundaries.py:242-279`).
- An unknown beat identifier is not silently removed: it is accepted and stored as supplied (`tests/test_security_boundaries.py:281-289`).
- Some older amendments predate the rule against repeats. Their repeated links are collapsed only in the scene projection the workspace reads; the stored amendment and its digest do not change (`src/lasttake/app/scene_view.py:38-43`, `tests/test_security_boundaries.py:338`).
- A 201st amendment is not written. The code raises an error first, and the HTTP handler returns it as a generic HTTP 500 (`src/lasttake/app/ingest.py:60-66`, `src/lasttake/app/handler.py:786-797`).
- When a storage read gives an uncertain answer, the API returns HTTP 503 with "Saved state is temporarily unavailable." It never falls back to treating the run as unowned, or to an empty saved state (`src/lasttake/app/handler.py:671-678`, `tests/test_security_boundaries.py:90-176`).
- A supplied record does not expire. Amendments sit under the data bucket's `artifacts/` prefix, and its lifecycle rules expire only `runs/` and `sessions/` (`infra/stack.yaml:66-78`). Use fictional records only, as the form asks (`frontend/src/Intake.tsx:34`).

## What reruns, and why

What happens next is the part worth watching. The document becomes a package amendment, the amended package produces new digests, and checks run again.

Which checks rerun is looked up by event type in the `AFFECTED_CHECKS` table in `src/lasttake/domain/events.py:129-135`. `perform_ingest` reads it through `affected_by` (`src/lasttake/app/ingest.py:318-327`). The table matches what each check reads:

| You supply | Event | Artifact whose digest moves | Checks that rerun |
| --- | --- | --- | --- |
| a take | `take.captured` | `takes` | coverage, continuity, metadata and rights, because all four cite `takes` |
| a release or licence record | `rights.record.updated` | `rights_ledger` | rights only, because no other check cites `rights_ledger` |

| Check | Artifacts it cites | Source |
| --- | --- | --- |
| coverage | `script_revision`, `takes`, `shot_plan` | `src/lasttake/checks/coverage.py:39-50` |
| continuity | `continuity_refs`, `script_notes`, `takes` | `src/lasttake/checks/continuity.py:47-57` |
| metadata | `takes`, `camera_report` | `src/lasttake/checks/metadata.py:38-43` |
| rights | `rights_ledger`, `takes` | `src/lasttake/checks/rights.py:50-55` |

`tests/test_handler.py:588-608` and `tests/test_handler.py:644-667` assert those two check lists over HTTP.

The gate makes its own, separate judgement from digests. It discards any stored finding that cites a source whose digest has changed, and it keeps a finding whose cited sources did not move, even though the package revision is new (`src/lasttake/domain/policy.py:197-248`, `tests/test_gate.py:118-139`). So if the table ever left out a check that reads the moved artifact, that check's old findings would be discarded, and the eligibility result would show a missing current result for it, not a pass.

The rerun happens inside the API route, without the orchestrator, and the event does not start it. The checks run first, then the amendment and the findings are saved, and `take.captured` or `rights.record.updated` is published last, as a record of what happened (`src/lasttake/app/ingest.py:314-330`). The only EventBridge resource in `infra/stack.yaml` is the bus itself (`infra/stack.yaml:130-136`); no rule in this repository routes the event anywhere.

The response carries the run's new state plus `affected_checks`, `ingested` (the kind and the run's amendment count), `withdrawn_decisions` and `delivery` (`src/lasttake/app/ingest.py:349-360`). Its `message` says the checks reran "because that is which artifact digests moved", but the list itself comes from the table above. If the bus does not accept the event, the message adds that the evidence is saved and asks you to review delivery status before retrying.

Two other routes do not use the table to choose checks. `POST /api/late-take` always reruns all four checks, and `POST /api/resolve-rights` always reruns rights only (`src/lasttake/app/handler.py:376-380`, `:423`). Both still fill the response's `affected_checks` from the table (`src/lasttake/app/handler.py:385`, `:429`). The CLI commands `lasttake late-take` and `lasttake resolve rights` choose the same checks in code, all four and rights only (`src/lasttake/cli.py:292-297`, `:352-354`).

## An approval does not survive the evidence it was about

A human decision used to bind to a finding id, and finding ids are deterministic: `<run_id>:con:CR-01` is the same string before and after a rerun. So a script supervisor could accept the mug continuity conflict as intentional, a take could arrive that changed the continuity evidence completely, the finding would be recomputed under the same id, and the old acceptance would still close it. Nobody would have looked at the new facts, and nothing would say so.

A decision now carries the digest of the finding it was taken about:

- Every new decision stores the finding's seal in its own `finding_sha256` field. The seal is `record_sha256`, a SHA-256 over the finding record, including the digest of each source the finding cites (`src/lasttake/domain/findings.py:134-156`). Both `POST /api/decide` (`src/lasttake/app/handler.py:465-476`) and the CLI command `lasttake resolve decision` (`src/lasttake/cli.py:374-382`) set it, so neither creates an unbound decision. The decision record itself is not sealed.
- On a session-owned run, `POST /api/decide` must also send the `finding_sha256` the person reviewed, or it is refused with HTTP 400 (`src/lasttake/app/workspace.py:166-167`). If the finding has changed since that review, the request is refused with HTTP 409 (`src/lasttake/app/handler.py:447-448`).
- The gate counts a decision only when its `finding_sha256` equals the finding's current seal (`src/lasttake/domain/policy.py:399-401`). It picks the latest decision from a role with authority before checking the digest, so a stale later review cannot bring back an earlier acceptance (`src/lasttake/domain/policy.py:388-396`). `tests/test_gate.py:221-252` reseals a changed finding under the same id and shows the acceptance no longer resolves it.

When an amendment moves the evidence a finding cites, the rerun writes that finding again with a different seal, and a decision bound to the old seal stops applying. The ingest response lists that decision in `withdrawn_decisions`, with its `decision_id`, `finding_id`, `actor`, `role` and a `why` (`src/lasttake/app/ingest.py:332-352`). A decision is listed when it carries a `finding_sha256`, its finding is still on file, and that finding's current seal differs from the digest the decision was bound to (`src/lasttake/app/ingest.py:343-346`). A listed decision stays in the run's history; it no longer applies (`tests/test_handler.py:610-641`, `tests/test_handler.py:848-878`). The comparison is with the decision, not with the seal as it stood before this ingest, so a decision that had already stopped applying is listed again by every later ingest, a release included. A release reruns only the rights check, so a decision on a coverage, continuity or metadata finding that was still applying keeps applying after one, even though an already withdrawn decision is listed again.

Decisions recorded before the digest field existed stay in history, but they no longer authorize a current finding (`tests/test_gate.py:255-270`). They carry no `finding_sha256`, so `withdrawn_decisions` never lists them (`src/lasttake/app/ingest.py:344`). The workspace shows the same note beside those and beside withdrawn decisions: "Earlier decision no longer applies: the evidence has changed. Review it again." (`frontend/src/Actions.tsx:13`, `frontend/src/model.ts:36-39`).

A pending wrap approval follows the same idea. If the package or the review digest changed after the 1st AD's wrap request, approving it is refused with HTTP 409, and the request has to be declined and asked for again after review (`src/lasttake/app/workspace.py:83-94`, `:170-172`, `tests/test_workspace.py:122`).

This binding is enforced by the same deterministic gate described in [README, The rule the whole product turns on](../README.md#the-rule-the-whole-product-turns-on).
