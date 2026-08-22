"""Spike: does a Strands interrupt survive process death and resume with restored state?

Run as two separate OS processes:

    python spike/interrupt_spike.py start   --store <dir>
    python spike/interrupt_spike.py approve --store <dir>

The claim under test has four parts and each is asserted separately:

  C1  a tool can raise an interrupt from inside itself
  C2  the run returns stop_reason == "interrupt"
  C3  a session manager writes the paused run to durable storage
  C4  a DIFFERENT process resumes it with prior state intact

C4 is the only part that is the hero, and it is the easy one to fake, so the
fake model in the approve process REFUSES to produce a first turn. If the
resume silently restarted the run from scratch, the model is asked for a first
turn and the process dies. A happy-path log cannot hide it.

No Bedrock call anywhere in here. The model is a stub on purpose: an AWS
credential failure must not be readable as "the hero does not work".
"""

import argparse
import inspect
import json
import os
import sys
from typing import Any, AsyncIterable, Optional

from strands import Agent, tool
from strands.models import Model
from strands.session import FileSessionManager
from strands.types.tools import ToolContext

# Carried in the user turn in the START process only. Its presence in the
# message history after resume is what proves the history came off disk.
NONCE = "LASTTAKE-NONCE-7f3a91"
SCENE_ID = "SC-042"
BEAT_ID = "B-17"
SESSION_ID = "wrap-checkpoint-sc042"


class ScriptedModel(Model):
    """Emits a tool use on the first turn, final text once a tool result exists.

    allow_first_turn=False makes an accidental from-scratch rerun fatal.
    """

    def __init__(self, allow_first_turn: bool) -> None:
        self.allow_first_turn = allow_first_turn

    def update_config(self, **kwargs: Any) -> None:
        pass

    def get_config(self) -> Any:
        return {}

    async def structured_output(self, output_model: Any, prompt: Any = None, **kwargs: Any) -> Any:
        raise NotImplementedError("the spike never asks for structured output")

    async def stream(
        self,
        messages: Any,
        tool_specs: Optional[list] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict]:
        has_tool_result = any(
            "toolResult" in block
            for message in messages
            for block in message.get("content", [])
            if isinstance(block, dict)
        )

        if has_tool_result:
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "PICKUP RECORDED"}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            return

        if not self.allow_first_turn:
            raise RuntimeError(
                "C4 FAILED: the model was asked for a FIRST turn in the approve "
                "process. That means the resume restarted the run instead of "
                "restoring it. Messages seen: " + json.dumps(messages)[:600]
            )

        tool_input = json.dumps(
            {"scene_id": SCENE_ID, "beat_id": BEAT_ID, "reason_text": "no viable coverage"}
        )
        yield {"messageStart": {"role": "assistant"}}
        yield {
            "contentBlockStart": {
                "start": {"toolUse": {"name": "request_pickup_approval", "toolUseId": "tu-1"}}
            }
        }
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": tool_input}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


def _raise_interrupt(tool_context: ToolContext, reason: dict) -> Any:
    """Call interrupt() and print the signature we actually resolved against."""
    sig = inspect.signature(tool_context.interrupt)
    print("[pid %d] resolved interrupt signature: %s" % (os.getpid(), sig), flush=True)
    try:
        return tool_context.interrupt("first-ad-approval", reason=reason)
    except TypeError as exc:
        print("[pid %d] positional form rejected (%s), trying reason-only" % (os.getpid(), exc), flush=True)
        return tool_context.interrupt(reason=reason)


@tool(context=True)
def request_pickup_approval(
    tool_context: ToolContext, scene_id: str, beat_id: str, reason_text: str
) -> str:
    """Ask the 1st AD to approve a pickup for an uncovered beat."""
    print("[pid %d] tool entered, about to interrupt" % os.getpid(), flush=True)
    decision = _raise_interrupt(
        tool_context, {"scene_id": scene_id, "beat_id": beat_id, "why": reason_text}
    )
    print("[pid %d] tool resumed, decision=%r" % (os.getpid(), decision), flush=True)
    # scene_id and beat_id were only ever supplied in the START process.
    return json.dumps(
        {
            "scene_id": scene_id,
            "beat_id": beat_id,
            "decision": decision,
            "tool_finished_in_pid": os.getpid(),
        }
    )


