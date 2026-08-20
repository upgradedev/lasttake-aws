# lasttake-aws

**Before you wrap the set, know whether you truly have the scene.**

Pre-wrap shoot-day assurance for the production-to-post handoff. At the end of a shoot day the
evidence needed to judge whether a scene is ready to wrap sits in seven places at once: the current
script, the planned shots, the captured takes, the script supervisor's notes, the camera and sound
reports, continuity references, and the rights and release records. Nobody holds all of it. The gap
is usually found after cast, location and equipment are released, when fifteen minutes of work has
become a pickup day.

Built for **Agents for Humans (AWS)**, track **Professional Agents**, on the **Strands Agents SDK**.

## Status

Scaffolding. Product code lands here. Nothing below is claimed as working yet; this README is
rewritten with measured numbers as each piece lands.

## What it does, when it exists

A wrap checkpoint fires as an event. Five bounded agents check coverage, continuity, metadata
integrity, and rights against immutable source artifacts. A deterministic gate, not a model, combines
the findings into an eligibility result. The 1st AD approves a pickup. The approved action changes
state through a real tool, and a versioned turnover manifest reaches editorial.

It does not judge creative quality, it does not approve anything itself, and it never infers a pass
from absent evidence. Absent evidence is a finding.

## Licence

MIT. See `LICENSE`.
