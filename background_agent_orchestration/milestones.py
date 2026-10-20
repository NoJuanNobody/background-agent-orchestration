"""Milestone progress reporting and noisy execution log suppression."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

NOISE_PATTERNS = (
    re.compile(r"\b(DEBUG|TRACE|VERBOSE|HEARTBEAT|POLL|TICK)\b", re.IGNORECASE),
    re.compile(r"^\s*(#|//|\.\.\.)"),
    re.compile(r"\b(processing chunk|scanning line|reading byte|keepalive)\b", re.IGNORECASE),
)

MILESTONE_SIGNAL_PATTERN = re.compile(
    r"(\[MILESTONE\]|STAGE_COMPLETE:|MILESTONE:)", re.IGNORECASE
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MilestoneEvent:
    """Clean, high-signal milestone notification suitable for the conversational thread."""

    contract_id: str
    stage: str
    progress_pct: float
    summary: str
    event_type: str = "stage_boundary"
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now_iso)

    def format_chat_update(self) -> str:
        """Render a concise one-line conversational update."""
        pct_str = f"{self.progress_pct:.0f}%"
        return f"[{self.contract_id} | {pct_str}] Stage '{self.stage}': {self.summary}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "stage": self.stage,
            "progress_pct": round(self.progress_pct, 2),
            "summary": self.summary,
            "event_type": self.event_type,
            "metrics": dict(self.metrics),
            "timestamp": self.timestamp,
        }


class MilestoneReporter:
    """Filters noisy execution logs and emits clean MilestoneEvent notifications at stage boundaries or threshold intervals."""

    def __init__(
        self,
        contract_id: str,
        stages: list[str] | None = None,
        threshold_pct: float = 25.0,
    ) -> None:
        if threshold_pct <= 0 or threshold_pct > 100:
            raise ValueError("threshold_pct must be between 0 (exclusive) and 100 (inclusive).")
        self.contract_id = contract_id
        self.stages = list(stages) if stages else []
        self.threshold_pct = float(threshold_pct)
        self._milestones: list[MilestoneEvent] = []
        self._completed_stages: list[str] = []
        self._last_reported_pct: float = 0.0
        self.ingested_count: int = 0
        self.suppressed_count: int = 0

    @property
    def milestones(self) -> list[MilestoneEvent]:
        """List of emitted milestone events."""
        return list(self._milestones)

    @property
    def completed_stages(self) -> list[str]:
        """Ordered list of stages reported complete."""
        return list(self._completed_stages)

    @property
    def suppression_ratio(self) -> float:
        """Fraction of ingested raw events that were suppressed as noise."""
        if self.ingested_count == 0:
            return 0.0
        return self.suppressed_count / self.ingested_count

    def _is_noisy_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return True
        if MILESTONE_SIGNAL_PATTERN.search(stripped):
            return False
        for pattern in NOISE_PATTERNS:
            if pattern.search(stripped):
                return True
        return True

    def ingest_log(
        self,
        raw_line: str,
        stage: str = "general",
        progress_pct: float | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> MilestoneEvent | None:
        """Ingest a raw execution log line; suppress noise or emit a MilestoneEvent if threshold/signal reached."""
        self.ingested_count += 1
        stripped = (raw_line or "").strip()

        if MILESTONE_SIGNAL_PATTERN.search(stripped):
            cleaned_summary = MILESTONE_SIGNAL_PATTERN.sub("", stripped).strip(" :-")
            pct = progress_pct if progress_pct is not None else self._last_reported_pct
            self._last_reported_pct = max(self._last_reported_pct, float(pct))
            event = MilestoneEvent(
                contract_id=self.contract_id,
                stage=stage,
                progress_pct=float(pct),
                summary=cleaned_summary or stripped,
                event_type="log_milestone",
                metrics=dict(metrics or {}),
            )
            self._milestones.append(event)
            return event

        if progress_pct is not None and not self._is_noisy_line(stripped):
            return self.report_progress(
                stage=stage,
                progress_pct=progress_pct,
                summary=stripped,
                metrics=metrics,
                _count_ingest=False,
            )

        if (
            progress_pct is not None
            and (progress_pct - self._last_reported_pct) >= self.threshold_pct
            and not any(p.search(stripped) for p in NOISE_PATTERNS[:1])
        ):
            return self.report_progress(
                stage=stage,
                progress_pct=progress_pct,
                summary=stripped,
                metrics=metrics,
                _count_ingest=False,
            )

        self.suppressed_count += 1
        return None

    def report_progress(
        self,
        stage: str,
        progress_pct: float,
        summary: str,
        metrics: dict[str, Any] | None = None,
        _count_ingest: bool = True,
    ) -> MilestoneEvent | None:
        """Report fine-grained progress; only emit a MilestoneEvent when crossing threshold_pct or reaching 100%."""
        if _count_ingest:
            self.ingested_count += 1

        clamped_pct = max(0.0, min(100.0, float(progress_pct)))
        delta = clamped_pct - self._last_reported_pct

        if delta >= self.threshold_pct or (clamped_pct >= 100.0 and self._last_reported_pct < 100.0):
            self._last_reported_pct = clamped_pct
            event = MilestoneEvent(
                contract_id=self.contract_id,
                stage=stage,
                progress_pct=clamped_pct,
                summary=summary.strip(),
                event_type="progress_threshold",
                metrics=dict(metrics or {}),
            )
            self._milestones.append(event)
            return event

        self.suppressed_count += 1
        return None

    def report_stage_complete(
        self,
        stage: str,
        summary: str,
        metrics: dict[str, Any] | None = None,
        progress_pct: float | None = None,
    ) -> MilestoneEvent:
        """Always emit a MilestoneEvent when a contract stage completes."""
        self.ingested_count += 1
        if stage not in self._completed_stages:
            self._completed_stages.append(stage)

        if progress_pct is not None:
            pct = max(0.0, min(100.0, float(progress_pct)))
        elif self.stages and stage in self.stages:
            idx = self.stages.index(stage) + 1
            pct = (idx / len(self.stages)) * 100.0
        elif self.stages:
            pct = min(100.0, (len(self._completed_stages) / len(self.stages)) * 100.0)
        else:
            pct = min(100.0, self._last_reported_pct + self.threshold_pct)

        self._last_reported_pct = max(self._last_reported_pct, pct)
        event = MilestoneEvent(
            contract_id=self.contract_id,
            stage=stage,
            progress_pct=pct,
            summary=summary.strip(),
            event_type="stage_boundary",
            metrics=dict(metrics or {}),
        )
        self._milestones.append(event)
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "ingested_count": self.ingested_count,
            "suppressed_count": self.suppressed_count,
            "suppression_ratio": round(self.suppression_ratio, 4),
            "emitted_count": len(self._milestones),
            "completed_stages": list(self._completed_stages),
            "milestones": [m.to_dict() for m in self._milestones],
        }
