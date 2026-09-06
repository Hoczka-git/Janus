"""Integration tests for the knowledge pipeline service (Phase 3)."""

from datetime import datetime, timezone

import pytest

from janus.models.knowledge_summary import KnowledgeSummary, TopicBlock
from janus.models.research_artifact import Finding, ResearchArtifact, Source
from janus.services.knowledge_pipeline import (
    PipelineValidationError,
    ValidationWarning,
    emit_knowledge_gaps_as_attention,
    generate_summary,
    validate_artifact,
)


def _src(url: str, title: str = "", stype: str = "web",
         accessed: datetime | None = None) -> Source:
    return Source(url=url, title=title, source_type=stype, accessed_at=accessed)


def _finding(statement: str, topic: str = "", confidence: str = "sredni",
             sources: list[Source] | None = None) -> Finding:
    return Finding(statement=statement, topic=topic, confidence=confidence,
                   sources=sources or [_src("http://example.com")])


# =============================================================================
# GLUE fixture
# =============================================================================

def _glue_artifact() -> ResearchArtifact:
    """Full GLUE example from design doc Section 6.2."""
    t = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
    return ResearchArtifact(
        title="Monte Rosa Therapeutics (GLUE) — Research Report — 2026-08-31",
        artifact_type="report",
        target="GLUE",
        summary="Clinical-stage biotech with MGD platform QuEEN. Roche + Novartis validation.",
        conclusions="GLUE is high-risk/high-reward. Key catalysts: MRT-6160 Phase 2, MRT-2359 Phase 2 readout.",
        findings=[
            Finding(
                statement="Market cap ~$1.88B (investing.com, 31.08.2026)",
                topic="valuation",
                confidence="niski",
                sources=[_src(
                    "https://investing.com/equities/monte-rosa-therapeutics",
                    title="investing.com GLUE",
                    accessed=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
                )],
            ),
            Finding(
                statement="Roche + Novartis partnerships: >$320M upfront, >$7.5B milestones",
                topic="partnerships",
                confidence="wyzszy",
                sources=[
                    _src(
                        "https://everyticker.com/quote/GLUE",
                        title="everyticker GLUE",
                        accessed=datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc),
                    ),
                    _src(
                        "https://investor.monte-rosa.com/news",
                        title="Company IR",
                        stype="document",
                        accessed=datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc),
                    ),
                ],
            ),
            Finding(
                statement="MRT-2359 Phase 2 in prostate cancer: 100% PSA response rate (early)",
                topic="pipeline",
                confidence="sredni",
                sources=[_src(
                    "https://quantisnow.com/ticker/GLUE",
                    title="quantisnow",
                    accessed=datetime(2026, 8, 31, 13, 0, tzinfo=timezone.utc),
                )],
            ),
        ],
        created_at=t,
        version=1,
    )


# =============================================================================
# validate_artifact — fatal errors
# =============================================================================

class TestValidateArtifactFatal:
    def test_valid_artifact_no_error(self):
        warnings = validate_artifact(_glue_artifact())
        assert isinstance(warnings, list)

    def test_empty_url_source_raises(self):
        # Source.__post_init__ already rejects empty URLs at construction time.
        # Pipeline validation is a second layer for content that passes model validation.
        # So constructing a Source with empty URL raises ValueError from the dataclass,
        # not PipelineValidationError from the pipeline.
        with pytest.raises(ValueError, match="url must not be empty"):
            Source(url="", title="bad")


# =============================================================================
# validate_artifact — warnings
# =============================================================================

