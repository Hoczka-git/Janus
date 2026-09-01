"""Knowledge summary models — TopicBlock, KnowledgeSummary.

Intermediate representation between ResearchArtifact and Obsidian output.

Follows the existing Janus dataclass pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime

from janus.models.research_artifact import CONFIDENCE_LEVELS, Finding


def _composite_confidence(findings: list[Finding]) -> str:
    """Conservative weakest-link: a topic is only as strong as its weakest finding."""
    if not findings:
        return "sredni"
    if any(f.confidence == "niski" for f in findings):
        return "niski"
    if all(f.confidence == "wyzszy" for f in findings):
        return "wyzszy"
    return "sredni"


# Known entity aliases (static, curated list). Add more as the research domain grows.
KNOWN_ENTITIES = frozenset({
    "Roche", "Novartis", "Kymera Therapeutics", "C4 Therapeutics",
    "Monte Rosa Therapeutics", "Arvelle Therapeutics", "Karus Therapeutics",
})


def _extract_entities(artifact_target: str, findings: list[Finding]) -> list[str]:
    """Deterministic entity extraction from finding statements.

    Returns deduplicated entity names suitable for wikilinks.
    """
    entities: list[str] = []

    # Target is always an entity (the primary ticker/subject).
    if artifact_target and artifact_target not in entities:
        entities.append(artifact_target)

    # Drug/compound codes: e.g. MRT-2359, MRT-6160.
    import re
    drug_re = re.compile(r"\b([A-Z]{2,}-\d+)\b")

    seen = set(entities)
    for f in findings:
        for match in drug_re.finditer(f.statement):
            candidate = match.group(1)
            if candidate not in seen:
                entities.append(candidate)
                seen.add(candidate)
        # Known entities: match case-insensitively against statement text.
        statement_lower = f.statement.lower()
        for known in KNOWN_ENTITIES:
            if known.lower() in statement_lower and known not in seen:
                entities.append(known)
                seen.add(known)

    return entities


@dataclass
class TopicBlock:
    """Grouped findings for a single topic with composite confidence and narrative."""

    topic: str
    findings: list[Finding]
    composite_confidence: str = ""
    narrative: str = ""

    def __post_init__(self) -> None:
        if not self.topic or not self.topic.strip():
            raise ValueError("TopicBlock.topic must not be empty")
        if not self.findings:
            raise ValueError("TopicBlock must have at least one finding")
        for f in self.findings:
            if not isinstance(f, Finding):
                raise ValueError(
                    f"TopicBlock.findings must contain Finding instances, "
                    f"got {type(f).__name__}"
                )
        if self.composite_confidence and self.composite_confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"Invalid composite_confidence: {self.composite_confidence!r}. "
                f"Allowed values: {', '.join(CONFIDENCE_LEVELS)}"
            )
        if not self.composite_confidence:
            self.composite_confidence = _composite_confidence(self.findings)

    def confidence_rank(self) -> int:
        """Numeric rank for sorting: wyzszy=3, sredni=2, niski=1."""
        return {"wyzszy": 3, "sredni": 2, "niski": 1}[self.composite_confidence]


@dataclass
class KnowledgeSummary:
    """Deterministic distillation of a ResearchArtifact into a knowledge summary IR."""

    target: str
    title: str
    summary_text: str
    conclusions: str
    topic_blocks: list[TopicBlock]
    entities: list[str] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)
    source_count: int = 0
    high_confidence_count: int = 0
    low_confidence_count: int = 0
    artifact_version: int = 1
    generated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.target or not self.target.strip():
            raise ValueError("KnowledgeSummary.target must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("KnowledgeSummary.title must not be empty")
        if not self.topic_blocks:
            raise ValueError("KnowledgeSummary must have at least one topic block")
        for tb in self.topic_blocks:
            if not isinstance(tb, TopicBlock):
                raise ValueError(
                    f"KnowledgeSummary.topic_blocks must contain TopicBlock instances, "
                    f"got {type(tb).__name__}"
                )
        if self.generated_at is None:
            self.generated_at = datetime.now().astimezone()

        # Compute aggregates.
        total_sources = 0
        high = 0
        low = 0
        for tb in self.topic_blocks:
            for f in tb.findings:
                total_sources += len(f.sources)
                if f.confidence == "wyzszy":
                    high += 1
                elif f.confidence == "niski":
                    low += 1
        self.source_count = total_sources
        self.high_confidence_count = high
        self.low_confidence_count = low

        # Extract entities (unless caller supplied explicit list).
        if not self.entities:
            self.entities = _extract_entities(
                self.target,
                [f for tb in self.topic_blocks for f in tb.findings],
            )

        # Generate knowledge gaps from low-confidence findings.
        if not self.knowledge_gaps:
            self.knowledge_gaps = [
                f"Area '{tb.topic}' has low-confidence claim: '{f.statement}'"
                for tb in self.topic_blocks
                for f in tb.findings
                if f.confidence == "niski"
            ]

    def ordered_topic_blocks(self) -> list[TopicBlock]:
        """Return topic blocks sorted by confidence (highest first), then finding count (most first),
        then alphabetical (stable tiebreaker)."""
        return sorted(
            self.topic_blocks,
            key=lambda tb: (-tb.confidence_rank(), -len(tb.findings), tb.topic.lower()),
        )
