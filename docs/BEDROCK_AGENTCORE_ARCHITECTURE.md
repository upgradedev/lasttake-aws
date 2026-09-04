# LastTake: Enterprise Amazon Bedrock AgentCore Alignment Architecture

This specification details how LastTake's autonomous film set shoot-day assurance and wrap risk engine maps to the **Amazon Bedrock AgentCore** architecture and enterprise runtime primitives.

---

## 1. Executive Summary

LastTake provides real-time shoot-day assurance for independent film and episodic television productions. Standing between camera reports, sound logs, script supervisor notes, and the production office, LastTake evaluates whether a scene can safely be wrapped before expensive sets are struck and cast released.

By deploying onto Amazon Bedrock AgentCore, LastTake coordinates multi-agent analysis across creative continuity and production logistics, while ensuring that all decisions are verified by deterministic domain rules and held at an overnight human approval gate.

```
                    ┌─────────────────────────────────────────┐
                    │      Real-Time Shoot-Day Telemetry      │
                    │   (Camera Cards / Sound / Script Notes) │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 Amazon Bedrock AgentCore Multi-Agent Runtime                │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │               Supervisor: Shoot-Day Orchestrator                    │   │
│   └───────────────────┬─────────────────────────────▲───────────────────┘   │
│                       │                             │                       │
│                       ▼                             │                       │
│   ┌──────────────────────────────────────┐  ┌───────┴───────────────────┐   │
│   │    Script Continuity Specialist      │  │ Production Risk Specialist│   │
│   │         (Claude 3.5 Sonnet)          │  │     (Claude 3.5 Haiku)    │   │
│   └───────────────────┬──────────────────┘  └───────▲───────────────────┘   │
│                       │                             │                       │
│                       ▼                             │                       │
│   ┌─────────────────────────────────────────────────┴───────────────────┐   │
│   │           Bedrock Action Group: Deterministic Rule Engines          │   │
│   │   - SAG-AFTRA & Minor Curfew Limits (Hard Turnaround Constraints)   │   │
│   │   - Beat Coverage Matrix (Lined Script Invariants)                  │   │
│   │   - Media Hash & Metadata Identity Reconciler                       │   │
│   └──────────────────────────────────┬──────────────────────────────────┘   │
│                                      │                                      │
│                                      ▼                                      │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │    Return-of-Control (ROC): 1st AD / Producer Human Gate            │   │
│   │    - Overnight Pause State (Suspended Execution)                    │   │
│   │    - Resumption via Authenticated Decision Callback                 │   │
│   └──────────────────────────────────┬──────────────────────────────────┘   │
│                                      │                                      │
│                                      ▼                                      │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │    Audit Memory Engine: Aurora DSQL / DynamoDB Resumption Store     │   │
│   │    - SHA-256 State Hashing across Lambda Container Recycling        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Bedrock AgentCore Primitive Mapping

| LastTake Component | Bedrock AgentCore Equivalent | Implementation & Role |
| :--- | :--- | :--- |
| **`lasttake.agents.orchestrator`** | **Supervisor Agent** | Coordinates multi-agent analysis of the shoot day, transitions state machines, and enforces overnight pauses. |
| **`lasttake.checks`** | **Deterministic Action Groups** | Four rule engines operating with OpenAPI schemas: Coverage (beats vs takes), Continuity (eyeline/wardrobe), Metadata (checksums/reel IDs), and Rights (cast/SAG-AFTRA releases). |
| **`lasttake.domain.turnover`** | **Bedrock Return-of-Control (ROC)** | Enforces human sign-off from the 1st AD or Unit Production Manager before authorizing wrap seals or scheduling pickups. |
| **`lasttake.adapters.aws.dsql`** | **AgentCore Memory Engine** | Distributed SQL (Aurora DSQL) / transactional state store allowing state resumption after Lambda container restarts. |
| **`lasttake.domain.sealing`** | **Cryptographic Audit Action Group** | Mints tamper-proof cryptographic certificates (SHA-256 state chain) over exact shoot-day evidence. |

---

## 3. Operations Research & Safety Constraints

Film sets operate under strict legal, labor, and financial constraints that cannot tolerate probabilistic hallucinations:
1. **SAG-AFTRA Turnaround Rule:** Minimum 12-hour rest period between wrap and next-day call time.
2. **Child Actor Working Hours:** Strict state-mandated daily maximum hours and night-time curfews.
3. **Golden Hour Expiry:** Hard sun angle time limits for exterior scenes.
4. **Beat Coverage Completeness:** Every planned script beat must map to at least one sound-synced, approved take.

---

## 4. Crash-Resilience & Container Recycling

LastTake is architected for serverless deployments where compute instances may be recycled during overnight pauses:
- **State Invariance:** Complete shoot-day state is serialized with SHA-256 cryptographic hashes.
- **Idempotency Tokens:** Prevent duplicate gate evaluations or spurious pickups during web retry events.
- **Cold-Start Resume:** An incoming webhook or human approval call deserializes the verified state and continues orchestration seamlessly.
