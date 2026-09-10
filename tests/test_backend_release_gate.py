"""Evaluate the actual job condition for push and every dispatch action."""
from pathlib import Path
from types import SimpleNamespace
import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy.yml"


@pytest.mark.parametrize("event,action,expected", [
    ("push", None, False), ("push", "deploy", False), ("pull_request", "deploy", False),
    ("workflow_dispatch", "deploy", True), ("workflow_dispatch", "teardown", False),
    ("workflow_dispatch", "lifecycle", False), ("workflow_dispatch", None, False),
])
def test_only_explicit_manual_deploy_activates_the_broad_backend_job(event, action, expected):
    source = WORKFLOW.read_text()
    condition = source.split("  deploy:\n",1)[1].split("\n",2)[1].strip().removeprefix("if: ")
    assert condition == "github.event_name == 'workflow_dispatch' && inputs.action == 'deploy'"
    result = eval(condition.replace("&&", "and"), {"__builtins__":{}},
                  {"github":SimpleNamespace(event_name=event),"inputs":SimpleNamespace(action=action)})
    assert result is expected
    assert "  teardown:" in source and "  lifecycle:" in source
