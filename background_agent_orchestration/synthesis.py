"""Artifact integrity verification (SHA-256) and executive summary synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any

from .contract import ExecutionContract
from .lifecycle import TaskState


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_sha256(content: str | bytes) -> str:
    """Compute a lowercase hexadecimal SHA-256 digest for string or bytes content."""
    raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return hashlib.sha256(raw_bytes).hexdigest()


@dataclass
class ArtifactRecord:
    """Metadata and cryptographic checksum for a deliverable produced by a background stage."""

    name: str
    stage: str
    content: str | bytes
    sha256: str
    size_bytes: int
    verified: bool = True
    created_at: str = field(default_factory=_utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "verified": self.verified,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class SynthesisReport:
    """Final synthesis report summarizing stage completeness, verified artifacts, and executive findings."""

    contract_id: str
    objective: str
    final_state: str
    is_complete: bool
    completed_stages: list[str]
    missing_stages: list[str]
    all_artifacts_verified: bool
    artifacts: list[ArtifactRecord]
    highlights: list[str]
    executive_summary: str
    generated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "objective": self.objective,
            "final_state": self.final_state,
            "is_complete": self.is_complete,
            "completed_stages": list(self.completed_stages),
            "missing_stages": list(self.missing_stages),
            "all_artifacts_verified": self.all_artifacts_verified,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "highlights": list(self.highlights),
            "executive_summary": self.executive_summary,
            "generated_at": self.generated_at,
        }


class ArtifactSynthesizer:
    """Verifies artifact integrity via SHA-256, checks stage completeness against ExecutionContract, and builds executive summaries."""

    def __init__(self, contract: ExecutionContract) -> None:
        self.contract = contract
        self._artifacts: list[ArtifactRecord] = []

    @property
    def artifacts(self) -> list[ArtifactRecord]:
        """List of registered deliverable artifacts."""
        return list(self._artifacts)

    @staticmethod
    def compute_checksum(content: str | bytes) -> str:
        """Compute SHA-256 hex digest for artifact payload."""
        return compute_sha256(content)

    def register_artifact(
        self,
        name: str,
        stage: str,
        content: str | bytes,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        """Register a produced artifact, computing its SHA-256 digest and byte size."""
        if not name or not str(name).strip():
            raise ValueError("Artifact name must be a non-empty string.")
        if stage not in self.contract.stages:
            raise ValueError(
                f"Artifact stage '{stage}' is not declared in contract stages {self.contract.stages}."
            )
        raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        record = ArtifactRecord(
            name=name.strip(),
            stage=stage,
            content=content,
            sha256=digest,
            size_bytes=len(raw_bytes),
            verified=True,
            metadata=dict(metadata or {}),
        )
        self._artifacts.append(record)
        return record

    def verify_artifact(
        self,
        artifact: ArtifactRecord,
        expected_sha256: str | None = None,
        current_content: str | bytes | None = None,
    ) -> bool:
        """Verify that an artifact's content matches its recorded or expected SHA-256 digest."""
        payload = current_content if current_content is not None else artifact.content
        actual_digest = compute_sha256(payload)
        target_digest = expected_sha256 if expected_sha256 is not None else artifact.sha256
        is_valid = actual_digest == target_digest and len(
            payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        ) > 0
        artifact.verified = is_valid
        return is_valid

    def verify_completeness(
        self, completed_stages: list[str] | None = None
    ) -> tuple[bool, list[str]]:
        """Check whether all stages in ExecutionContract.stages have been completed or produced artifacts."""
        artifact_stages = {a.stage for a in self._artifacts}
        observed_stages = set(completed_stages or []) | artifact_stages
        missing = [s for s in self.contract.stages if s not in observed_stages]
        return (len(missing) == 0, missing)

    def format_executive_summary(
        self,
        final_state: TaskState | str,
        completed_stages: list[str],
        missing_stages: list[str],
        highlights: list[str] | None = None,
    ) -> str:
        """Format a concise Markdown executive summary for the conversational thread."""
        state_str = final_state.value if isinstance(final_state, TaskState) else str(final_state)
        total_stages = len(self.contract.stages)
        covered_count = total_stages - len(missing_stages)

        lines = [
            f"### Executive Synthesis — `{self.contract.contract_id}`",
            f"- **Objective**: {self.contract.objective}",
            f"- **Final State**: `{state_str}` (Priority: `{self.contract.priority}`)",
            f"- **Stage Coverage**: {covered_count}/{total_stages} stages complete",
        ]
        if missing_stages:
            lines.append(f"- **Missing Stages**: {', '.join(missing_stages)}")

        if highlights:
            lines.append("\n#### Key Findings")
            for item in highlights:
                lines.append(f"- {item}")

        if self._artifacts:
            lines.append("\n#### Verified Deliverables (SHA-256)")
            for art in self._artifacts:
                status_badge = "VERIFIED" if art.verified else "TAMPERED/INVALID"
                lines.append(
                    f"- `{art.name}` (stage: `{art.stage}`, {art.size_bytes} bytes, "
                    f"sha256: `{art.sha256[:16]}...`, status: **{status_badge}**)"
                )

        return "\n".join(lines)

    def synthesize(
        self,
        final_state: TaskState | str = TaskState.COMPLETED,
        completed_stages: list[str] | None = None,
        highlights: list[str] | None = None,
    ) -> SynthesisReport:
        """Verify all registered artifacts, check stage completeness, and build a SynthesisReport."""
        all_verified = all(self.verify_artifact(a) for a in self._artifacts)
        is_complete, missing = self.verify_completeness(completed_stages=completed_stages)
        covered = [s for s in self.contract.stages if s not in missing]
        state_str = final_state.value if isinstance(final_state, TaskState) else str(final_state)
        summary_md = self.format_executive_summary(
            final_state=state_str,
            completed_stages=covered,
            missing_stages=missing,
            highlights=highlights,
        )
        return SynthesisReport(
            contract_id=self.contract.contract_id,
            objective=self.contract.objective,
            final_state=state_str,
            is_complete=is_complete and all_verified,
            completed_stages=covered,
            missing_stages=missing,
            all_artifacts_verified=all_verified,
            artifacts=list(self._artifacts),
            highlights=list(highlights or []),
            executive_summary=summary_md,
        )