def build_agent(store: str, allow_first_turn: bool) -> Agent:
    return Agent(
        model=ScriptedModel(allow_first_turn=allow_first_turn),
        tools=[request_pickup_approval],
        session_manager=FileSessionManager(session_id=SESSION_ID, storage_dir=store),
    )


def fail(msg: str) -> None:
    print("FAIL: " + msg, flush=True)
    sys.exit(1)


def cmd_start(store: str) -> None:
    pid = os.getpid()
    print("=== START process, pid %d ===" % pid, flush=True)
    agent = build_agent(store, allow_first_turn=True)
    result = agent("Wrap checkpoint for %s. %s" % (SCENE_ID, NONCE))

    print("[pid %d] stop_reason = %r" % (pid, result.stop_reason), flush=True)
    if result.stop_reason != "interrupt":
        fail("C2: expected stop_reason 'interrupt', got %r" % (result.stop_reason,))
    print("PASS C1: a tool raised an interrupt from inside itself", flush=True)
    print("PASS C2: stop_reason == 'interrupt'", flush=True)

    interrupts = list(result.interrupts)
    if not interrupts:
        fail("C2: stop_reason was 'interrupt' but result.interrupts is empty")
    interrupt_id = interrupts[0].id
    print("[pid %d] interrupt id = %s" % (pid, interrupt_id), flush=True)

    written = []
    for root, _dirs, files in os.walk(store):
        for f in files:
            written.append(os.path.relpath(os.path.join(root, f), store))
    if not written:
        fail("C3: session manager wrote nothing under %s" % store)
    print("PASS C3: session storage holds %d file(s):" % len(written), flush=True)
    for w in sorted(written):
        print("    " + w, flush=True)

    # The interrupt id is the correlation token the approval link would carry.
    with open(os.path.join(store, "handoff.json"), "w") as fh:
        json.dump({"interrupt_id": interrupt_id, "start_pid": pid}, fh)
    print("=== START process exiting, pid %d is now dead ===" % pid, flush=True)


def cmd_approve(store: str) -> None:
    pid = os.getpid()
    print("=== APPROVE process, pid %d ===" % pid, flush=True)
    with open(os.path.join(store, "handoff.json")) as fh:
        handoff = json.load(fh)
    start_pid = handoff["start_pid"]
    print("[pid %d] start pid was %d" % (pid, start_pid), flush=True)
    if pid == start_pid:
        fail("C4: same pid as the start process, this is not process death")

    # allow_first_turn=False: a from-scratch rerun is fatal, not invisible.
    agent = build_agent(store, allow_first_turn=False)
    result = agent(
        [{"interruptResponse": {"interruptId": handoff["interrupt_id"], "response": "y"}}]
    )

    print("[pid %d] stop_reason = %r" % (pid, result.stop_reason), flush=True)
    if result.stop_reason == "interrupt":
        fail("C4: still interrupted after the approval was supplied")

    transcript = json.dumps(agent.messages)
    if NONCE not in transcript:
        fail(
            "C4: the nonce from the START process is absent from the restored "
            "history, so prior state was not restored"
        )
    print("PASS C4a: the START nonce %s is present in the restored history" % NONCE, flush=True)

    if BEAT_ID not in transcript:
        fail("C4: beat id %s absent, the pre-interrupt tool arguments did not survive" % BEAT_ID)
    print("PASS C4b: pre-interrupt tool argument %s survived the process boundary" % BEAT_ID, flush=True)

    finished_in = None
    for message in agent.messages:
        for block in message.get("content", []):
            if isinstance(block, dict) and "toolResult" in block:
                for inner in block["toolResult"].get("content", []):
                    if "text" in inner:
                        try:
                            finished_in = json.loads(inner["text"])["tool_finished_in_pid"]
                        except (ValueError, KeyError, TypeError):
                            pass
    print("[pid %d] tool finished in pid %s" % (pid, finished_in), flush=True)
    if finished_in != pid:
        fail("C4: tool completed in pid %s, expected the approve pid %d" % (finished_in, pid))
    print("PASS C4c: the tool STARTED in pid %d and FINISHED in pid %d" % (start_pid, pid), flush=True)
    print("[pid %d] final text: %r" % (pid, str(result)), flush=True)
    print("=== all four claims hold ===", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "approve"])
    parser.add_argument("--store", required=True)
    args = parser.parse_args()
    os.makedirs(args.store, exist_ok=True)
    if args.command == "start":
        cmd_start(args.store)
    else:
        cmd_approve(args.store)


if __name__ == "__main__":
    main()
