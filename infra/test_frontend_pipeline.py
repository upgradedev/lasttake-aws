"""CI-only structural regression checks for main -> deploy -> live UAT."""
import copy
from fnmatch import fnmatchcase
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_browser", ROOT / ".github/scripts/install-playwright-chromium.py")
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)


def read_workflow(name):
    # BaseLoader preserves GitHub's 'on' and booleans as strings (YAML 1.1 differs).
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def validate(deploy, uat):
    assert deploy["on"]["push"] == {"branches": ["main"]}
    assert "workflow_dispatch" in deploy["on"]
    assert deploy["concurrency"]["queue"] == "max"
    assert deploy["concurrency"]["cancel-in-progress"] == "false"
    jobs = deploy["jobs"]
    assert jobs["verify"]["uses"] == "./.github/workflows/frontend-ci.yml"
    assert jobs["release"]["needs"] == "verify"
    assert jobs["release"]["if"] == "github.ref == 'refs/heads/main'"
    acceptance = jobs["acceptance"]
    assert acceptance["needs"] == "release"
    assert acceptance["uses"] == "./.github/workflows/aws-uat.yml"
    assert acceptance["with"]["release_sha"] == "${{ github.sha }}"
    # Reusable caller permits OIDC solely for its isolated publisher job.
    assert acceptance["permissions"] == {"contents": "read", "actions": "read", "id-token": "write"}
    assert "continue-on-error" not in acceptance
    assert "secrets" not in acceptance
    for trigger in ("workflow_call", "workflow_dispatch"):
        value = uat["on"][trigger]["inputs"]["release_sha"]
        assert value["required"] == "true" and value["type"] == "string"
    assert uat["permissions"] == {"contents": "read"}
    assert uat["concurrency"]["group"] != deploy["concurrency"]["group"]
    assert uat["concurrency"]["queue"] == "max"
    assert uat["concurrency"]["cancel-in-progress"] == "false"
    job = uat["jobs"]["acceptance"]
    assert job["permissions"] == {"contents": "read"}
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "continue-on-error" not in job
    assert job["env"]["EXPECTED_RELEASE"] == "${{ inputs.release_sha }}"
    steps = job["steps"]
    indexed = {step.get("id"): step for step in steps if "id" in step}
    assert indexed["journeys"]["run"] == "npm run test:e2e -- --forbid-only"
    assert "continue-on-error" not in indexed["journeys"]
    assert "frontend_smoke.py" in indexed["preflight"]["run"]
    assert "frontend_smoke.py" in indexed["postflight"]["run"]
    assert indexed["postflight"]["if"] == "always() && steps.journeys.outcome != 'skipped'"
    assert steps.index(indexed["preflight"]) < steps.index(indexed["journeys"])
    assert steps.index(indexed["postflight"]) > steps.index(indexed["journeys"])
    assert not any("configure-aws-credentials" in step.get("uses", "") for step in steps)
    assert not any("AWS_" in str(step.get("env", {})) for step in steps)
    artifact = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert artifact["if"] == "always()"
    assert artifact["with"]["retention-days"] == "90"
    for path in ("frontend/test-results/", "frontend/artifacts/browser-junit.xml",
                 "frontend/playwright-report/", "frontend/UAT.testbook.*"):
        assert path in artifact["with"]["path"].splitlines()
    publisher = uat["jobs"]["publish"]
    assert publisher["needs"] == "acceptance"
    assert publisher["if"] == "github.ref == 'refs/heads/main' && needs.acceptance.result == 'success'"
    assert publisher["permissions"] == {"contents": "read", "actions": "read", "id-token": "write"}
    assert publisher["concurrency"] == jobs["release"]["concurrency"]
    assert publisher["concurrency"]["group"] == "lasttake-frontend-write"
    assert publisher["concurrency"]["cancel-in-progress"] == "false"
    assert publisher["concurrency"]["queue"] == "max"
    assert not any("npm" in step.get("run", "") or "playwright" in step.get("run", "") for step in publisher["steps"])
    download = next(s for s in publisher["steps"] if s.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"] == {"name": "${{ needs.acceptance.outputs.artifact_name }}", "path": "public-proof"}
    assert job["outputs"] == {"artifact_name": "${{ steps.proof.outputs.artifact_name }}", "run_attempt": "${{ steps.proof.outputs.run_attempt }}"}
    assert publisher["env"]["PRODUCER_RUN_ATTEMPT"] == "${{ needs.acceptance.outputs.run_attempt }}"
    followup = uat["jobs"]["verify-public-proof"]
    assert followup["needs"] == ["acceptance", "publish"] and followup["permissions"] == {"contents": "read"}
    assert followup["env"]["PRODUCER_RUN_ATTEMPT"] == "${{ needs.acceptance.outputs.run_attempt }}"
    assert not any("configure-aws-credentials" in s.get("uses", "") for s in followup["steps"])

    # Playwright cleans test-results at startup. Identity evidence must survive it.
    assert "--output frontend/acceptance-observations/preflight.json" in indexed["preflight"]["run"]
    assert "--output frontend/acceptance-observations/postflight.json" in indexed["postflight"]["run"]
    assert "playwright.proof.config" not in str(steps)


class MainAcceptanceContract(unittest.TestCase):
    def test_backend_push_paths_cover_shipped_inputs_but_refuse_proof_and_packaging_only_changes(self):
        deploy = read_workflow("deploy.yml")
        paths = deploy["on"]["push"]["paths"]
        assert paths == ["src/**", "corpus/**", "infra/stack.yaml"]
        assert "workflow_dispatch" in deploy["on"]
        for path in ("src/lasttake/app/handler.py", "src/lasttake/adapters/aws/dsql.py", "corpus/takes.json", "infra/stack.yaml"):
            with self.subTest(path=path):
                assert any(fnmatchcase(path, pattern) for pattern in paths)
        for path in ("infra/frontend_acceptance.py", "infra/frontend_publish.py", "infra/test_frontend_pipeline.py",
                     "frontend/public/acceptance.html", "README.md", ".github/workflows/deploy.yml", "pyproject.toml"):
            with self.subTest(path=path):
                assert not any(fnmatchcase(path, pattern) for pattern in paths)

    def test_shared_browser_preparation_preserves_install_and_journey_contracts(self):
        invocation = "python ../.github/scripts/install-playwright-chromium.py"
        for name, job in (("frontend-ci.yml", "verify"), ("aws-uat.yml", "acceptance")):
            steps = read_workflow(name)["jobs"][job]["steps"]
            preparation = next(step for step in steps if invocation in step.get("run", ""))
            self.assertEqual(preparation["working-directory"], "frontend")
            self.assertNotIn("continue-on-error", preparation)
        self.assertEqual(browser.COMMAND, ["npx", "playwright", "install", "--with-deps", "chromium"])
        config = (ROOT / "frontend/playwright.config.ts").read_text()
        for value in ("timeout:90000", "retries:0", "workers:1", "maxFailures:1"):
            self.assertIn(value, config)

    def test_browser_reporting_cannot_silently_narrow_history_scan(self):
        workflow = read_workflow("frontend-ci.yml")
        steps = workflow["jobs"]["verify"]["steps"]
        checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["fetch-depth"] == "0"
        scan = next(s for s in steps if s.get("name") == "Secret and prose regressions")
        assert "--unshallow" in scan["run"] and "'+refs/heads/*:refs/remotes/origin/*'" in scan["run"]
        assert 'test "$(git rev-parse --is-shallow-repository)" = false' in scan["run"]
        assert 'test "$(git rev-parse HEAD)" = "$scanned_head"' in scan["run"]
        assert "python tools/secret_scan.py --all-history" in scan["run"]
        assert "continue-on-error" not in scan
        config = (ROOT / "frontend/playwright.config.ts").read_text()
        assert "captureGitInfo:{commit:true,diff:false}" in config

    def setUp(self):
        self.deploy = read_workflow("frontend-deploy.yml")
        self.uat = read_workflow("aws-uat.yml")

    def test_checked_in_pipeline(self):
        validate(self.deploy, self.uat)

    def test_missing_main_trigger_is_rejected(self):
        self.deploy["on"]["push"]["branches"] = ["dev"]
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_test_before_deployment_is_rejected(self):
        self.deploy["jobs"]["acceptance"]["needs"] = "verify"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_dropped_pending_merges_are_rejected(self):
        self.deploy["concurrency"]["queue"] = "single"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_wrong_tested_commit_is_rejected(self):
        self.deploy["jobs"]["acceptance"]["with"]["release_sha"] = "main"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_ignored_browser_failure_is_rejected(self):
        self.deploy["jobs"]["acceptance"]["continue-on-error"] = "true"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_cloud_credentials_in_browser_job_are_rejected(self):
        self.uat["permissions"]["id-token"] = "write"
        with self.assertRaises(AssertionError):
            validate(self.deploy, self.uat)

    def test_explicit_browser_oidc_or_credential_action_is_rejected(self):
        for mutate in (lambda job: job["permissions"].update({"id-token": "write"}),
                       lambda job: job["steps"].append({"uses": "aws-actions/configure-aws-credentials@v4"}),
                       lambda job: job["steps"].append({"env": {"AWS_ACCESS_KEY_ID": "credential"}})):
            candidate = copy.deepcopy(self.uat)
            mutate(candidate["jobs"]["acceptance"])
            with self.assertRaises(AssertionError):
                validate(self.deploy, candidate)

    def test_publication_without_acceptance_or_writer_lock_is_rejected(self):
        for key, value in (("needs", "verify"), ("if", "always()"),
                           ("concurrency", {"group": "independent", "cancel-in-progress": "false", "queue": "max"})):
            candidate = copy.deepcopy(self.uat)
            candidate["jobs"]["publish"][key] = value
            with self.assertRaises(AssertionError):
                validate(self.deploy, candidate)

    def test_browser_or_arbitrary_artifact_in_publisher_is_rejected(self):
        candidate = copy.deepcopy(self.uat)
        candidate["jobs"]["publish"]["steps"].append({"run": "npx playwright test"})
        with self.assertRaises(AssertionError):
            validate(self.deploy, candidate)
        candidate = copy.deepcopy(self.uat)
        download = next(s for s in candidate["jobs"]["publish"]["steps"] if "download-artifact" in s.get("uses", ""))
        download["with"]["name"] = "raw-scenarios"
        with self.assertRaises(AssertionError):
            validate(self.deploy, candidate)

    def test_proof_fixture_tests_never_enter_real_aws_journey_totals(self):
        source = read_workflow("frontend-ci.yml")
        assert "playwright.proof.config.ts" in str(source["jobs"]["verify"]["steps"])
        config = (ROOT / "frontend/playwright.proof.config.ts").read_text()
        assert "testDir: './proof-tests'" in config and "proof-junit.xml" in config
        product = (ROOT / "frontend/playwright.config.ts").read_text()
        assert "testDir:'./tests/e2e'" in product and "test-results/e2e.xml" in product
        assert "test-results/e2e-results.json" in product
        assert "proof-tests" not in product

    def test_observation_inside_browser_cleanup_directory_is_rejected(self):
        candidate = copy.deepcopy(self.uat)
        before = next(s for s in candidate["jobs"]["acceptance"]["steps"] if s.get("id") == "preflight")
        before["run"] = before["run"].replace("acceptance-observations", "test-results")
        with self.assertRaises(AssertionError):
            validate(self.deploy, candidate)

    def test_publisher_retry_must_use_producer_artifact_and_attempt(self):
        candidate = copy.deepcopy(self.uat)
        candidate["jobs"]["publish"]["env"]["PRODUCER_RUN_ATTEMPT"] = "${{ github.run_attempt }}"
        with self.assertRaises(AssertionError):
            validate(self.deploy, candidate)

    def test_missing_postflight_or_failure_artifacts_are_rejected(self):
        for broken in ("postflight", "artifact"):
            uat = copy.deepcopy(self.uat)
            for step in uat["jobs"]["acceptance"]["steps"]:
                if broken == "postflight" and step.get("id") == "postflight":
                    step["run"] = "true"
                if broken == "artifact" and step.get("uses", "").startswith("actions/upload-artifact@"):
                    step["if"] = "success()"
            with self.subTest(broken=broken), self.assertRaises(AssertionError):
                validate(self.deploy, uat)


class BrowserPreparationContract(unittest.TestCase):
    LIST = b"# managed Chrome source\ndeb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] https://dl.google.com/linux/chrome-stable/deb/ stable main\n"
    SOURCES = b"Types: deb\nURIs: https://dl.google.com/linux/chrome-stable/deb/\nSuites: stable\nComponents: main\nSigned-By: /usr/share/keyrings/google.gpg\n"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources.list.d"
        self.sources.mkdir()
        self.ubuntu = self.sources / "ubuntu.sources"
        self.ubuntu.write_bytes(b"Types: deb\nURIs: http://archive.ubuntu.com/ubuntu\nSuites: noble\nComponents: main\n")
        self.original_ubuntu = browser.snapshot(self.ubuntu)

    def execute(self, child, move=None):
        result = browser.install(self.sources, self.root, run=child,
                                 move=move or (lambda source, target: source.rename(target)))
        self.assertEqual(browser.snapshot(self.ubuntu), self.original_ubuntu)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["sources.list.d"])
        return result

    def test_absent_or_comment_only_chrome_source_is_noop(self):
        for comments in (None, b"# no enabled Chrome repository\n"):
            with self.subTest(comments=comments):
                if comments:
                    (self.sources / "google-chrome.list").write_bytes(comments)
                calls = []
                def child(command, **kwargs):
                    calls.append((command, kwargs))
                    return SimpleNamespace(returncode=0)
                def unexpected_move(*args):
                    self.fail("no source may move")
                self.assertEqual(self.execute(child, unexpected_move), 0)
                self.assertEqual(calls, [(["npx", "playwright", "install", "--with-deps", "chromium"], {"check": False})])

    def test_chrome_only_formats_restore_original_bytes_and_metadata_after_success_or_failure(self):
        for name, data in (("google-chrome.list", self.LIST), ("google-chrome.sources", self.SOURCES)):
            for returncode in (0, 100):
                with self.subTest(name=name, returncode=returncode):
                    source = self.sources / name
                    source.write_bytes(data)
                    source.chmod(0o640)
                    before = browser.snapshot(source)
                    def child(command, **kwargs):
                        self.assertFalse(source.exists())
                        self.assertEqual(browser.snapshot(self.ubuntu), self.original_ubuntu)
                        self.assertEqual(command, ["npx", "playwright", "install", "--with-deps", "chromium"])
                        return SimpleNamespace(returncode=returncode)
                    self.assertEqual(self.execute(child), returncode)
                    self.assertEqual(browser.snapshot(source), before)
                    source.unlink()

    def test_all_sources_restore_when_child_cannot_launch(self):
        originals = {}
        for name, data in (("google-chrome.list", self.LIST), ("google-chrome.sources", self.SOURCES)):
            source = self.sources / name
            source.write_bytes(data)
            originals[source] = browser.snapshot(source)
        def child(*args, **kwargs):
            self.assertTrue(all(not source.exists() for source in originals))
            raise FileNotFoundError("installer unavailable")
        with self.assertRaisesRegex(FileNotFoundError, "installer unavailable"):
            self.execute(child)
        for source, original in originals.items():
            self.assertEqual(browser.snapshot(source), original)
        self.assertEqual(browser.snapshot(self.ubuntu), self.original_ubuntu)

    def test_mixed_sources_refused_before_any_move_or_install(self):
        for name, data in (("google-chrome.list", self.LIST + b"deb https://example.invalid/ubuntu noble main\n"),
                           ("google-chrome.sources", self.SOURCES.replace(b"/deb/", b"/deb/ https://example.invalid/ubuntu"))):
            with self.subTest(name=name):
                source = self.sources / name
                source.write_bytes(data)
                before = browser.snapshot(source)
                def unexpected(*args, **kwargs):
                    self.fail("mixed sources must fail before mutation or install")
                with self.assertRaisesRegex(ValueError, "mixed or unrelated"):
                    self.execute(unexpected, unexpected)
                self.assertEqual(browser.snapshot(source), before)
                self.assertEqual(browser.snapshot(self.ubuntu), self.original_ubuntu)
                source.unlink()

    def test_partial_move_failure_restores_previously_moved_source(self):
        for name, data in (("google-chrome.list", self.LIST), ("google-chrome.sources", self.SOURCES)):
            (self.sources / name).write_bytes(data)
        def move(source, target):
            if source == self.sources / "google-chrome.sources":
                raise PermissionError("move refused")
            source.rename(target)
        with self.assertRaisesRegex(PermissionError, "move refused"):
            self.execute(lambda *args, **kwargs: self.fail("installer must not run"), move)
        self.assertEqual((self.sources / "google-chrome.list").read_bytes(), self.LIST)
        self.assertEqual((self.sources / "google-chrome.sources").read_bytes(), self.SOURCES)

    def test_symlink_and_non_ci_execution_refused(self):
        (self.sources / "google-chrome.list").symlink_to(self.ubuntu)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            self.execute(lambda *args, **kwargs: self.fail("installer must not run"))
        with patch.dict(browser.os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, "Linux CI"):
            browser.main()


if __name__ == "__main__":
    unittest.main(verbosity=2)
