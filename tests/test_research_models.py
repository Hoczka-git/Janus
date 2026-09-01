"""Tests for research artifact and knowledge summary models (Phase 1-2)."""

from datetime import datetime, timezone

import pytest

from janus.models.knowledge_summary import (
    KNOWN_ENTITIES,
    KnowledgeSummary,
    TopicBlock,
    _composite_confidence,
    _extract_entities,
)
from janus.models.research_artifact import (
    ARTIFACT_TYPES,
    CONFIDENCE_LEVELS,
    SOURCE_TYPES,
    Finding,
    ResearchArtifact,
    Source,
)


# =============================================================================
# Fixtures
# =============================================================================

def _src(url: str, title: str = "", stype: str = "web",
         accessed: datetime | None = None) -> Source:
    return Source(url=url, title=title, source_type=stype, accessed_at=accessed)


def _finding(statement: str, topic: str = "", confidence: str = "sredni",
             sources: list[Source] | None = None) -> Finding:
    return Finding(statement=statement, topic=topic, confidence=confidence,
                   sources=sources or [_src("http://example.com")])


# =============================================================================
# Source
# =============================================================================

class TestSource:
    def test_basic_construction(self):
        s = Source(url="https://example.com", title="Example", source_type="web")
        assert s.url == "https://example.com"
        assert s.title == "Example"
        assert s.source_type == "web"
        assert s.accessed_at is None

    def test_with_accessed_at(self):
        t = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
        s = Source(url="https://example.com", accessed_at=t)
        assert s.accessed_at == t

    def test_empty_url_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            Source(url="")

    def test_empty_url_whitespace_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            Source(url="   ")

    def test_invalid_source_type_rejected(self):
        with pytest.raises(ValueError, match="Invalid source_type"):
            Source(url="http://x.com", source_type="invalid")

    def test_all_valid_source_types(self):
        for st in SOURCE_TYPES:
            s = Source(url="http://x.com", source_type=st)
            assert s.source_type == st


# =============================================================================
# Finding
# =============================================================================

class TestFinding:
    def test_basic_construction(self):
        f = Finding(statement="Cash ~$107M", topic="finances", confidence="sredni",
                    sources=[_src("http://example.com")])
        assert f.statement == "Cash ~$107M"
        assert f.topic == "finances"
        assert f.confidence == "sredni"
        assert len(f.sources) == 1

    def test_default_confidence_is_sredni(self):
        f = Finding(statement="X", sources=[_src("http://x.com")])
        assert f.confidence == "sredni"

    def test_default_topic_is_empty(self):
        f = Finding(statement="X", sources=[_src("http://x.com")])
        assert f.topic == ""

    def test_empty_statement_rejected(self):
        with pytest.raises(ValueError, match="statement must not be empty"):
            Finding(statement="", sources=[_src("http://x.com")])

    def test_whitespace_statement_rejected(self):
        with pytest.raises(ValueError, match="statement must not be empty"):
            Finding(statement="   ", sources=[_src("http://x.com")])

    def test_no_sources_rejected(self):
        with pytest.raises(ValueError, match="at least one source"):
            Finding(statement="Unsupported claim", sources=[])

    def test_default_factory_sources_is_empty_list(self):
        with pytest.raises(ValueError, match="at least one source"):
            Finding(statement="No sources")

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValueError, match="Invalid confidence"):
            Finding(statement="X", confidence="uzy", sources=[_src("http://x.com")])

    def test_all_valid_confidence_levels(self):
        for c in CONFIDENCE_LEVELS:
            f = Finding(statement="X", confidence=c, sources=[_src("http://x.com")])
            assert f.confidence == c

    def test_sources_must_be_Source_instances(self):
        with pytest.raises(ValueError, match="must contain Source instances"):
            Finding(statement="X", sources=["not a source"])  # type: ignore[arg-type]

    def test_multiple_sources(self):
        s1 = _src("http://a.com", "A")
        s2 = _src("http://b.com", "B", stype="document")
        f = Finding(statement="X", sources=[s1, s2])
        assert len(f.sources) == 2
        assert f.sources[0].title == "A"
        assert f.sources[1].source_type == "document"


# =============================================================================
# ResearchArtifact
# =============================================================================

