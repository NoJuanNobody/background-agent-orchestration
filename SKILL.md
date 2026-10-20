---
name: background-agent-orchestration
description: Protocol and runtime toolkit for orchestrating autonomous background agents from an interactive conversational interface. Covers asynchronous task delegation via ExecutionContracts, explicit lifecycle FSM tracking, noise-filtered milestone progress reporting, mid-flight steering with HITL checkpoints, and SHA-256 verified artifact synthesis.
---

# Background Agent Orchestration (`background-agent-orchestration`)

When a user requests a long-running, multi-stage workflow—such as *"Launch a multi-stage background analysis on our quarterly server access logs, synthesize security anomalies, and keep me posted at major milestones while I continue asking other questions"*—the conversational agent MUST NOT block the interactive thread with raw tool loops or verbose log streams.

Instead, follow the **5-Pillar Background Agent Orchestration Protocol** defined in this skill.

---

## 1. Asynchronous Task Delegation

Package every background job into a self-contained, immutable-by-default **`ExecutionContract`** and hand it off immediately so the conversational thread remains responsive (`<100ms` turn turnaround).

### Contract Schema
- `contract_id`: Unique identifier (e.g., `bg-8f92a1c4`)
- `objective`: Crisp natural-language objective statement
- `stages`: Ordered list of discrete execution stages (e.g., `["ingest_logs", "detect_anomalies", "remediate_plan", "executive_synthesis"]`)
- `priority`: Initial execution priority (`low`, `normal`, `high`, `critical`)
- `requires_hitl_at`: Subset of stages that require explicit Human-in-the-Loop (HITL) approval before proceeding
- `created_at`: ISO-8601 UTC creation timestamp
- `metadata`: Arbitrary context dictionary (workspace paths, resource budgets, ports)

### Delegation Rules
1. Validate contract completeness (`stages` non-empty, `requires_hitl_at` subset of `stages`, valid `priority`) **before** spawning the worker.
2. Acknowledge delegation in a single concise message containing the `contract_id`, stages, and next expected milestone.

---

## 2. State & Lifecycle Tracking

Every background task is governed by a deterministic Finite State Machine (`LifecycleStateMachine`) with six explicit states (`TaskState`):

| State | Meaning | Valid Outgoing Transitions |
| :--- | :--- | :--- |
| `pending` | Contract validated and queued, worker not yet executing | `running`, `canceled`, `failed` |
| `running` | Actively executing stages in the background | `paused`, `completed`, `failed`, `canceled` |
| `paused` | Execution suspended awaiting HITL approval or user resume | `running`, `canceled`, `failed` |
| `completed` | All contract stages finished and artifacts verified (Terminal) | *None* |
| `failed` | Unrecoverable error encountered during execution (Terminal) | *None* |
| `canceled` | Explicitly aborted by user steering or rejected HITL gate (Terminal) | *None* |

Every transition records an immutable `StateTransitionRecord` (`from_state`, `to_state`, `reason`, `timestamp`) for auditability.

---

## 3. Milestone Progress Reporting

Never flood the interactive conversation with raw `DEBUG`/`TRACE`/`INFO` stdout chatter or 1% progress ticks.

Use `MilestoneReporter` to filter execution telemetry:
- **Suppress Noise**: Drop low-level log lines (`DEBUG`, `TRACE`, raw stack traces, repetitive polling messages) while incrementing `suppressed_count`.
- **Emit Clean Milestones**: Emit structured `MilestoneEvent` notifications only when:
  1. A declared contract stage completes (`report_stage_complete`), OR
  2. Progress crosses a configured percentage threshold delta (default `>= 25%`).

Each `MilestoneEvent` provides:
- `contract_id`, `stage`, `progress_pct`, `summary`, `metrics`, and `timestamp`.

---

## 4. Mid-Flight Steering & HITL Checkpoints

While the background agent works, the user continues conversing and may adjust course at any time via `SteeringController`:

- **Priority Shift (`shift_priority`)**: Dynamically elevate or lower task priority (`low` <-> `critical`) without restarting completed stages.
- **Guidance Injection (`inject_guidance`)**: Append mid-flight instructions (e.g., *"Focus specifically on SSH brute-force anomalies from subnet 10.24.0.0/16"*) scoped globally or to a specific stage.
- **Pause / Resume (`pause`, `resume`)**: Temporarily freeze resource consumption and resume cleanly.
- **Cancellation (`cancel`)**: Immediately transition the task to `canceled` and release locks.
- **HITL Checkpoints (`request_hitl_approval`, `resolve_hitl_checkpoint`)**:
  - When execution reaches a stage listed in `requires_hitl_at`, the orchestrator automatically transitions to `paused` and emits an `HITLCheckpoint` prompt.
  - **Approved**: Transitions `paused -> running` and records the approval note.
  - **Rejected**: Transitions `paused -> canceled` (or `failed`) and halts further stage execution.

---

## 5. Synthesis & Artifact Delivery

Before transitioning to `completed`, `ArtifactSynthesizer` performs final integrity checks:

1. **SHA-256 Integrity Verification**: Computes and verifies SHA-256 digests (`sha256`) and byte sizes for every produced artifact.
2. **Stage Completeness Check**: Verifies that every stage declared in `ExecutionContract.stages` produced its expected deliverable or completion marker.
3. **Executive Summary Formatting**: Generates a concise Markdown executive summary for the conversational thread containing the final state, stage coverage, verified artifact table (with SHA-256 prefixes), and key findings.

---

## CLI Quick Reference

```bash
# Run a full multi-stage background analysis simulation (logs -> anomalies -> HITL -> synthesis)
bg-orchestrator simulate --json

# Delegate a custom background task contract
bg-orchestrator delegate \
  --objective "Analyze quarterly server access logs and synthesize security anomalies" \
  --stages ingest_logs,parse_records,detect_anomalies,synthesize_report \
  --priority high \
  --hitl detect_anomalies

# Inspect lifecycle state or apply mid-flight steering
bg-orchestrator status --contract-id bg-demo0001
bg-orchestrator steer --contract-id bg-demo0001 --action priority --value critical
```
