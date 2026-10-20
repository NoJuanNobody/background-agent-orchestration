"""Mid-flight task steering and Human-in-the-Loop (HITL) checkpoint controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

from .contract import VALID_PRIORITIES, ExecutionContract
from .lifecycle import (
    InvalidStateTransitionError,
    LifecycleStateMachine,
    StateTransitionRecord,
    TaskState,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckpointNotFoundError(KeyError, ValueError):
    """Raised when referencing an unknown HITL checkpoint identifier."""


@dataclass
class HITLCheckpoint:
    """Represents a Human-in-the-Loop approval gate at a critical stage."""

    checkpoint_id: str
    stage: str
    prompt: str
    status: str = "pending"  # pending | approved | rejected | canceled
    decision_note: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    resolved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "stage": self.stage,
            "prompt": self.prompt,
            "status": self.status,
            "decision_note": self.decision_note,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass(frozen=True)
class SteeringAction:
    """Audit record for any mid-flight steering command."""

    action_type: str
    payload: dict[str, Any]
    timestamp: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


class SteeringController:
    """Coordinates mid-flight priority shifts, guidance injection, pause/resume/cancel, and HITL checkpoints."""

    def __init__(
        self,
        contract: ExecutionContract,
        lifecycle: LifecycleStateMachine | None = None,
    ) -> None:
        self.contract = contract
        self.lifecycle = lifecycle or LifecycleStateMachine(contract_id=contract.contract_id)
        self._actions: list[SteeringAction] = []
        self._guidance_log: list[dict[str, Any]] = []
        self._checkpoints: dict[str, HITLCheckpoint] = {}

    @property
    def actions(self) -> list[SteeringAction]:
        """Chronological log of all steering actions applied to this task."""
        return list(self._actions)

    @property
    def guidance_log(self) -> list[dict[str, Any]]:
        """List of injected mid-flight user guidance messages."""
        return list(self._guidance_log)

    @property
    def checkpoints(self) -> dict[str, HITLCheckpoint]:
        """Dictionary of HITL checkpoints keyed by checkpoint_id."""
        return dict(self._checkpoints)

    @property
    def pending_checkpoints(self) -> list[HITLCheckpoint]:
        """List of unresolved HITL checkpoints currently awaiting user decision."""
        return [cp for cp in self._checkpoints.values() if cp.status == "pending"]

    def _ensure_active(self, operation: str) -> None:
        if self.lifecycle.is_terminal:
            raise InvalidStateTransitionError(
                f"Cannot perform '{operation}' on terminal task '{self.contract.contract_id}' "
                f"(current state: {self.lifecycle.state.value})."
            )

    def shift_priority(self, new_priority: str, reason: str = "") -> SteeringAction:
        """Dynamically shift execution priority mid-flight."""
        self._ensure_active("shift_priority")
        if new_priority not in VALID_PRIORITIES:
            raise ValueError(
                f"Invalid priority '{new_priority}'. Must be one of {VALID_PRIORITIES}."
            )
        previous_priority = self.contract.priority
        self.contract.priority = new_priority
        action = SteeringAction(
            action_type="shift_priority",
            payload={
                "old_priority": previous_priority,
                "new_priority": new_priority,
                "reason": reason or f"Priority changed from {previous_priority} to {new_priority}",
            },
        )
        self._actions.append(action)
        return action

    def inject_guidance(
        self, guidance: str, target_stage: str | None = None
    ) -> SteeringAction:
        """Inject mid-flight user instructions or constraints into the running workflow."""
        self._ensure_active("inject_guidance")
        if not isinstance(guidance, str) or not guidance.strip():
            raise ValueError("Guidance message must be a non-empty string.")
        if target_stage is not None and target_stage not in self.contract.stages:
            raise ValueError(
                f"Target stage '{target_stage}' is not declared in contract stages {self.contract.stages}."
            )
        entry = {
            "guidance": guidance.strip(),
            "target_stage": target_stage,
            "timestamp": _utc_now_iso(),
        }
        self._guidance_log.append(entry)
        action = SteeringAction(
            action_type="inject_guidance",
            payload=entry,
        )
        self._actions.append(action)
        return action

    def request_hitl_approval(
        self,
        stage: str,
        prompt: str,
        checkpoint_id: str | None = None,
    ) -> HITLCheckpoint:
        """Pause task execution at a critical stage and register an HITL approval checkpoint."""
        self._ensure_active("request_hitl_approval")
        if not prompt or not str(prompt).strip():
            raise ValueError("HITL checkpoint prompt must be a non-empty string.")

        if self.lifecycle.state == TaskState.PENDING:
            self.lifecycle.transition(
                TaskState.RUNNING, reason=f"Started execution entering stage '{stage}'"
            )

        if self.lifecycle.state == TaskState.RUNNING:
            self.lifecycle.transition(
                TaskState.PAUSED,
                reason=f"Paused at HITL checkpoint for stage '{stage}'",
            )

        cp_id = checkpoint_id or f"hitl-{uuid.uuid4().hex[:8]}"
        checkpoint = HITLCheckpoint(
            checkpoint_id=cp_id,
            stage=stage,
            prompt=prompt.strip(),
            status="pending",
        )
        self._checkpoints[cp_id] = checkpoint
        self._actions.append(
            SteeringAction(
                action_type="request_hitl_approval",
                payload=checkpoint.to_dict(),
            )
        )
        return checkpoint

    def resolve_hitl_checkpoint(
        self,
        checkpoint_id: str,
        approved: bool,
        decision_note: str = "",
    ) -> HITLCheckpoint:
        """Resolve a pending HITL checkpoint: resume to RUNNING if approved, or transition to CANCELED if rejected."""
        if checkpoint_id not in self._checkpoints:
            raise CheckpointNotFoundError(f"Unknown HITL checkpoint_id: '{checkpoint_id}'.")

        checkpoint = self._checkpoints[checkpoint_id]
        if checkpoint.status != "pending":
            raise ValueError(
                f"HITL checkpoint '{checkpoint_id}' is already resolved with status '{checkpoint.status}'."
            )

        checkpoint.resolved_at = _utc_now_iso()
        checkpoint.decision_note = decision_note.strip()

        if approved:
            checkpoint.status = "approved"
            if self.lifecycle.state == TaskState.PAUSED and not self.pending_checkpoints:
                self.lifecycle.transition(
                    TaskState.RUNNING,
                    reason=f"HITL checkpoint '{checkpoint_id}' approved for stage '{checkpoint.stage}'",
                )
        else:
            checkpoint.status = "rejected"
            if not self.lifecycle.is_terminal:
                self.lifecycle.transition(
                    TaskState.CANCELED,
                    reason=f"HITL checkpoint '{checkpoint_id}' rejected at stage '{checkpoint.stage}': {checkpoint.decision_note}",
                )

        self._actions.append(
            SteeringAction(
                action_type="resolve_hitl_checkpoint",
                payload={
                    "checkpoint_id": checkpoint_id,
                    "approved": approved,
                    "status": checkpoint.status,
                    "decision_note": checkpoint.decision_note,
                },
            )
        )
        return checkpoint

    def pause(self, reason: str = "User requested pause") -> StateTransitionRecord:
        """Pause a running background task."""
        record = self.lifecycle.transition(TaskState.PAUSED, reason=reason)
        self._actions.append(
            SteeringAction(
                action_type="pause",
                payload={"reason": reason, "state": self.lifecycle.state.value},
            )
        )
        return record

    def resume(self, reason: str = "User resumed execution") -> StateTransitionRecord:
        """Resume a paused background task (fails if unresolved HITL checkpoints are still pending)."""
        if self.pending_checkpoints:
            pending_ids = [cp.checkpoint_id for cp in self.pending_checkpoints]
            raise InvalidStateTransitionError(
                f"Cannot resume task '{self.contract.contract_id}' while HITL checkpoints remain pending: {pending_ids}"
            )
        record = self.lifecycle.transition(TaskState.RUNNING, reason=reason)
        self._actions.append(
            SteeringAction(
                action_type="resume",
                payload={"reason": reason, "state": self.lifecycle.state.value},
            )
        )
        return record

    def cancel(self, reason: str = "User canceled task") -> StateTransitionRecord:
        """Immediately cancel a pending, running, or paused background task."""
        record = self.lifecycle.transition(TaskState.CANCELED, reason=reason)
        for cp in self._checkpoints.values():
            if cp.status == "pending":
                cp.status = "canceled"
                cp.resolved_at = _utc_now_iso()
                cp.decision_note = reason
        self._actions.append(
            SteeringAction(
                action_type="cancel",
                payload={"reason": reason, "state": self.lifecycle.state.value},
            )
        )
        return record

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract.contract_id,
            "priority": self.contract.priority,
            "state": self.lifecycle.state.value,
            "guidance_log": list(self._guidance_log),
            "checkpoints": {k: v.to_dict() for k, v in self._checkpoints.items()},
            "actions": [a.to_dict() for a in self._actions],
        }
