"""Evaluate the actual job condition for push and every dispatch action."""
from pathlib import Path
from types import SimpleNamespace
import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy.yml"
STACK = Path(__file__).resolve().parents[1] / "infra/stack.yaml"


@pytest.mark.parametrize("event,action,expected", [
    ("push", None, False), ("push", "deploy", False), ("pull_request", "deploy", False),
    ("workflow_dispatch", "deploy", True), ("workflow_dispatch", "teardown", False),
    ("workflow_dispatch", "lifecycle", False), ("workflow_dispatch", None, False),
])
def test_only_explicit_manual_deploy_activates_the_broad_backend_job(event, action, expected):
    source = WORKFLOW.read_text()
    condition = source.split("  deploy:\n",1)[1].split("\n",1)[0].strip().removeprefix("if: ")
    assert condition == "github.event_name == 'workflow_dispatch' && inputs.action == 'deploy'"
    result = eval(condition.replace("&&", "and"), {"__builtins__":{}},
                  {"github":SimpleNamespace(event_name=event),"inputs":SimpleNamespace(action=action)})
    assert result is expected
    assert "  teardown:" in source and "  lifecycle:" in source


def test_eventbridge_rule_targets_a_separate_terminal_consumer_with_bounded_retries():
    source = STACK.read_text(encoding="utf-8")
    role = source.split("  EventConsumerRole:", 1)[1].split("  EventConsumerFunction:", 1)[0]
    function = source.split("  EventConsumerFunction:", 1)[1].split("  EventDeliveryRule:", 1)[0]
    rule = source.split("  EventDeliveryRule:", 1)[1].split("  EventConsumerInvokePermission:", 1)[0]
    permission = source.split("  EventConsumerInvokePermission:", 1)[1].split("  EventConsumerAsyncConfig:", 1)[0]
    async_config = source.split("  EventConsumerAsyncConfig:", 1)[1].split("  # There was an", 1)[0]

    assert "Type: AWS::Lambda::Function" in function
    assert "Handler: lasttake.adapters.aws.event_consumer.handler" in function
    assert "ReservedConcurrentExecutions: 2" in function
    assert "eventbridge-consumption/*" in role
    assert "events:PutEvents" not in role
    assert "Type: AWS::Events::Rule" in rule
    assert "EventBusName: !Ref EventBus" in rule
    assert "- lasttake.orchestrator" in rule
    assert "detail-type:" in rule
    for event_type in (
        "scene.package.registered", "take.captured", "scene.wrap-checkpoint.requested",
        "dailies.uploaded", "analysis.requested", "finding.recorded", "approval.requested",
        "pickup.requested", "rights.record.updated", "wrap.eligible", "wrap.ready",
        "turnover.generated",
    ):
        assert f"- {event_type}" in rule
    assert "Arn: !GetAtt EventConsumerFunction.Arn" in rule
    assert "MaximumEventAgeInSeconds: 300" in rule
    assert "MaximumRetryAttempts: 1" in rule
    assert "Principal: events.amazonaws.com" in permission
    assert "SourceArn: !GetAtt EventDeliveryRule.Arn" in permission
    assert "Type: AWS::Lambda::EventInvokeConfig" in async_config
    assert 'Qualifier: "$LATEST"' in async_config
    assert "MaximumEventAgeInSeconds: 300" in async_config
    assert "MaximumRetryAttempts: 1" in async_config
    assert "FunctionName: !Ref EventConsumerFunction" in async_config
    assert "FunctionName: !Ref ApiFunction" not in async_config


def test_deploy_proves_the_rule_target_and_public_consumption_receipt():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "aws events list-targets-by-rule" in workflow
    assert "EventConsumerFunctionName" in workflow
    assert "EventDeliveryRuleName" in workflow
    assert 'RULE="${RULE_REF##*|}"' in workflow
    assert "scene.wrap-checkpoint.requested" in workflow
    assert "receipt['status']=='consumed'" in workflow
    assert "receipt['deployed_sha']==os.environ['GITHUB_SHA']" in workflow
    assert "consumed_receipt_count" in workflow
