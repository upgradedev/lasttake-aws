"""CI-only functional tests with inert JUnit and an in-memory frontend bucket."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("proof", Path(__file__).with_name("frontend_acceptance.py"))
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)
FRONTEND = "a" * 40
BACKEND = "b" * 40  # Independently observed backend, deliberately not frontend parity.
NOW = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)
ENV = {"EXPECTED_RELEASE": FRONTEND, "PREFLIGHT": "success", "JOURNEYS": "success", "POSTFLIGHT": "success",
       "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": FRONTEND,
       "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": proof.REPO}
JUNIT = b'''<testsuites tests="2" failures="0" errors="0" skipped="0">
<testsuite name="journeys.spec.ts" hostname="desktop" tests="1" failures="0" errors="0" skipped="0">
<testcase classname="journeys.spec.ts" name="refusal and recovery"><system-out>PRIVATE SCENARIO TEXT NOT FOR PUBLICATION</system-out></testcase></testsuite>
<testsuite name="journeys.spec.ts" hostname="mobile" tests="1" failures="0" errors="0" skipped="0">
<testcase classname="journeys.spec.ts" name="refusal and recovery"/></testsuite></testsuites>'''


def observation(at=NOW):
    return {"frontend_commit": FRONTEND, "backend_commit": BACKEND, "observed_at": proof.stamp(at)}


def receipt():
    with patch.object(proof, "utcnow", return_value=NOW):
        return proof.build(JUNIT, observation(NOW - timedelta(minutes=9)), observation(), ENV)


class ReceiptContract(unittest.TestCase):
    def test_real_case_nodes_produce_only_sanitized_totals_and_exact_observed_pair(self):
        result = receipt()
        self.assertEqual(result["totals"], {"tests": 2, "passed": 2, "failed": 0, "skipped": 0})
        self.assertEqual(result["frontend_commit"], FRONTEND)
        self.assertEqual(result["backend_commit"], BACKEND)
        self.assertEqual(result["run_attempt"], "2")
        self.assertEqual(result["human_uat"], "NOT_RUN")
        self.assertEqual(result["workflow_status"], "NOT_ASSERTED")
        self.assertNotIn(b"PRIVATE SCENARIO", proof.encode(result))
        self.assertNotIn(b"refusal and recovery", proof.encode(result))

    def test_failed_skipped_or_missing_stage_never_creates_receipt(self):
        for stage in ("PREFLIGHT", "JOURNEYS", "POSTFLIGHT"):
            for status in ("failure", "skipped", "cancelled", "", None):
                with self.subTest(stage=stage, status=status), self.assertRaises(ValueError):
                    proof.build(JUNIT, observation(), observation(), {**ENV, stage: status})

    def test_junit_empty_malformed_or_false_counts_refused(self):
        for bad in (b"", b"<testsuites/>", b"<html>success</html>", b"<!DOCTYPE x>" + JUNIT,
                    JUNIT.replace(b'tests="2"', b'tests="3"'), JUNIT.replace(b'tests="1"', b'tests="2"'),
                    JUNIT.replace(b'failures="0"', b'failures="1"'), JUNIT.replace(b'skipped="0"', b'skipped="1"'),
                    JUNIT.replace(b'<system-out>', b'<failure>').replace(b'</system-out>', b'</failure>'),
                    JUNIT.replace(b'<system-out>', b'<skipped>').replace(b'</system-out>', b'</skipped>'),
                    JUNIT.replace(b' hostname="mobile"', b' hostname="desktop"'),
                    JUNIT.replace(b' name="refusal and recovery"', b''), JUNIT.replace(b'errors="0"', b'errors="1"')):
            with self.subTest(input=bad[:90]), self.assertRaises((ValueError, proof.ET.ParseError)):
                proof.junit_totals(bad)

    def test_changed_pair_refused(self):
        for key in ("frontend_commit", "backend_commit"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                proof.build(JUNIT, observation(), {**observation(), key: "c" * 40}, ENV)

    def test_unavailable_or_unhealthy_backend_never_invents_a_revision(self):
        for health in ({}, {"ok": False, "commit": BACKEND}, {"ok": True, "commit": "unknown"},
                       {"ok": True, "commit": BACKEND, "run_state_store": "s3"}):
            with self.subTest(health=health), self.assertRaises(ValueError):
                proof.identity(FRONTEND, lambda path: {"commit": FRONTEND} if path == "release.json" else health)

    def test_main_dispatch_must_match_checkout_and_current_main(self):
        def command(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout=FRONTEND)
        proof.require_current_source(FRONTEND, ENV, command)
        for extra in ({"GITHUB_REF": "refs/heads/codex/proof"}, {"GITHUB_SHA": "c" * 40},
                      {"GITHUB_REPOSITORY": "upgradedev/another"}):
            with self.assertRaises(ValueError):
                proof.require_current_source(FRONTEND, {**ENV, **extra}, command)
        for stale_command in ("gh", "git"):
            def stale(args, **kwargs):
                return subprocess.CompletedProcess(args, 0, stdout=("d" * 40 if args[0] == stale_command else FRONTEND))
            with self.assertRaisesRegex(ValueError, "stale"):
                proof.require_current_source(FRONTEND, ENV, stale)

    def test_strict_schema_rejects_raw_data_or_broadened_claims(self):
        for extra in ({"raw_scenarios": ["private"]}, {"human_uat": "PASS"}, {"workflow_status": "success"},
                      {"schema_version": True}, {"backend_commit": "unavailable"}, {"application": "archon"},
                      {"run_url": "https://example.com/token"}, {"receipt_path": "/acceptance/runs/../../secret"},
                      {"totals": {"tests": 2, "passed": 2, "failed": 0, "skipped": 1}},
                      {"totals": {"tests": True, "passed": True, "failed": 0, "skipped": 0}},
                      {"totals": {"tests": 0, "passed": 0, "failed": 0, "skipped": 0}},
                      {"preflight_at": "2026-09-10T07:00:00Z"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                proof.validate({**receipt(), **extra})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            proof.read_json('{"run_id":"1","run_id":"2"}')

    def test_old_or_future_proof_is_not_current(self):
        for now in (NOW + timedelta(hours=25), NOW - timedelta(minutes=6)):
            with self.assertRaisesRegex(ValueError, "stale or future"):
                proof.validate(receipt(), now=now, fresh=True)


class Bucket:
    """Emulates conditional S3 requests, never authorizes unconditional writes."""
    def __init__(self):
        self.objects = {"release.json": proof.encode({"commit": FRONTEND})}
        self.calls = []
        self.frontend, self.backend = FRONTEND, BACKEND
        self.html_commit = FRONTEND
        self.before_put = None
        self.output_bucket = "lasttake-web-123456789012-eu-west-1"

    def public(self, path):
        if path == "":
            return f'<html><head><meta name="application-commit" content="{self.html_commit}"></head></html>'
        if path == "release.json":
            return {"commit": self.frontend}
        return {"commit": self.backend, "ok": True, "run_state_store": "aurora-dsql"}

    @staticmethod
    def etag(data):
        return '"' + proof.hashlib.sha256(data).hexdigest() + '"'

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ("cloudformation", "describe-stacks"):
            values = {"FrontendBucket": self.output_bucket, "FrontendUrl": proof.URL, "DistributionId": "EXAMPLE"}
            return {"Stacks": [{"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in values.items()]}]}
        if args[0] == "cloudfront":
            return {}
        key = args[args.index("--key") + 1]
        if args[1] == "get-object":
            if key not in self.objects:
                raise subprocess.CalledProcessError(1, args, stderr="(NoSuchKey)")
            Path(args[-1]).write_bytes(self.objects[key])
            return {"ETag": self.etag(self.objects[key])}
        if self.before_put:
            self.before_put(key)
        if "--if-none-match" in args:
            if key in self.objects:
                raise subprocess.CalledProcessError(1, args, stderr="(PreconditionFailed)")
        elif "--if-match" in args:
            if key not in self.objects or self.etag(self.objects[key]) != args[args.index("--if-match") + 1]:
                raise subprocess.CalledProcessError(1, args, stderr="(PreconditionFailed)")
        else:
            raise AssertionError("unconditional publication")
        self.objects[key] = Path(args[args.index("--body") + 1]).read_bytes()
        return {}


class PublicationContract(unittest.TestCase):
    def setUp(self):
        self.bucket = Bucket()
        self.record = receipt()
        self.data = proof.encode(self.record)

    def publish(self, **kwargs):
        return proof.publish(kwargs.pop("data", self.data), kwargs.pop("expected", FRONTEND),
                             kwargs.pop("run", "12345"), kwargs.pop("attempt", "2"),
                             command=self.bucket.command, request=self.bucket.public, now=lambda: NOW, **kwargs)

    def test_first_publish_and_identical_retry_keep_history_and_do_not_claim_workflow_success(self):
        result = self.publish()
        self.assertEqual(result["workflow_status"], "NOT_ASSERTED")
        immutable = self.record["receipt_path"].lstrip("/")
        self.assertEqual(self.bucket.objects[immutable], self.data)
        self.assertEqual(self.bucket.objects["acceptance.json"], self.data)
        self.publish()
        latest_puts = [call for call in self.bucket.calls if call[:2] == ("s3api", "put-object") and call[call.index("--key") + 1] == "acceptance.json"]
        self.assertEqual(len(latest_puts), 1)
        self.assertTrue(all("no-store,max-age=0" in call for call in latest_puts))

    def test_immutable_collision_is_refused_without_latest(self):
        self.bucket.objects[self.record["receipt_path"].lstrip("/")] = b"historic bytes"
        with self.assertRaisesRegex(ValueError, "collision"):
            self.publish()
        self.assertNotIn("acceptance.json", self.bucket.objects)
        self.assertIn(b"historic bytes", self.bucket.objects.values())

    def test_wrong_artifact_run_or_sha_refused_before_cloud_access(self):
        for kwargs in ({"expected": "c" * 40}, {"run": "54321"}, {"attempt": "1"},
                       {"data": b'{}'}, {"data": self.data + b' '}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.publish(**kwargs)
        self.assertEqual(self.bucket.calls, [])

    def test_wrong_bucket_refused(self):
        self.bucket.output_bucket = "archon-web-123456789012-eu-west-1"
        with self.assertRaisesRegex(ValueError, "target"):
            self.publish()
        self.assertNotIn("acceptance.json", self.bucket.objects)

    def test_public_frontend_backend_or_s3_manifest_change_refuses_publication(self):
        for kind in ("frontend", "backend", "origin", "html_commit"):
            self.bucket = Bucket()
            if kind == "origin":
                self.bucket.objects["release.json"] = proof.encode({"commit": "c" * 40})
            else:
                setattr(self.bucket, kind, "c" * 40)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.publish()
            self.assertNotIn("acceptance.json", self.bucket.objects)

    def test_change_after_immutable_write_preserves_history_but_refuses_latest(self):
        def change(key):
            if key.startswith("acceptance/runs/"):
                self.bucket.backend = "c" * 40
        self.bucket.before_put = change
        with self.assertRaisesRegex(ValueError, "backend changed"):
            self.publish()
        self.assertIn(self.record["receipt_path"].lstrip("/"), self.bucket.objects)
        self.assertNotIn("acceptance.json", self.bucket.objects)

    def test_newer_or_malformed_latest_is_never_overwritten(self):
        prior = {**self.record, "observed_at": proof.stamp(NOW + timedelta(minutes=1))}
        for existing in (proof.encode(prior), b'{}'):
            self.bucket = Bucket()
            self.bucket.objects["acceptance.json"] = existing
            with self.assertRaises(ValueError):
                self.publish()
            self.assertEqual(self.bucket.objects["acceptance.json"], existing)

    def test_publisher_retry_keeps_the_producing_attempt(self):
        self.publish()
        with patch.dict(proof.os.environ, {"GITHUB_RUN_ATTEMPT": "3", "PRODUCER_RUN_ATTEMPT": "2"}):
            self.publish(attempt=proof.os.environ["PRODUCER_RUN_ATTEMPT"])
        self.assertEqual(proof.read_json(self.bucket.objects["acceptance.json"])["run_attempt"], "2")
        self.assertNotIn("acceptance/runs/12345-3.json", self.bucket.objects)

    def test_root_html_changing_after_immutable_write_refuses_latest(self):
        self.bucket.before_put = lambda key: setattr(self.bucket, "html_commit", "d" * 40)
        with self.assertRaisesRegex(ValueError, "root HTML"):
            self.publish()
        self.assertNotIn("acceptance.json", self.bucket.objects)

    def test_missing_and_ambiguous_root_html_markers_refuse_current_identity(self):
        for html in ('<html>old release</html>', ('<meta name="application-commit" content="' + FRONTEND + '">') * 2):
            def request(path):
                return html if path == "" else self.bucket.public(path)
            with self.subTest(html=html), self.assertRaisesRegex(ValueError, "root HTML"):
                proof.identity(FRONTEND, request=request)

    def test_older_latest_updates_with_compare_and_swap(self):
        prior = {**self.record, "observed_at": proof.stamp(NOW - timedelta(minutes=1))}
        self.bucket.objects["acceptance.json"] = proof.encode(prior)
        self.publish()
        self.assertEqual(self.bucket.objects["acceptance.json"], self.data)
        self.assertTrue(any("--if-match" in call for call in self.bucket.calls))

    def test_concurrent_latest_writer_cannot_be_overwritten(self):
        def conflict(key):
            if key == "acceptance.json":
                self.bucket.objects[key] = b"concurrent receipt"
        self.bucket.before_put = conflict
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.assertEqual(self.bucket.objects["acceptance.json"], b"concurrent receipt")

    def test_access_denial_is_not_mistaken_for_missing_evidence(self):
        def denied(*args):
            raise subprocess.CalledProcessError(1, args, stderr="(AccessDenied)")
        with self.assertRaises(subprocess.CalledProcessError):
            proof.publish(self.data, FRONTEND, "12345", "2", command=denied, request=self.bucket.public, now=lambda: NOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
