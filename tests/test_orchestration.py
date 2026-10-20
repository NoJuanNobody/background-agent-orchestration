"""Comprehensive test suite for background-agent-orchestration."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from background_agent_orchestration import (
    ArtifactSynthesizer,
    CheckpointNotFoundError,
    ExecutionContract,
    InvalidStateTransitionError,
    LifecycleStateMachine,
    MilestoneReporter,
    SteeringController,
    TaskState,
    compute_sha256,
)
from background_agent_orchestration.cli import main as cli_main, run_simulation


def test_execution_contract_creation_and_serialization_roundtrip() -> None:
    contract = ExecutionContract(
        contract_id="bg-test-001",
        objective="Analyze quarterly server access logs for security anomalies",
        stages=["ingest", "correlate", "classify", "synthesize"],
        priority="high",
        requires_hitl_at=["classify"],
        metadata={"env": "production", "web_port": 3004, "api_port": 8004},
    )

    assert contract.contract_id == "bg-test-001"
    assert contract.requires_hitl_for_stage("classify") is True
    assert contract.requires_hitl_for_stage("ingest") is False

    serialized = contract.to_json()
    restored = ExecutionContract.from_json(serialized)
    assert restored.to_dict() == contract.to_dict()


def test_execution_contract_validation_errors() -> None:
    # Empty objective
    with pytest.raises(ValueError, match="objective"):
        ExecutionContract(objective="   ", stages=["stage_1"])

    # Empty stages
    with pytest.raises(ValueError, match="stages"):
        ExecutionContract(objective="Valid objective", stages=[])

    # Duplicate stages
    with pytest.raises(ValueError, match="duplicate"):
        ExecutionContract(objective="Valid objective", stages=["s1", "s1"])

    # Invalid priority
    with pytest.raises(ValueError, match="priority"):
        ExecutionContract(
            objective="Valid objective",
            stages=["s1", "s2"],
            priority="ultra-urgent",
        )

    # HITL stage not in contract stages
    with pytest.raises(ValueError, match="requires_hitl_at"):
        ExecutionContract(
            objective="Valid objective",
            stages=["s1", "s2"],
            requires_hitl_at=["nonexistent_stage"],
        )


def test_lifecycle_valid_state_transitions_and_audit_history() -> None:
    fsm = LifecycleStateMachine(contract_id="bg-fsm-01")
    assert fsm.state == TaskState.PENDING
    assert fsm.is_terminal is False

    r1 = fsm.transition(TaskState.RUNNING, reason="Worker started")
    assert r1.from_state == TaskState.PENDING
    assert r1.to_state == TaskState.RUNNING
    assert fsm.state == TaskState.RUNNING

    fsm.transition(TaskState.PAUSED, reason="HITL checkpoint reached")
    assert fsm.state == TaskState.PAUSED

    fsm.transition(TaskState.RUNNING, reason="HITL approved")
    assert fsm.state == TaskState.RUNNING

    fsm.transition(TaskState.COMPLETED, reason="All stages verified")
    assert fsm.state == TaskState.COMPLETED
    assert fsm.is_terminal is True
    assert len(fsm.history) == 4
    assert [h.to_state for h in fsm.history] == [
        TaskState.RUNNING,
        TaskState.PAUSED,
        TaskState.RUNNING,
        TaskState.COMPLETED,
    ]


def test_lifecycle_invalid_state_transitions_rejected() -> None:
    fsm = LifecycleStateMachine(contract_id="bg-fsm-02")

    # Cannot jump directly from PENDING to COMPLETED or PAUSED
    assert fsm.can_transition(TaskState.COMPLETED) is False
    assert fsm.can_transition(TaskState.PAUSED) is False
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition(TaskState.COMPLETED)
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition(TaskState.PAUSED)

    # Move to RUNNING then CANCELED (terminal)
    fsm.transition(TaskState.RUNNING)
    fsm.transition(TaskState.CANCELED, reason="Aborted by user")
    assert fsm.is_terminal is True

    # Terminal states cannot transition anywhere
    for target in TaskState:
        assert fsm.can_transition(target) is False
        with pytest.raises(InvalidStateTransitionError):
            fsm.transition(target)


def test_milestone_reporter_suppresses_noisy_logs_and_emits_stage_boundaries() -> None:
    stages = ["ingest_logs", "detect_anomalies", "remediate", "report"]
    reporter = MilestoneReporter(
        contract_id="bg-mile-01",
        stages=stages,
        threshold_pct=25.0,
    )

    noisy_lines = [
        "[DEBUG] Worker thread initialized",
        "[TRACE] Reading chunk 1/500",
        "[VERBOSE] Keepalive heartbeat ok",
        "   ",
        "# comment line in script output",
        "Scanning line 4092 of access.log",
    ]
    for line in noisy_lines:
        assert reporter.ingest_log(line, stage="ingest_logs") is None

    assert reporter.ingested_count == len(noisy_lines)
    assert reporter.suppressed_count == len(noisy_lines)
    assert len(reporter.milestones) == 0
    assert reporter.suppression_ratio == 1.0

    # Emit explicit stage boundary milestone
    m1 = reporter.report_stage_complete(
        stage="ingest_logs",
        summary="Ingested 500,000 log entries cleanly.",
        metrics={"lines": 500000},
    )
    assert m1.stage == "ingest_logs"
    assert m1.progress_pct == 25.0
    assert "500,000" in m1.format_chat_update()
    assert len(reporter.milestones) == 1


def test_milestone_reporter_threshold_progress_gating() -> None:
    reporter = MilestoneReporter(
        contract_id="bg-mile-02",
        stages=["s1", "s2", "s3", "s4"],
        threshold_pct=25.0,
    )

    # Fine-grained updates below 25% delta should be suppressed
    assert reporter.report_progress("s1", 5.0, "5% done") is None
    assert reporter.report_progress("s1", 12.0, "12% done") is None
    assert reporter.report_progress("s1", 24.9, "24.9% done") is None
    assert len(reporter.milestones) == 0

    # Crossing 25% emits a milestone
    ev_25 = reporter.report_progress("s1", 25.0, "Quarter way through analysis")
    assert ev_25 is not None
    assert ev_25.progress_pct == 25.0

    # 35% and 49% suppressed (since last emitted was 25% and threshold is 25%)
    assert reporter.report_progress("s2", 35.0, "35% done") is None
    assert reporter.report_progress("s2", 49.0, "49% done") is None

    # Crossing 50% emits a milestone
    ev_50 = reporter.report_progress("s2", 52.0, "Halfway milestone reached")
    assert ev_50 is not None
    assert ev_50.progress_pct == 52.0

    # Reaching 100% always emits
    ev_100 = reporter.report_progress("s4", 100.0, "Finished all processing")
    assert ev_100 is not None
    assert ev_100.progress_pct == 100.0
    assert len(reporter.milestones) == 3


def test_steering_priority_shift_and_guidance_injection() -> None:
    contract = ExecutionContract(
        contract_id="bg-steer-01",
        objective="Analyze server logs",
        stages=["ingest", "analyze", "synthesize"],
        priority="normal",
    )
    fsm = LifecycleStateMachine(contract_id=contract.contract_id)
    fsm.transition(TaskState.RUNNING)
    steering = SteeringController(contract=contract, lifecycle=fsm)

    action_prio = steering.shift_priority("critical", reason="Active incident escalation")
    assert contract.priority == "critical"
    assert action_prio.payload["old_priority"] == "normal"
    assert action_prio.payload["new_priority"] == "critical"

    action_guidance = steering.inject_guidance(
        "Filter out internal healthcheck subnet 10.0.0.0/8",
        target_stage="analyze",
    )
    assert len(steering.guidance_log) == 1
    assert action_guidance.payload["target_stage"] == "analyze"

    with pytest.raises(ValueError, match="Target stage"):
        steering.inject_guidance("Invalid stage target", target_stage="unknown_stage")


def test_steering_hitl_checkpoint_approval_flow() -> None:
    contract = ExecutionContract(
        contract_id="bg-hitl-approve",
        objective="Audit firewall anomalies",
        stages=["scan", "quarantine", "summary"],
        requires_hitl_at=["quarantine"],
    )
    fsm = LifecycleStateMachine(contract_id=contract.contract_id)
    fsm.transition(TaskState.RUNNING)
    steering = SteeringController(contract=contract, lifecycle=fsm)

    cp = steering.request_hitl_approval(
        stage="quarantine",
        prompt="Block 3 anomalous IPs in production firewall?",
        checkpoint_id="cp-fw-01",
    )
    assert fsm.state == TaskState.PAUSED
    assert cp.status == "pending"
    assert len(steering.pending_checkpoints) == 1

    # Attempting manual resume while HITL checkpoint is still pending must fail
    with pytest.raises(InvalidStateTransitionError, match="pending"):
        steering.resume()

    resolved = steering.resolve_hitl_checkpoint(
        checkpoint_id="cp-fw-01",
        approved=True,
        decision_note="Confirmed with SecOps on-call.",
    )
    assert resolved.status == "approved"
    assert fsm.state == TaskState.RUNNING
    assert len(steering.pending_checkpoints) == 0


def test_steering_hitl_checkpoint_rejection_cancels_task() -> None:
    contract = ExecutionContract(
        contract_id="bg-hitl-reject",
        objective="Purge stale access logs",
        stages=["locate", "delete_archives", "verify"],
        requires_hitl_at=["delete_archives"],
    )
    fsm = LifecycleStateMachine(contract_id=contract.contract_id)
    fsm.transition(TaskState.RUNNING)
    steering = SteeringController(contract=contract, lifecycle=fsm)

    cp = steering.request_hitl_approval(
        stage="delete_archives",
        prompt="Permanently delete 90-day archive bucket?",
        checkpoint_id="cp-del-01",
    )
    assert fsm.state == TaskState.PAUSED

    resolved = steering.resolve_hitl_checkpoint(
        checkpoint_id=cp.checkpoint_id,
        approved=False,
        decision_note="Hold deletion until compliance audit finishes.",
    )
    assert resolved.status == "rejected"
    assert fsm.state == TaskState.CANCELED
    assert fsm.is_terminal is True

    with pytest.raises(CheckpointNotFoundError):
        steering.resolve_hitl_checkpoint("cp-unknown", approved=True)


def test_artifact_synthesizer_sha256_integrity_and_tamper_detection() -> None:
    contract = ExecutionContract(
        contract_id="bg-synth-01",
        objective="Synthesize security report",
        stages=["extract", "report"],
    )
    synthesizer = ArtifactSynthesizer(contract=contract)

    payload = '{"anomalies": 7, "severity": "high"}'
    expected_digest = compute_sha256(payload)
    record = synthesizer.register_artifact(
        name="anomalies.json",
        stage="extract",
        content=payload,
    )
    assert record.sha256 == expected_digest
    assert synthesizer.verify_artifact(record) is True

    # Tamper with content and verify detection
    assert (
        synthesizer.verify_artifact(
            record, current_content='{"anomalies": 0, "severity": "none"}'
        )
        is False
    )
    assert record.verified is False


def test_artifact_synthesizer_completeness_and_executive_summary() -> None:
    contract = ExecutionContract(
        contract_id="bg-synth-02",
        objective="Complete 3-stage anomaly pipeline",
        stages=["stage_a", "stage_b", "stage_c"],
        priority="high",
    )
    synthesizer = ArtifactSynthesizer(contract=contract)

    synthesizer.register_artifact("a.json", "stage_a", '{"ok": true}')
    synthesizer.register_artifact("b.json", "stage_b", '{"ok": true}')

    # Missing stage_c
    is_complete, missing = synthesizer.verify_completeness()
    assert is_complete is False
    assert missing == ["stage_c"]

    partial_report = synthesizer.synthesize(final_state=TaskState.RUNNING)
    assert partial_report.is_complete is False
    assert "stage_c" in partial_report.missing_stages

    # Register stage_c artifact and re-synthesize
    synthesizer.register_artifact("c.md", "stage_c", "# Final Deliverable")
    full_report = synthesizer.synthesize(
        final_state=TaskState.COMPLETED,
        highlights=["All 3 stages verified with zero errors."],
    )
    assert full_report.is_complete is True
    assert full_report.missing_stages == []
    assert full_report.all_artifacts_verified is True
    assert "Executive Synthesis" in full_report.executive_summary
    assert "VERIFIED" in full_report.executive_summary


def test_cli_subcommands_and_full_simulation(capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Test `simulate --json`
    rc_sim = cli_main(["simulate", "--json"])
    assert rc_sim == 0
    sim_out = json.loads(capsys.readouterr().out)
    assert sim_out["lifecycle"]["current_state"] == "completed"
    assert sim_out["synthesis"]["is_complete"] is True
    assert sim_out["milestones"]["suppressed_count"] >= 8
    assert sim_out["milestones"]["emitted_count"] == 4
    assert sim_out["steering"]["priority"] == "high"

    # 2. Test `delegate --json`
    rc_del = cli_main(
        [
            "delegate",
            "--contract-id",
            "bg-cli-99",
            "--objective",
            "Run background log audit",
            "--stages",
            "ingest,analyze,report",
            "--priority",
            "high",
            "--hitl",
            "analyze",
            "--json",
        ]
    )
    assert rc_del == 0
    del_out = json.loads(capsys.readouterr().out)
    assert del_out["delegated"] is True
    assert del_out["contract"]["contract_id"] == "bg-cli-99"
    assert del_out["contract"]["requires_hitl_at"] == ["analyze"]

    # 3. Test `status --json`
    rc_stat = cli_main(["status", "--contract-id", "bg-cli-99", "--state", "running", "--json"])
    assert rc_stat == 0
    stat_out = json.loads(capsys.readouterr().out)
    assert stat_out["current_state"] == "running"

    # 4. Test `steer --json`
    rc_steer = cli_main(
        [
            "steer",
            "--contract-id",
            "bg-cli-99",
            "--action",
            "priority",
            "--value",
            "critical",
            "--json",
        ]
    )
    assert rc_steer == 0
    steer_out = json.loads(capsys.readouterr().out)
    assert steer_out["priority"] == "critical"

    # 5. Direct programmatic simulation sanity check
    direct_sim = run_simulation()
    assert len(direct_sim["synthesis"]["artifacts"]) == 4
