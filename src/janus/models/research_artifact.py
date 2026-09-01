"""Research artifact models — Source, Finding, ResearchArtifact.

Dataclasses with __post_init__ validation. Follows the existing Janus
models/ pattern (task.py, goal.py).

Canonical storage is git-tracked markdown; these models are the structured
in-memory representation that serializes to/from that markdown.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

CONFIDENCE_LEVELS = ("niski", "sredni", "wyzszy")
SOURCE_TYPES = ("web", "document", "api", "dataset", "interview")
ARTIFACT_TYPES = ("report", "note", "analysis", "thesis")


@dataclass
class Source:
    """A single cited origin (URL, document, dataset, API, interview)."""

    url: str
    title: str = ""
    accessed_at: datetime | None = None
    source_type: str = "web"

    def __post_init__(self) -> None:
        if not self.url or not self.url.strip():
            raise ValueError("Source.url must not be empty")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type: {self.source_type!r}. "
                f"Allowed values: {', '.join(SOURCE_TYPES)}"
            )


@dataclass
class Finding:
    """An atomic claim or data point, with per-finding confidence and sources."""

    statement: str
    topic: str = ""
    confidence: str = "sredni"
    sources: list[Source] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.statement or not self.statement.strip():
            raise ValueError("Finding.statement must not be empty")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"Invalid confidence: {self.confidence!r}. "
                f"Allowed values: {', '.join(CONFIDENCE_LEVELS)}"
            )
        if not self.sources:
            raise ValueError(
                "Finding must have at least one source (zero sources = unsupported claim)"
            )
        for src in self.sources:
            if not isinstance(src, Source):
                raise ValueError(
                    f"Finding.sources must contain Source instances, got {type(src).__name__}"
                )


@dataclass
class ResearchArtifact:
    """Top-level container for a structured research output."""

    title: str
    artifact_type: str = "report"
    summary: str = ""
    conclusions: str = ""
    findings: list[Finding] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1
    target: str = ""

    def __post_init__(self) -> None:
        if not self.title or not self.title.strip():
            raise ValueError("ResearchArtifact.title must not be empty")
        if self.artifact_type not in ARTIFACT_TYPES:
            raise ValueError(
                f"Invalid artifact_type: {self.artifact_type!r}. "
                f"Allowed values: {', '.join(ARTIFACT_TYPES)}"
            )
        if self.version < 1:
            raise ValueError(f"ResearchArtifact.version must be >= 1, got {self.version}")
        for f in self.findings:
            if not isinstance(f, Finding):
                raise ValueError(
                    f"ResearchArtifact.findings must contain Finding instances, "
                    f"got {type(f).__name__}"
                )
