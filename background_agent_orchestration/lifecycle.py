"""Deterministic task lifecycle state machine and audit history tracker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskState(str, Enum):
    """Explicit lifecycle states for an orchestrated background task."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
)

VALID_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.RUNNING, TaskState.CANCELED, TaskState.FAILED}),
    TaskState.RUNNING: frozenset(
        {TaskState.PAUSED, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
    ),
    TaskState.PAUSED: frozenset({TaskState.RUNNING, TaskState.CANCELED, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELED: frozenset(),
}


class InvalidStateTransitionError(ValueError):
    """Raised when attempting an illegal lifecycle state transition."""


@dataclass(frozen=True)
class StateTransitionRecord:
    """Audit log entry recording a single state transition."""

    from_state: TaskState
    to_state: TaskState
    reason: str = ""
    timestamp: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class LifecycleStateMachine:
    """Enforces valid background task state transitions and records full audit history."""

    def __init__(
        self,
        contract_id: str = "bg-default",
        initial_state: TaskState | str = TaskState.PENDING,
    ) -> None:
        self.contract_id = contract_id
        self._state: TaskState = self._coerce_state(initial_state)
        self._history: list[StateTransitionRecord] = []

    @staticmethod
    def _coerce_state(state: TaskState | str) -> TaskState:
        if isinstance(state, TaskState):
            return state
        try:
            return TaskState(str(state).lower().strip())
        except ValueError as exc:
            raise ValueError(f"Unknown TaskState: {state!r}") from exc

    @property
    def state(self) -> TaskState:
        """Current lifecycle state."""
        return self._state

    @property
    def history(self) -> list[StateTransitionRecord]:
        """Chronological list of all state transitions."""
        return list(self._history)

    @property
    def is_terminal(self) -> bool:
        """Return True if the state machine is in a terminal state."""
        return self._state in TERMINAL_STATES

    def can_transition(self, target_state: TaskState | str) -> bool:
        """Return True if transitioning from the current state to target_state is valid."""
        target = self._coerce_state(target_state)
        return target in VALID_TRANSITIONS.get(self._state, frozenset())

    def transition(
        self, target_state: TaskState | str, reason: str = ""
    ) -> StateTransitionRecord:
        """Transition to target_state if valid, recording an audit entry; otherwise raise InvalidStateTransitionError."""
        target = self._coerce_state(target_state)
        if not self.can_transition(target):
            raise InvalidStateTransitionError(
                f"Invalid state transition for '{self.contract_id}': "
                f"cannot transition from '{self._state.value}' to '{target.value}'."
            )
        record = StateTransitionRecord(
            from_state=self._state,
            to_state=target,
            reason=reason or f"Transitioned from {self._state.value} to {target.value}",
        )
        self._state = target
        self._history.append(record)
        return record

    def to_dict(self) -> dict[str, Any]:
        """Serialize current state and transition history."""
        return {
            "contract_id": self.contract_id,
            "current_state": self._state.value,
            "is_terminal": self.is_terminal,
            "history": [entry.to_dict() for entry in self._history],
        }
