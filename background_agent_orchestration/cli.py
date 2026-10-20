"""Command-line interface for background-agent-orchestration (bg-orchestrator)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .contract import ExecutionContract
from .lifecycle import LifecycleStateMachine, TaskState
from .milestones import MilestoneReporter
from .steering import SteeringController
from .synthesis import ArtifactSynthesizer

DEFAULT_SIMULATION_OBJECTIVE = (
    "Launch a multi-stage background analysis on our quarterly server access logs, "
    "synthesize security anomalies, and keep me posted at major milestones while I "
    "continue asking other questions"
)

DEFAULT_SIMULATION_STAGES = [
    "ingest_quarterly_logs",
    "correlate_access_patterns",
    "classify_security_anomalies",
    "synthesize_executive_report",
]


def run_simulation(objective: str = DEFAULT_SIMULATION_OBJECTIVE) -> dict[str, Any]:
    """Execute the end-to-end multi-stage background analysis simulation."""
    contract = ExecutionContract(
        contract_id="bg-q3-seclog-01",
        objective=objective,
        stages=list(DEFAULT_SIMULATION_STAGES),
        priority="normal",
        requires_hitl_at=["classify_security_anomalies"],
        metadata={"quarter": "Q3", "source": "access_logs_cluster_eu_us"},
    )
    lifecycle = LifecycleStateMachine(contract_id=contract.contract_id)
    reporter = MilestoneReporter(
        contract_id=contract.contract_id,
        stages=contract.stages,
        threshold_pct=25.0,
    )
    steering = SteeringController(contract=contract, lifecycle=lifecycle)
    synthesizer = ArtifactSynthesizer(contract=contract)

    # Start background execution
    lifecycle.transition(TaskState.RUNNING, reason="Delegated background log analysis worker")

    # Stage 1: Ingest quarterly logs (with noisy low-level logs that get suppressed)
    noisy_stream_stage_1 = [
        "[DEBUG] Opening shard 01 of quarterly access logs...",
        "[TRACE] Reading byte offset 0..65536",
        "[DEBUG] Scanning line 10000: GET /healthz 200",
        "[VERBOSE] Keepalive tick from worker thread-3",
        "[DEBUG] Processing chunk 42/120",
    ]
    for raw in noisy_stream_stage_1:
        reporter.ingest_log(raw, stage="ingest_quarterly_logs")

    synthesizer.register_artifact(
        name="ingested_log_index.json",
        stage="ingest_quarterly_logs",
        content=json.dumps({"total_events": 1420500, "shards": 12, "corrupted_lines": 0}),
    )
    reporter.report_stage_complete(
        stage="ingest_quarterly_logs",
        summary="Indexed 1,420,500 quarterly access log records across 12 shards.",
        metrics={"records": 1420500, "shards": 12},
    )

    # Mid-flight user steering while continuing interactive conversation
    steering.shift_priority(
        "high",
        reason="User elevated priority after noticing latency spikes in auth service",
    )
    steering.inject_guidance(
        "Prioritize anomalous credential-stuffing bursts against /api/v2/auth/token",
        target_stage="correlate_access_patterns",
    )

    # Stage 2: Correlate access patterns
    for raw in [
        "[DEBUG] Computing sliding window IP velocity...",
        "[TRACE] Bucket 198.51.100.0/24 evaluated",
        "[DEBUG] Polling geo-IP lookup cache",
    ]:
        reporter.ingest_log(raw, stage="correlate_access_patterns")

    synthesizer.register_artifact(
        name="correlated_ip_clusters.json",
        stage="correlate_access_patterns",
        content=json.dumps(
            {
                "suspicious_subnets": ["198.51.100.0/24", "203.0.113.0/24"],
                "credential_stuffing_attempts": 18420,
            }
        ),
    )
    reporter.report_stage_complete(
        stage="correlate_access_patterns",
        summary="Correlated 18,420 credential-stuffing attempts across 2 anomalous subnets.",
        metrics={"suspicious_subnets": 2, "attempts": 18420},
    )

    # Stage 3: HITL checkpoint before classifying & locking quarantine rules
    checkpoint = steering.request_hitl_approval(
        stage="classify_security_anomalies",
        prompt=(
            "Approve automated classification & quarantine recommendation for 2 high-risk "
            "subnets (198.51.100.0/24, 203.0.113.0/24)?"
        ),
        checkpoint_id="hitl-quarantine-01",
    )
    steering.resolve_hitl_checkpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        approved=True,
        decision_note="Approved subnet quarantine recommendations for executive report.",
    )

    synthesizer.register_artifact(
        name="security_anomalies_classification.json",
        stage="classify_security_anomalies",
        content=json.dumps(
            {
                "critical_anomalies": 3,
                "quarantined_subnets": ["198.51.100.0/24", "203.0.113.0/24"],
                "mitigation": "WAF rate-limit + ASN block",
            }
        ),
    )
    reporter.report_stage_complete(
        stage="classify_security_anomalies",
        summary="Classified 3 critical anomalies and validated WAF quarantine rules after HITL approval.",
        metrics={"critical_anomalies": 3},
    )

    # Stage 4: Synthesize executive report
    synthesizer.register_artifact(
        name="q3_security_anomaly_executive_report.md",
        stage="synthesize_executive_report",
        content=(
            "# Q3 Server Access Log Security Analysis\n\n"
            "- Analyzed 1,420,500 access events.\n"
            "- Isolated 18,420 credential-stuffing requests on `/api/v2/auth/token`.\n"
            "- Approved WAF quarantine for `198.51.100.0/24` and `203.0.113.0/24`.\n"
        ),
    )
    reporter.report_stage_complete(
        stage="synthesize_executive_report",
        summary="Synthesized verified Q3 security anomaly executive report.",
        metrics={"artifacts_verified": 4},
    )

    # Complete lifecycle and generate synthesis
    lifecycle.transition(
        TaskState.COMPLETED,
        reason="All 4 stages completed and SHA-256 artifacts verified",
    )
    report = synthesizer.synthesize(
        final_state=lifecycle.state,
        completed_stages=reporter.completed_stages,
        highlights=[
            "Processed 1,420,500 quarterly access log lines with 8 noisy debug logs suppressed.",
            "Identified 18,420 credential-stuffing attempts targeting /api/v2/auth/token.",
            "Applied mid-flight priority shift (normal -> high) and HITL approval (hitl-quarantine-01).",
        ],
    )

    return {
        "contract": contract.to_dict(),
        "lifecycle": lifecycle.to_dict(),
        "milestones": reporter.to_dict(),
        "steering": steering.to_dict(),
        "synthesis": report.to_dict(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bg-orchestrator",
        description="Orchestrate autonomous background agents with FSM tracking, milestone filtering, HITL steering, and artifact synthesis.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # delegate
    delegate_p = subparsers.add_parser(
        "delegate", help="Create and validate an asynchronous background ExecutionContract."
    )
    delegate_p.add_argument("--contract-id", default="", help="Optional explicit contract ID.")
    delegate_p.add_argument(
        "--objective",
        required=True,
        help="Natural-language objective for the background agent.",
    )
    delegate_p.add_argument(
        "--stages",
        required=True,
        help="Comma-separated list of ordered execution stages.",
    )
    delegate_p.add_argument(
        "--priority",
        default="normal",
        choices=["low", "normal", "high", "critical"],
        help="Initial execution priority.",
    )
    delegate_p.add_argument(
        "--hitl",
        default="",
        help="Optional comma-separated list of stages requiring HITL approval.",
    )
    delegate_p.add_argument("--json", action="store_true", help="Emit JSON output.")

    # status
    status_p = subparsers.add_parser(
        "status", help="Inspect the lifecycle state and milestones of a background task."
    )
    status_p.add_argument("--contract-id", default="bg-q3-seclog-01", help="Target contract ID.")
    status_p.add_argument(
        "--state",
        default="running",
        choices=[s.value for s in TaskState],
        help="Current state to inspect.",
    )
    status_p.add_argument("--json", action="store_true", help="Emit JSON output.")

    # steer
    steer_p = subparsers.add_parser(
        "steer", help="Apply a mid-flight steering action to an active background task."
    )
    steer_p.add_argument("--contract-id", default="bg-q3-seclog-01", help="Target contract ID.")
    steer_p.add_argument(
        "--action",
        required=True,
        choices=["priority", "guidance", "pause", "resume", "cancel", "approve", "reject"],
        help="Steering action to perform.",
    )
    steer_p.add_argument(
        "--value",
        default="",
        help="Action payload (e.g., new priority level, guidance text, or HITL decision note).",
    )
    steer_p.add_argument("--json", action="store_true", help="Emit JSON output.")

    # simulate
    sim_p = subparsers.add_parser(
        "simulate",
        help="Run the full multi-stage background log analysis simulation.",
    )
    sim_p.add_argument(
        "--objective",
        default=DEFAULT_SIMULATION_OBJECTIVE,
        help="Custom objective override for the simulation.",
    )
    sim_p.add_argument("--json", action="store_true", help="Emit full simulation payload as JSON.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "delegate":
        stages = [s.strip() for s in args.stages.split(",") if s.strip()]
        hitl = [s.strip() for s in args.hitl.split(",") if s.strip()]
        contract = ExecutionContract(
            contract_id=args.contract_id,
            objective=args.objective,
            stages=stages,
            priority=args.priority,
            requires_hitl_at=hitl,
        )
        fsm = LifecycleStateMachine(contract_id=contract.contract_id)
        payload = {
            "delegated": True,
            "contract": contract.to_dict(),
            "lifecycle": fsm.to_dict(),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Delegated contract '{contract.contract_id}' "
                f"(state={fsm.state.value}, priority={contract.priority}, stages={len(contract.stages)})"
            )
        return 0

    if args.subcommand == "status":
        fsm = LifecycleStateMachine(
            contract_id=args.contract_id, initial_state=TaskState(args.state)
        )
        payload = fsm.to_dict()
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Contract '{fsm.contract_id}': state={fsm.state.value} "
                f"(terminal={fsm.is_terminal})"
            )
        return 0

    if args.subcommand == "steer":
        contract = ExecutionContract(
            contract_id=args.contract_id,
            objective="Active background task",
            stages=list(DEFAULT_SIMULATION_STAGES),
            priority="normal",
            requires_hitl_at=["classify_security_anomalies"],
        )
        fsm = LifecycleStateMachine(contract_id=contract.contract_id)
        fsm.transition(TaskState.RUNNING, reason="Task active")
        controller = SteeringController(contract=contract, lifecycle=fsm)

        if args.action == "priority":
            controller.shift_priority(args.value or "high", reason="CLI priority shift")
        elif args.action == "guidance":
            controller.inject_guidance(args.value or "Focus on high-severity anomalies")
        elif args.action == "pause":
            controller.pause(reason=args.value or "CLI pause")
        elif args.action == "resume":
            controller.pause(reason="Preparing resume demonstration")
            controller.resume(reason=args.value or "CLI resume")
        elif args.action == "cancel":
            controller.cancel(reason=args.value or "CLI cancel")
        elif args.action in ("approve", "reject"):
            cp = controller.request_hitl_approval(
                stage="classify_security_anomalies",
                prompt="Confirm anomaly classification gate",
                checkpoint_id="hitl-cli-01",
            )
            controller.resolve_hitl_checkpoint(
                cp.checkpoint_id,
                approved=(args.action == "approve"),
                decision_note=args.value or f"CLI {args.action}",
            )

        payload = controller.to_dict()
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Steered '{contract.contract_id}' with action='{args.action}' -> "
                f"state={fsm.state.value}, priority={contract.priority}"
            )
        return 0

    if args.subcommand == "simulate":
        result = run_simulation(objective=args.objective)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            for m in result["milestones"]["milestones"]:
                print(
                    f"[{m['contract_id']} | {m['progress_pct']:.0f}%] "
                    f"Stage '{m['stage']}': {m['summary']}"
                )
            print()
            print(result["synthesis"]["executive_summary"])
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
