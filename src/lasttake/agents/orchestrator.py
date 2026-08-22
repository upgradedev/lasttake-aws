"""The orchestrator: a Strands agent that runs the checkpoint and decides nothing.

Strands is load-bearing here in a way that is easy to check. Take it out and
you lose the tool loop, the two human approvals, the session that survives a
dead process, and the resume that makes an overnight approval possible. What
remains is a script.

The orchestrator is a model, and that is a deliberate risk with a deliberate
mitigation. A model can forget to call a check. So the deterministic gate does
not ask the orchestrator what it ran; it derives the required check set from
the package itself, finds no result, and fails closed. The orchestrator cannot
make a requirement disappear by not looking at it, which is what makes it safe
to let a model drive at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterable, Optional

from ..ports.interpreter import Interpreter
from .runtime import WrapRun
from .tools import build_tools

ORCHESTRATOR_PROMPT = """You run a pre-wrap checkpoint for a scene that is about
to be released. A script supervisor is watching, and a 1st AD is waiting on a
number.

Your job is to run the checks, report what they found, and route what needs a
human to that human. You do not decide whether the scene is covered, whether a
continuity difference matters, or whether the scene may wrap. Deterministic
policy decides eligibility and the 1st AD decides authority.

Work in this order:

1. Run all four checks: coverage, continuity, metadata, rights. Run every one
   of them, every time, unless you were explicitly told which checks a new
   event affects.
2. Call evaluate_wrap_eligibility and read the count back to the supervisor in
   the exact form the tool returns it.
3. If a required beat has no viable coverage, and only then, call
   request_pickup_approval for that beat. That stops your run until the 1st AD
   answers, which may be tomorrow morning. Ask for one beat at a time and put
   the reason in the supervisor's terms, not in yours.
4. Only when eligibility says eligible, call request_wrap_approval, and only
   after it is approved, call publish_turnover.

Never state that a scene is clear, safe or complete. The states are verified,
missing, conflicting and unknown, and three of those are exceptions. Absent
evidence is a finding, never a pass: if a check produced no result, say so
plainly rather than reading silence as success.

Be brief. The set is being struck around the person reading this."""


from strands.models import Model as _StrandsModel


class OfflineOrchestratorModel(_StrandsModel):
    """A deterministic stand-in for the planning model, for offline runs.

    It is not the model and does not pretend to be: ``model_id`` reports
    ``offline-scripted`` and that string reaches the audit. It walks the same
    tool sequence the system prompt describes, so the offline demo exercises
    the real tools, the real gate, the real interrupts and the real turnover,
    with only the planner replaced.

    It exists so the end-to-end test runs with no AWS account, and so a unit on
    a location with no signal still gets a checkpoint.
    """

    #: The order the prompt asks for, checked against what has already returned.
    SEQUENCE = (
        "run_coverage_check",
        "run_continuity_check",
        "run_metadata_check",
        "run_rights_check",
        "evaluate_wrap_eligibility",
    )

    #: This planner keeps no server-side conversation state; the session
    #: manager on the agent is what persists the run.
    stateful = False

    def __init__(self, plan: tuple[str, ...] | None = None, **kwargs: Any) -> None:
        self.plan = plan if plan is not None else self.SEQUENCE
        self._config: dict = dict(kwargs)

    @property
    def model_id(self) -> str:
        return "offline-scripted/1.0.0"

    def update_config(self, **kwargs: Any) -> None:
        self._config.update(kwargs)

    def get_config(self) -> Any:
        return self._config

    async def structured_output(self, output_model: Any, prompt: Any = None, **kw: Any):
        raise NotImplementedError("the offline orchestrator never asks for structured output")

    #: What an instruction asks for, matched on the most recent user turn.
    #: A real planner reads the sentence; this one matches phrases, which is
    #: enough to walk the same path and honest about being less than reading.
    ROUTES = (
        ("publish the turnover", "publish_turnover"),
        ("approve the wrap", "request_wrap_approval"),
        ("wrap approval", "request_wrap_approval"),
        ("pickup", "request_pickup_approval"),
        ("eligibilit", "evaluate_wrap_eligibility"),
    )

    async def stream(
        self,
        messages: Any,
        tool_specs: Optional[list] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict]:
        called: list[str] = []
        last_user = ""
        for message in messages:
            for block in message.get("content", []):
                if not isinstance(block, dict):
                    continue
                if "toolUse" in block:
                    called.append(block["toolUse"].get("name", ""))
                if message.get("role") == "user" and "text" in block:
                    last_user = block["text"]

        instructed = self._route(last_user)
        if instructed and instructed[0] not in called:
            name, args = instructed
            async for event in self._emit_tool_use(name, args, len(called)):
                yield event
            return

        remaining = [step for step in self.plan if step not in called]
        if remaining:
            name = remaining[0]
            async for event in self._emit_tool_use(name, {}, len(called)):
                yield event
            return

        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {
            "contentBlockDelta": {
                "delta": {
                    "text": (
                        "Checkpoint complete. Every check has a current result and the "
                        "eligibility packet is on file."
                    )
                }
            }
        }
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}

    def _route(self, text: str) -> tuple[str, dict] | None:
        """Turn an instruction into one tool call and its arguments."""
        import re

        lowered = text.lower()
        for phrase, tool_name in self.ROUTES:
            if phrase not in lowered:
                continue
            args: dict[str, Any] = {}
            if tool_name == "request_pickup_approval":
                beat = re.search(r"\bB-\d+\b", text)
                justification = text.split("Justification:", 1)
                args = {
                    "beat_id": beat.group(0) if beat else "",
                    "justification": (
                        justification[1].strip()
                        if len(justification) > 1
                        else "no viable coverage, and the set is still standing"
                    ),
                }
            return tool_name, args
        return None

    async def _emit_tool_use(self, name: str, args: dict, index: int) -> AsyncIterable[dict]:
        yield {"messageStart": {"role": "assistant"}}
        yield {
            "contentBlockStart": {
                "start": {"toolUse": {"name": name, "toolUseId": f"offline-{index}-{name}"}}
            }
        }
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


def build_orchestrator(
    run: WrapRun,
    session_dir: Optional[Path] = None,
    model: Any = None,
    plan: tuple[str, ...] | None = None,
):
    """Assemble the Strands agent for one run.

    ``session_dir`` is what makes an approval survivable across process death.
    Without it the agent still interrupts, but a run that stops at 23:10 dies
    with the process and the 1st AD has nothing to come back to at 06:40.
    """
    from strands import Agent

    if model is None:
        model = OfflineOrchestratorModel(plan=plan)

    session_manager = None
    if session_dir is not None:
        from strands.session import FileSessionManager

        session_manager = FileSessionManager(
            session_id=run.run_id.replace(":", "_"), storage_dir=str(session_dir)
        )

    return Agent(
        model=model,
        tools=build_tools(run),
        system_prompt=ORCHESTRATOR_PROMPT,
        session_manager=session_manager,
    )


def build_s3_session_manager(session_id: str, bucket: str, prefix: str = "sessions/"):
    """The deployed equivalent of ``FileSessionManager``.

    Lambda's ``/tmp`` does not survive the gap between a 23:10 interrupt and an
    06:40 approval, so the deployed build needs shared durable storage or the
    hero does not port. ``S3SessionManager`` ships in the SDK; this is the one
    line that swaps it in.
    """
    from strands.session import S3SessionManager

    return S3SessionManager(session_id=session_id, bucket=bucket, prefix=prefix)