class TestValidateArtifactWarnings:
    def test_future_accessed_at_warns(self):
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        art = ResearchArtifact(
            title="X",
            findings=[Finding(
                statement="X",
                sources=[_src("http://x.com", accessed=future)],
            )],
        )
        warnings = validate_artifact(art)
        future_warnings = [w for w in warnings if w.category == "freshness"]
        assert len(future_warnings) == 1
        assert "2099" in future_warnings[0].message

    def test_empty_summary_warns(self):
        art = ResearchArtifact(
            title="X", summary="", conclusions="Y",
            findings=[_finding("X")],
        )
        warnings = validate_artifact(art)
        completeness = [w for w in warnings if w.category == "completeness"]
        assert any("summary" in w.message for w in completeness)

    def test_empty_conclusions_warns(self):
        art = ResearchArtifact(
            title="X", summary="Y", conclusions="",
            findings=[_finding("X")],
        )
        warnings = validate_artifact(art)
        completeness = [w for w in warnings if w.category == "completeness"]
        assert any("conclusions" in w.message for w in completeness)

    def test_niski_finding_warns(self):
        art = ResearchArtifact(
            title="X",
            findings=[_finding("Risky claim", confidence="niski")],
        )
        warnings = validate_artifact(art)
        low_conf = [w for w in warnings if w.category == "low_confidence"]
        assert len(low_conf) == 1
        assert low_conf[0].finding_index == 0

    def test_sredni_no_low_conf_warning(self):
        art = ResearchArtifact(
            title="X",
            findings=[_finding("Safe claim", confidence="sredni")],
        )
        warnings = validate_artifact(art)
        low_conf = [w for w in warnings if w.category == "low_confidence"]
        assert len(low_conf) == 0

    def test_multiple_warnings_collected(self):
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        art = ResearchArtifact(
            title="X", summary="", conclusions="",
            findings=[
                _finding("Risky", confidence="niski"),
                _finding("Safe", confidence="sredni",
                         sources=[_src("http://x.com", accessed=future)]),
            ],
        )
        warnings = validate_artifact(art)
        assert len(warnings) >= 3  # completeness x2, low_confidence, freshness
        categories = {w.category for w in warnings}
        assert "completeness" in categories
        assert "low_confidence" in categories
        assert "freshness" in categories


# =============================================================================
# generate_summary — GLUE end-to-end
# =============================================================================

class TestGenerateSummaryGlue:
    def test_produces_knowledge_summary(self):
        ks = generate_summary(_glue_artifact())
        assert isinstance(ks, KnowledgeSummary)
        assert ks.target == "GLUE"
        assert ks.title == _glue_artifact().title
        assert ks.artifact_version == 1

    def test_topic_blocks_grouped(self):
        ks = generate_summary(_glue_artifact())
        topic_names = {tb.topic for tb in ks.topic_blocks}
        assert "valuation" in topic_names
        assert "partnerships" in topic_names
        assert "pipeline" in topic_names

    def test_composite_confidence_per_topic(self):
        ks = generate_summary(_glue_artifact())
        by_topic = {tb.topic: tb.composite_confidence for tb in ks.topic_blocks}
        assert by_topic["valuation"] == "niski"
        assert by_topic["partnerships"] == "wyzszy"
        assert by_topic["pipeline"] == "sredni"

    def test_entities_extracted(self):
        ks = generate_summary(_glue_artifact())
        assert "GLUE" in ks.entities
        assert "MRT-2359" in ks.entities
        assert "Roche" in ks.entities
        assert "Novartis" in ks.entities

    def test_knowledge_gaps_from_niski(self):
        ks = generate_summary(_glue_artifact())
        assert len(ks.knowledge_gaps) >= 1
        assert any("valuation" in g for g in ks.knowledge_gaps)

    def test_source_count_aggregate(self):
        ks = generate_summary(_glue_artifact())
        assert ks.source_count == 4  # 1 + 2 + 1

    def test_high_low_confidence_counts(self):
        ks = generate_summary(_glue_artifact())
        assert ks.high_confidence_count == 1
        assert ks.low_confidence_count == 1

    def test_summary_text_from_artifact(self):
        ks = generate_summary(_glue_artifact())
        assert ks.summary_text == _glue_artifact().summary

    def test_ordered_topics(self):
        ks = generate_summary(_glue_artifact())
        ordered = ks.ordered_topic_blocks()
        # partnerships (wyzszy) first, then pipeline (sredni), then valuation (niski)
        assert ordered[0].topic == "partnerships"
        assert ordered[-1].topic == "valuation"


# =============================================================================
# generate_summary — narrative generation
# =============================================================================