class TestResearchArtifact:
    def test_basic_construction(self):
        t = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
        a = ResearchArtifact(
            title="GLUE Report",
            artifact_type="report",
            target="GLUE",
            summary="Summary text",
            conclusions="Conclusion text",
            findings=[_finding("Cash ~$107M", topic="finances", confidence="sredni",
                               sources=[_src("http://example.com")])],
            version=1,
            created_at=t,
        )
        assert a.title == "GLUE Report"
        assert a.target == "GLUE"
        assert a.artifact_type == "report"
        assert a.version == 1
        assert a.created_at == t
        assert len(a.findings) == 1

    def test_default_artifact_type_is_report(self):
        a = ResearchArtifact(
            title="X",
            findings=[_finding("X", sources=[_src("http://x.com")])]
        )
        assert a.artifact_type == "report"

    def test_default_version_is_1(self):
        a = ResearchArtifact(
            title="X",
            findings=[_finding("X", sources=[_src("http://x.com")])]
        )
        assert a.version == 1

    def test_empty_title_rejected(self):
        with pytest.raises(ValueError, match="title must not be empty"):
            ResearchArtifact(title="", findings=[])

    def test_whitespace_title_rejected(self):
        with pytest.raises(ValueError, match="title must not be empty"):
            ResearchArtifact(title="   ", findings=[])

    def test_invalid_artifact_type_rejected(self):
        with pytest.raises(ValueError, match="Invalid artifact_type"):
            ResearchArtifact(title="X", artifact_type="invalid", findings=[])

    def test_version_below_1_rejected(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            ResearchArtifact(title="X", version=0, findings=[])

    def test_negative_version_rejected(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            ResearchArtifact(title="X", version=-1, findings=[])

    def test_findings_must_be_Finding_instances(self):
        with pytest.raises(ValueError, match="must contain Finding instances"):
            ResearchArtifact(title="X", findings=["not a finding"])  # type: ignore[arg-type]

    def test_all_valid_artifact_types(self):
        for at in ARTIFACT_TYPES:
            a = ResearchArtifact(
                title="X", artifact_type=at,
                findings=[_finding("X", sources=[_src("http://x.com")])]
            )
            assert a.artifact_type == at

    def test_full_glue_fixture(self):
        """Construct the full GLUE example from the design doc Section 6.2."""
        t = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
        a = ResearchArtifact(
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
        assert a.target == "GLUE"
        assert len(a.findings) == 3
        assert a.findings[0].confidence == "niski"
        assert a.findings[1].confidence == "wyzszy"
        assert a.findings[1].sources[1].source_type == "document"

    def test_constructing_artifact_without_findings(self):
        """Artifact with no findings is valid (findings default to [])."""
        a = ResearchArtifact(title="Empty Report", findings=[])
        assert a.findings == []


# =============================================================================
# Composite confidence
# =============================================================================

class TestCompositeConfidence:
    def test_all_wyzszy_yields_wyzszy(self):
        findings = [
            Finding(statement="A", confidence="wyzszy", sources=[_src("http://a.com")]),
            Finding(statement="B", confidence="wyzszy", sources=[_src("http://b.com")]),
        ]
        assert _composite_confidence(findings) == "wyzszy"

    def test_any_niski_yields_niski(self):
        findings = [
            Finding(statement="A", confidence="wyzszy", sources=[_src("http://a.com")]),
            Finding(statement="B", confidence="niski", sources=[_src("http://b.com")]),
        ]
        assert _composite_confidence(findings) == "niski"

    def test_mixed_sredni_niski_yields_niski(self):
        findings = [
            Finding(statement="A", confidence="sredni", sources=[_src("http://a.com")]),
            Finding(statement="B", confidence="niski", sources=[_src("http://b.com")]),
        ]
        assert _composite_confidence(findings) == "niski"

    def test_all_sredni_yields_sredni(self):
        findings = [
            Finding(statement="A", confidence="sredni", sources=[_src("http://a.com")]),
            Finding(statement="B", confidence="sredni", sources=[_src("http://b.com")]),
        ]
        assert _composite_confidence(findings) == "sredni"

    def test_single_wyzszy(self):
        findings = [Finding(statement="A", confidence="wyzszy", sources=[_src("http://a.com")])]
        assert _composite_confidence(findings) == "wyzszy"

    def test_single_sredni(self):
        findings = [Finding(statement="A", confidence="sredni", sources=[_src("http://a.com")])]
        assert _composite_confidence(findings) == "sredni"

    def test_single_niski(self):
        findings = [Finding(statement="A", confidence="niski", sources=[_src("http://a.com")])]
        assert _composite_confidence(findings) == "niski"

    def test_empty_findings_returns_sredni(self):
        assert _composite_confidence([]) == "sredni"


# =============================================================================
# TopicBlock
# =============================================================================

class TestTopicBlock:
    def test_basic_construction(self):
        f = _finding("Cash ~$107M", topic="finances", confidence="sredni",
                     sources=[_src("http://example.com")])
        tb = TopicBlock(topic="finances", findings=[f])
        assert tb.topic == "finances"
        assert len(tb.findings) == 1
        assert tb.composite_confidence == "sredni"

    def test_composite_confidence_derived(self):
        f_niski = _finding("X", confidence="niski", sources=[_src("http://a.com")])
        tb = TopicBlock(topic="t", findings=[f_niski])
        assert tb.composite_confidence == "niski"

    def test_composite_confidence_override(self):
        f = _finding("X", confidence="wyzszy", sources=[_src("http://a.com")])
        tb = TopicBlock(topic="t", findings=[f], composite_confidence="sredni")
        assert tb.composite_confidence == "sredni"

    def test_empty_topic_rejected(self):
        f = _finding("X", sources=[_src("http://x.com")])
        with pytest.raises(ValueError, match="topic must not be empty"):
            TopicBlock(topic="", findings=[f])

    def test_no_findings_rejected(self):
        with pytest.raises(ValueError, match="at least one finding"):
            TopicBlock(topic="t", findings=[])

    def test_invalid_composite_confidence_rejected(self):
        f = _finding("X", confidence="wyzszy", sources=[_src("http://x.com")])
        with pytest.raises(ValueError, match="Invalid composite_confidence"):
            TopicBlock(topic="t", findings=[f], composite_confidence="uzy")

    def test_findings_must_be_Finding_instances(self):
        with pytest.raises(ValueError, match="must contain Finding instances"):
            TopicBlock(topic="t", findings=["not a finding"])  # type: ignore[arg-type]

    def test_confidence_rank(self):
        f_s = _finding("X", confidence="sredni", sources=[_src("http://x.com")])
        f_w = _finding("X", confidence="wyzszy", sources=[_src("http://x.com")])
        f_n = _finding("X", confidence="niski", sources=[_src("http://x.com")])
        assert TopicBlock(topic="a", findings=[f_w]).confidence_rank() == 3
        assert TopicBlock(topic="a", findings=[f_s]).confidence_rank() == 2
        assert TopicBlock(topic="a", findings=[f_n]).confidence_rank() == 1


# =============================================================================
# Entity extraction
# =============================================================================

class TestEntityExtraction:
    def test_target_is_entity(self):
        entities = _extract_entities("GLUE", [])
        assert "GLUE" in entities

    def test_drug_codes_extracted(self):
        findings = [
            Finding(statement="MRT-2359 Phase 2 in prostate cancer",
                    sources=[_src("http://x.com")]),
            Finding(statement="MRT-6160 Phase 1 data",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert "MRT-2359" in entities
        assert "MRT-6160" in entities

    def test_known_entities_extracted(self):
        findings = [
            Finding(statement="Roche and Novartis partnerships",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert "Roche" in entities
        assert "Novartis" in entities

    def test_no_duplicate_entities(self):
        findings = [
            Finding(statement="MRT-2359 Phase 2 and MRT-2359 Phase 1 data",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert entities.count("MRT-2359") == 1

    def test_target_not_duplicated(self):
        findings = [
            Finding(statement="GLUE is a biotech company",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert entities.count("GLUE") == 1

    def test_empty_findings_only_target(self):
        entities = _extract_entities("GLUE", [])
        assert entities == ["GLUE"]

    def test_order_is_target_first_then_discovery_order(self):
        findings = [
            Finding(statement="MRT-2359 Phase 2 data",
                    sources=[_src("http://x.com")]),
            Finding(statement="Roche partnership",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert entities[0] == "GLUE"
        assert "MRT-2359" in entities
        assert "Roche" in entities

    def test_case_insensitive_known_entity_match(self):
        findings = [
            Finding(statement="roche and novartis announced today",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert "Roche" in entities
        assert "Novartis" in entities

    def test_partial_ticker_not_extracted(self):
        """'PSA' alone should not be extracted as a ticker."""
        findings = [
            Finding(statement="PSA response rate of 100%",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert "PSA" not in entities
        assert entities == ["GLUE"]

    def test_ticker_in_drug_code_not_duplicate(self):
        """MRT from MRT-2359 should not appear separately."""
        findings = [
            Finding(statement="MRT-2359 Phase 2 data for MRT-6160",
                    sources=[_src("http://x.com")]),
        ]
        entities = _extract_entities("GLUE", findings)
        assert "MRT" not in entities
        assert "MRT-2359" in entities
        assert "MRT-6160" in entities


# =============================================================================
# KnowledgeSummary
# =============================================================================

class TestKnowledgeSummary:
    def test_basic_construction(self):
        tb = TopicBlock(
            topic="partnerships",
            findings=[_finding("Roche deal", confidence="wyzszy",
                               sources=[_src("http://a.com"), _src("http://b.com")])]
        )
        ks = KnowledgeSummary(
            target="GLUE",
            title="GLUE Summary",
            summary_text="Clinical-stage biotech.",
            conclusions="High-risk/high-reward.",
            topic_blocks=[tb],
            artifact_version=1,
        )
        assert ks.target == "GLUE"
        assert ks.title == "GLUE Summary"
        assert ks.artifact_version == 1
        assert len(ks.topic_blocks) == 1
        assert ks.source_count == 2
        assert ks.high_confidence_count == 1
        assert ks.low_confidence_count == 0

    def test_source_count_aggregate(self):
        f1 = _finding("A", confidence="wyzszy",
                      sources=[_src("http://a.com"), _src("http://b.com")])
        f2 = _finding("B", confidence="niski", sources=[_src("http://c.com")])
        tb1 = TopicBlock(topic="t1", findings=[f1])
        tb2 = TopicBlock(topic="t2", findings=[f2])
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[tb1, tb2],
        )
        assert ks.source_count == 3

    def test_high_confidence_count(self):
        f_w = _finding("A", confidence="wyzszy", sources=[_src("http://a.com")])
        f_s = _finding("B", confidence="sredni", sources=[_src("http://b.com")])
        f_n = _finding("C", confidence="niski", sources=[_src("http://c.com")])
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[TopicBlock(topic="t1", findings=[f_w, f_s, f_n])],
        )
        assert ks.high_confidence_count == 1
        assert ks.low_confidence_count == 1

    def test_entities_extracted(self):
        f = _finding("MRT-2359 Phase 2 and Roche partnership",
                     sources=[_src("http://x.com")])
        ks = KnowledgeSummary(
            target="GLUE", title="X", summary_text="X", conclusions="X",
            topic_blocks=[TopicBlock(topic="pipeline", findings=[f])],
        )
        assert "GLUE" in ks.entities
        assert "MRT-2359" in ks.entities
        assert "Roche" in ks.entities

    def test_explicit_entities_preserved(self):
        """When entities are supplied, extraction is skipped."""
        f = _finding("X", sources=[_src("http://x.com")])
        ks = KnowledgeSummary(
            target="GLUE", title="X", summary_text="X", conclusions="X",
            topic_blocks=[TopicBlock(topic="t", findings=[f])],
            entities=["CustomEntity"],
        )
        assert ks.entities == ["CustomEntity"]

    def test_knowledge_gaps_from_low_confidence(self):
        f_n = _finding("Market cap ~$1.88B", confidence="niski",
                       sources=[_src("http://x.com")])
        f_w = _finding("Roche deal >$320M", confidence="wyzszy",
                       sources=[_src("http://x.com")])
        ks = KnowledgeSummary(
            target="GLUE", title="X", summary_text="X", conclusions="X",
            topic_blocks=[
                TopicBlock(topic="valuation", findings=[f_n]),
                TopicBlock(topic="partnerships", findings=[f_w]),
            ],
        )
        assert len(ks.knowledge_gaps) == 1
        assert "valuation" in ks.knowledge_gaps[0]
        assert "Market cap ~$1.88B" in ks.knowledge_gaps[0]

    def test_no_gaps_when_no_low_confidence(self):
        f = _finding("X", confidence="wyzszy", sources=[_src("http://x.com")])
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[TopicBlock(topic="t", findings=[f])],
        )
        assert ks.knowledge_gaps == []

    def test_generated_at_set_automatically(self):
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[TopicBlock(
                topic="t",
                findings=[_finding("X", sources=[_src("http://x.com")])]
            )],
        )
        assert ks.generated_at is not None

    def test_generated_at_can_be_set_explicitly(self):
        t = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[TopicBlock(
                topic="t",
                findings=[_finding("X", sources=[_src("http://x.com")])]
            )],
            generated_at=t,
        )
        assert ks.generated_at == t

    def test_empty_target_rejected(self):
        with pytest.raises(ValueError, match="target must not be empty"):
            KnowledgeSummary(
                target="", title="X", summary_text="X", conclusions="X",
                topic_blocks=[TopicBlock(
                    topic="t",
                    findings=[_finding("X", sources=[_src("http://x.com")])]
                )],
            )

    def test_empty_title_rejected(self):
        with pytest.raises(ValueError, match="title must not be empty"):
            KnowledgeSummary(
                target="X", title="", summary_text="X", conclusions="X",
                topic_blocks=[TopicBlock(
                    topic="t",
                    findings=[_finding("X", sources=[_src("http://x.com")])]
                )],
            )

    def test_no_topic_blocks_rejected(self):
        with pytest.raises(ValueError, match="at least one topic block"):
            KnowledgeSummary(
                target="X", title="X", summary_text="X", conclusions="X",
                topic_blocks=[],
            )

    def test_topic_blocks_must_be_TopicBlock_instances(self):
        with pytest.raises(ValueError, match="must contain TopicBlock instances"):
            KnowledgeSummary(
                target="X", title="X", summary_text="X", conclusions="X",
                topic_blocks=["not a topic block"],  # type: ignore[arg-type]
            )


# =============================================================================
# Topic ordering
# =============================================================================

class TestTopicOrdering:
    def test_ordered_by_confidence_desc(self):
        f_n = _finding("A", confidence="niski", sources=[_src("http://a.com")])
        f_w = _finding("B", confidence="wyzszy", sources=[_src("http://b.com")])
        f_s = _finding("C", confidence="sredni", sources=[_src("http://c.com")])
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[
                TopicBlock(topic="low", findings=[f_n]),
                TopicBlock(topic="high", findings=[f_w]),
                TopicBlock(topic="mid", findings=[f_s]),
            ],
        )
        ordered = ks.ordered_topic_blocks()
        assert [tb.topic for tb in ordered] == ["high", "mid", "low"]

    def test_same_confidence_ordered_by_finding_count_desc(self):
        f1 = _finding("A", sources=[_src("http://a.com")])
        f2 = _finding("B", sources=[_src("http://b.com")])
        f3 = _finding("C", sources=[_src("http://c.com")])
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[
                TopicBlock(topic="many", findings=[f1, f2, f3]),
                TopicBlock(topic="few", findings=[f1]),
            ],
        )
        ordered = ks.ordered_topic_blocks()
        assert [tb.topic for tb in ordered] == ["many", "few"]

    def test_same_confidence_and_count_ordered_alphabetically(self):
        f1 = _finding("A", sources=[_src("http://a.com")])
        f2 = _finding("B", sources=[_src("http://b.com")])
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[
                TopicBlock(topic="zebra", findings=[f1]),
                TopicBlock(topic="apple", findings=[f2]),
            ],
        )
        ordered = ks.ordered_topic_blocks()
        assert [tb.topic for tb in ordered] == ["apple", "zebra"]

    def test_stable_deterministic_order(self):
        """Same input produces same order across calls."""
        f1 = _finding("A", sources=[_src("http://a.com")])
        f2 = _finding("B", sources=[_src("http://b.com")])
        ks = KnowledgeSummary(
            target="X", title="X", summary_text="X", conclusions="X",
            topic_blocks=[
                TopicBlock(topic="b", findings=[f1]),
                TopicBlock(topic="a", findings=[f2]),
            ],
        )
        first = ks.ordered_topic_blocks()
        second = ks.ordered_topic_blocks()
        assert [tb.topic for tb in first] == [tb.topic for tb in second]
