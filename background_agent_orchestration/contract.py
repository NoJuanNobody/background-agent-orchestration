"""Execution contract definition, validation, and serialization for background agent tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
import uuid

VALID_PRIORITIES = ("low", "normal", "high", "critical")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_contract_id() -> str:
    return f"bg-{uuid.uuid4().hex[:8]}"


@dataclass
class ExecutionContract:
    """Self-contained execution contract for asynchronous background task delegation."""

    contract_id: str = field(default_factory=_generate_contract_id)
    objective: str = ""
    stages: list[str] = field(default_factory=list)
    priority: str = "normal"
    requires_hitl_at: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.contract_id or not str(self.contract_id).strip():
            self.contract_id = _generate_contract_id()
        if not self.created_at or not str(self.created_at).strip():
            self.created_at = _utc_now_iso()
        self.stages = list(self.stages) if self.stages is not None else []
        self.requires_hitl_at = (
            list(self.requires_hitl_at) if self.requires_hitl_at is not None else []
        )
        self.metadata = dict(self.metadata) if self.metadata is not None else {}
        self.validate()

    def validate(self) -> bool:
        """Validate contract invariants and raise ValueError if any constraint is violated."""
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("ExecutionContract.objective must be a non-empty string.")

        if not isinstance(self.stages, list) or len(self.stages) == 0:
            raise ValueError("ExecutionContract.stages must be a non-empty list of stage names.")

        cleaned_stages: list[str] = []
        for stage in self.stages:
            if not isinstance(stage, str) or not stage.strip():
                raise ValueError("Every stage in ExecutionContract.stages must be a non-empty string.")
            cleaned_stages.append(stage.strip())

        if len(set(cleaned_stages)) != len(cleaned_stages):
            raise ValueError("ExecutionContract.stages must not contain duplicate stage names.")

        if self.priority not in VALID_PRIORITIES:
            raise ValueError(
                f"Invalid priority '{self.priority}'. Must be one of {VALID_PRIORITIES}."
            )

        unknown_hitl = [s for s in self.requires_hitl_at if s not in cleaned_stages]
        if unknown_hitl:
            raise ValueError(
                f"requires_hitl_at contains stages not present in contract stages: {unknown_hitl}"
            )

        return True

    def requires_hitl_for_stage(self, stage: str) -> bool:
        """Return True if the given stage requires Human-in-the-Loop approval."""
        return stage in self.requires_hitl_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize the contract to a plain dictionary."""
        return {
            "contract_id": self.contract_id,
            "objective": self.objective,
            "stages": list(self.stages),
            "priority": self.priority,
            "requires_hitl_at": list(self.requires_hitl_at),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize the contract to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionContract:
        """Deserialize an ExecutionContract from a dictionary."""
        return cls(
            contract_id=data.get("contract_id", ""),
            objective=data.get("objective", ""),
            stages=list(data.get("stages", [])),
            priority=data.get("priority", "normal"),
            requires_hitl_at=list(data.get("requires_hitl_at", [])),
            created_at=data.get("created_at", ""),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_json(cls, raw_json: str) -> ExecutionContract:
        """Deserialize an ExecutionContract from a JSON string."""
        data = json.loads(raw_json)
        if not isinstance(data, dict):
            raise ValueError("Serialized ExecutionContract JSON must represent an object.")
        return cls.from_dict(data)