class TestNarrativeGeneration:
    def test_narrative_generated_for_each_topic(self):
        ks = generate_summary(_glue_artifact())
        for tb in ks.topic_blocks:
            assert tb.narrative
            assert len(tb.narrative) > 0

    def test_narrative_includes_finding_statements(self):
        ks = generate_summary(_glue_artifact())
        pipeline_tb = next(tb for tb in ks.topic_blocks if tb.topic == "pipeline")
        assert "MRT-2359" in pipeline_tb.narrative
        assert "PSA" in pipeline_tb.narrative

    def test_narrative_is_deterministic(self):
        """Same artifact produces same narratives across calls."""
        ks1 = generate_summary(_glue_artifact())
        ks2 = generate_summary(_glue_artifact())
        for tb1, tb2 in zip(ks1.topic_blocks, ks2.topic_blocks):
            assert tb1.narrative == tb2.narrative


# =============================================================================
# generate_summary — explicit entities/gaps
# =============================================================================

class TestExplicitEntitiesAndGaps:
    def test_explicit_entities_preserved(self):
        ks = generate_summary(
            _glue_artifact(),
            explicit_entities=["CustomEntity"],
        )
        assert "CustomEntity" in ks.entities

    def test_explicit_gaps_preserved(self):
        ks = generate_summary(
            _glue_artifact(),
            explicit_gaps=["Manual gap note"],
        )
        assert "Manual gap note" in ks.knowledge_gaps

    def test_explicit_entities_skip_extraction(self):
        """When explicit entities are provided, auto-extraction is skipped."""
        ks = generate_summary(
            _glue_artifact(),
            explicit_entities=["OnlyManual"],
        )
        assert ks.entities == ["OnlyManual"]

    def test_explicit_gaps_skip_auto_generation(self):
        """When explicit gaps are provided, auto-gap generation is skipped."""
        ks = generate_summary(
            _glue_artifact(),
            explicit_gaps=["Manual only"],
        )
        assert ks.knowledge_gaps == ["Manual only"]


# =============================================================================
# generate_summary — empty/minimal artifact
# =============================================================================

class TestMinimalArtifact:
    def test_single_finding_summary(self):
        art = ResearchArtifact(
            title="Minimal",
            target="T",
            findings=[_finding("One claim", topic="t", confidence="wyzszy")],
        )
        ks = generate_summary(art)
        assert len(ks.topic_blocks) == 1
        assert ks.topic_blocks[0].composite_confidence == "wyzszy"
        assert ks.entities == ["T"]
        assert ks.knowledge_gaps == []

    def test_empty_summary_generated_when_missing(self):
        art = ResearchArtifact(
            title="X", target="T", summary="", conclusions="",
            findings=[_finding("A", confidence="wyzszy"),
                      _finding("B", confidence="wyzszy")],
        )
        ks = generate_summary(art)
        assert ks.summary_text  # generated, not empty
        assert ks.conclusions  # generated, not empty
        assert "strong evidence" in ks.conclusions

    def test_no_gaps_when_all_high_confidence(self):
        art = ResearchArtifact(
            title="X", target="T",
            findings=[_finding("A", confidence="wyzszy"),
                      _finding("B", confidence="wyzszy")],
        )
        ks = generate_summary(art)
        assert ks.knowledge_gaps == []


# =============================================================================
# emit_knowledge_gaps_as_attention (Stage 3 bridge)
# =============================================================================

