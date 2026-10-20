"""Background Agent Orchestration protocol and runtime package."""

from .contract import VALID_PRIORITIES, ExecutionContract
from .lifecycle import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    InvalidStateTransitionError,
    LifecycleStateMachine,
    StateTransitionRecord,
    TaskState,
)
from .milestones import MilestoneEvent, MilestoneReporter
from .steering import (
    CheckpointNotFoundError,
    HITLCheckpoint,
    SteeringAction,
    SteeringController,
)
from .synthesis import (
    ArtifactRecord,
    ArtifactSynthesizer,
    SynthesisReport,
    compute_sha256,
)

__all__ = [
    "VALID_PRIORITIES",
    "ExecutionContract",
    "TaskState",
    "TERMINAL_STATES",
    "VALID_TRANSITIONS",
    "InvalidStateTransitionError",
    "StateTransitionRecord",
    "LifecycleStateMachine",
    "MilestoneEvent",
    "MilestoneReporter",
    "CheckpointNotFoundError",
    "HITLCheckpoint",
    "SteeringAction",
    "SteeringController",
    "ArtifactRecord",
    "SynthesisReport",
    "ArtifactSynthesizer",
    "compute_sha256",
]