class TestEmitKnowledgeGapsAsAttention:
    def test_empty_gaps_returns_empty(self):
        ks = KnowledgeSummary(
            target="T", title="T", summary_text="T", conclusions="T",
            topic_blocks=[TopicBlock(
                topic="t",
                findings=[_finding("A", confidence="wyzszy")],
            )],
        )
        items = emit_knowledge_gaps_as_attention(ks)
        assert items == []

    def test_single_gap_produces_item(self):
        ks = KnowledgeSummary(
            target="T", title="T", summary_text="T", conclusions="T",
            topic_blocks=[TopicBlock(
                topic="t",
                findings=[_finding("X", confidence="niski")],
            )],
        )
        items = emit_knowledge_gaps_as_attention(ks)
        assert len(items) == 1
        item = items[0]
        assert item["category"] == "knowledge_gap"
        assert item["score"] == 50
        assert item["title"] == ks.knowledge_gaps[0]
        assert item["reason"] == ks.knowledge_gaps[0]

    def test_goal_title_scoped(self):
        ks = KnowledgeSummary(
            target="T", title="T", summary_text="T", conclusions="T",
            topic_blocks=[TopicBlock(
                topic="t",
                findings=[_finding("X", confidence="niski")],
            )],
        )
        items = emit_knowledge_gaps_as_attention(ks, goal_title="My Goal")
        assert len(items) == 1
        assert "[Gap]" in items[0]["title"]
        assert "My Goal" in items[0]["title"]
        assert "My Goal" in items[0]["reason"]
        assert items[0]["category"] == "knowledge_gap"

    def test_multiple_gaps(self):
        ks = KnowledgeSummary(
            target="T", title="T", summary_text="T", conclusions="T",
            topic_blocks=[
                TopicBlock(topic="a", findings=[_finding("A", confidence="niski")]),
                TopicBlock(topic="b", findings=[_finding("B", confidence="niski")]),
            ],
            knowledge_gaps=["Gap one", "Gap two", "Gap three"],
        )
        items = emit_knowledge_gaps_as_attention(ks)
        assert len(items) == 3
        assert items[0]["reason"] == "Gap one"
        assert items[1]["reason"] == "Gap two"
        assert items[2]["reason"] == "Gap three"

    def test_is_pure_no_mutation(self):
        ks = KnowledgeSummary(
            target="T", title="T", summary_text="T", conclusions="T",
            topic_blocks=[TopicBlock(
                topic="t",
                findings=[_finding("X", confidence="niski")],
            )],
        )
        gaps_before = list(ks.knowledge_gaps)
        emit_knowledge_gaps_as_attention(ks, goal_title="G")
        assert ks.knowledge_gaps == gaps_before

    def test_long_gap_truncated_in_title(self):
        long_gap = "X" * 200
        ks = KnowledgeSummary(
            target="T", title="T", summary_text="T", conclusions="T",
            topic_blocks=[TopicBlock(
                topic="t",
                findings=[_finding("X", confidence="niski")],
            )],
            knowledge_gaps=[long_gap],
        )
        items = emit_knowledge_gaps_as_attention(ks)
        assert len(items) == 1
        assert len(items[0]["title"]) <= 83  # 77 chars + "..."
        assert items[0]["reason"] == long_gap  # reason is not truncated


# =============================================================================
# Loop closure: artifact -> summary -> gaps -> attention
# =============================================================================

class TestLoopClosure:
    """End-to-end: create artifact → generate summary → emit gaps → verify."""

    def test_full_loop(self, tmp_path, monkeypatch):
        """AC6: End-to-end test of the research→finding→attention loop.

        create artifact → link to goal → generate summary → emit gaps
        → verify goal has artifact reference.
        """
        # Set up goals file with a goal
        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n\n## Goal: GLUE Research\nStatus: active\n")
        monkeypatch.setattr(
            "janus.integrations.markdown_goals.GOALS_PATH", goals_file
        )

        # Stage 1: Research → Artifact
        artifact = ResearchArtifact(
            title="GLUE Report",
            target="GLUE",
            summary="Clinical-stage biotech.",
            conclusions="High-risk/high-reward.",
            findings=[
                Finding(
                    statement="MRT-2359 Phase 2: 100% PSA response rate",
                    topic="pipeline",
                    confidence="wyzszy",
                    sources=[_src("http://example.com")],
                ),
                Finding(
                    statement="Market cap ~$1.88B (unverified)",
                    topic="valuation",
                    confidence="niski",
                    sources=[_src("http://example.com")],
                ),
            ],
            linked_goal_titles=["GLUE Research"],
        )

        # Link artifact → goal (bidirectional)
        from janus.services.artifact_linking import link_artifact_to_goal
        link_artifact_to_goal("GLUE Report", "GLUE Research", artifact)

        # Stage 2: Artifact → KnowledgeSummary
        summary = generate_summary(artifact)
        assert summary.target == "GLUE"
        assert len(summary.knowledge_gaps) >= 1

        # Stage 3: Summary → attention
        attention_items = emit_knowledge_gaps_as_attention(summary, goal_title="GLUE Research")
        assert len(attention_items) >= 1
        assert all(item["category"] == "knowledge_gap" for item in attention_items)
        assert all("GLUE Research" in item["title"] for item in attention_items)

        # Verify: goal has artifact reference (loop closure condition 1 & 2)
        from janus.services.goals import get_goal
        goal = get_goal("GLUE Research")
        assert "GLUE Report" in goal.research_artifact_titles  # type: ignore[operator]
        assert "GLUE Research" in artifact.linked_goal_titles
