"""Tests for research artifact models, markdown integration, and service layer."""
from datetime import datetime
from pathlib import Path
import os

import pytest

from janus.models.research_artifact import (
    ARTIFACT_TYPES,
    CONFIDENCE_LEVELS,
    SOURCE_TYPES,
    Finding,
    ResearchArtifact,
    Source,
)
from janus.integrations.markdown_research import (
    RESEARCH_DIR,
    _slugify,
    _parse_artifact,
    _serialize_artifact,
    _split_frontmatter,
    _parse_simple_yaml,
    _extract_section,
    _extract_findings,
    _parse_finding_block,
    load_artifact,
    load_all_artifacts,
    save_artifact,
    update_artifact,
)
from janus.services.research_artifacts import (
    create_artifact,
    load_artifact as svc_load_artifact,
    load_all_artifacts as svc_load_all_artifacts,
    update_artifact as svc_update_artifact,
    link_finding_to_decision,
    get_artifacts_for_decision,
    get_findings_for_decision,
)


# ── Model tests ──────────────────────────────────────────────────────────

class TestSource:
    def test_valid_source(self):
        src = Source(url="https://example.com", title="Example", source_type="web")
        assert src.url == "https://example.com"
        assert src.title == "Example"
        assert src.source_type == "web"

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="url must not be empty"):
            Source(url="", title="", source_type="web")

    def test_invalid_source_type_raises(self):
        with pytest.raises(ValueError, match="Invalid source_type"):
            Source(url="https://example.com", source_type="invalid")

    @pytest.mark.parametrize("src_type", SOURCE_TYPES)
    def test_all_source_types_valid(self, src_type):
        src = Source(url="https://example.com", source_type=src_type)
        assert src.source_type == src_type


class TestFinding:
    def _make_source(self):
        return Source(url="https://example.com", source_type="web")

    def test_valid_finding(self):
        finding = Finding(
            statement="Test finding",
            sources=[self._make_source()],
        )
        assert finding.statement == "Test finding"
        assert finding.confidence == "sredni"

    @pytest.mark.parametrize("conf", CONFIDENCE_LEVELS)
    def test_all_confidence_levels(self, conf):
        finding = Finding(
            statement="Test",
            confidence=conf,
            sources=[self._make_source()],
        )
        assert finding.confidence == conf

    def test_empty_statement_raises(self):
        with pytest.raises(ValueError, match="statement must not be empty"):
            Finding(statement="", sources=[self._make_source()])

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError, match="Invalid confidence"):
            Finding(statement="Test", confidence="bad", sources=[self._make_source()])

    def test_no_sources_raises(self):
        with pytest.raises(ValueError, match="at least one source"):
            Finding(statement="Test", sources=[])

    def test_decision_numbers_dedup(self):
        finding = Finding(
            statement="Test",
            sources=[self._make_source()],
            decision_numbers=["001", "002", "001"],
        )
        assert finding.decision_numbers == ["001", "002"]

    def test_none_decision_numbers_becomes_empty(self):
        finding = Finding(
            statement="Test",
            sources=[self._make_source()],
            decision_numbers=None,
        )
        assert finding.decision_numbers == []


class TestResearchArtifact:
    def _make_finding(self):
        return Finding(
            statement="Test finding",
            sources=[Source(url="https://example.com", source_type="web")],
        )

    def test_valid_artifact(self):
        artifact = ResearchArtifact(
            title="Test Artifact",
            findings=[self._make_finding()],
        )
        assert artifact.title == "Test Artifact"
        assert artifact.artifact_type == "report"
        assert artifact.version == 1

    @pytest.mark.parametrize("art_type", ARTIFACT_TYPES)
    def test_all_artifact_types(self, art_type):
        artifact = ResearchArtifact(
            title="Test",
            artifact_type=art_type,
            findings=[self._make_finding()],
        )
        assert artifact.artifact_type == art_type

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="title must not be empty"):
            ResearchArtifact(title="", findings=[self._make_finding()])

    def test_invalid_artifact_type_raises(self):
        with pytest.raises(ValueError, match="Invalid artifact_type"):
            ResearchArtifact(title="Test", artifact_type="bad", findings=[self._make_finding()])

    def test_version_zero_raises(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            ResearchArtifact(title="Test", version=0, findings=[self._make_finding()])

    def test_invalid_finding_type_raises(self):
        with pytest.raises(ValueError, match="Finding instances"):
            ResearchArtifact(title="Test", findings=["not a finding"])

    def test_linked_goal_titles_dedup(self):
        artifact = ResearchArtifact(
            title="Test",
            findings=[self._make_finding()],
            linked_goal_titles=["A", "B", "A"],
        )
        assert artifact.linked_goal_titles == ["A", "B"]

    def test_decision_numbers_dedup(self):
        artifact = ResearchArtifact(
            title="Test",
            findings=[self._make_finding()],
            decision_numbers=["001", "002", "001"],
        )
        assert artifact.decision_numbers == ["001", "002"]


# ── YAML parsing tests ───────────────────────────────────────────────────

class TestYamlParsing:
    def test_simple_scalar(self):
        result = _parse_simple_yaml("title: My Artifact")
        assert result["title"] == "My Artifact"

    def test_quoted_scalar(self):
        result = _parse_simple_yaml('title: "My Artifact"')
        assert result["title"] == "My Artifact"

    def test_inline_list(self):
        result = _parse_simple_yaml('items: ["a", "b", "c"]')
        assert result["items"] == ["a", "b", "c"]

    def test_block_list(self):
        result = _parse_simple_yaml(
            "items:\n"
            '  - "a"\n'
            '  - "b"\n'
            '  - "c"\n'
        )
        assert result["items"] == ["a", "b", "c"]

    def test_mixed_frontmatter(self):
        text = (
            "title: Test Artifact\n"
            "artifact_type: report\n"
            "version: 1\n"
            "linked_goal_titles:\n"
            '  - "Goal One"\n'
            '  - "Goal Two"\n'
        )
        result = _parse_simple_yaml(text)
        assert result["title"] == "Test Artifact"
        assert result["artifact_type"] == "report"
        assert result["version"] == "1"
        assert result["linked_goal_titles"] == ["Goal One", "Goal Two"]


# ── Section extraction tests ─────────────────────────────────────────────

class TestSectionExtraction:
    def test_extract_summary(self):
        body = (
            "# Summary\n"
            "\n"
            "This is the summary text.\n"
            "\n"
            "# Conclusions\n"
            "\n"
            "Conclusions here.\n"
        )
        result = _extract_section(body, "Summary")
        assert result == "This is the summary text."

    def test_extract_conclusions(self):
        body = (
            "# Summary\n"
            "\n"
            "Summary text.\n"
            "\n"
            "# Conclusions\n"
            "\n"
            "Conclusions here.\n"
        )
        result = _extract_section(body, "Conclusions")
        assert result == "Conclusions here."

    def test_extract_missing_section(self):
        body = "# Something else\n\nText.\n"
        result = _extract_section(body, "Summary")
        assert result == ""


# ── Findings extraction tests ────────────────────────────────────────────

class TestFindingsExtraction:
    def test_extract_single_finding(self):
        body = (
            "# Findings\n"
            "\n"
            "## Finding 1\n"
            "\n"
            "**Statement:** The glue protein binds DNA.\n"
            "**Confidence:** wyzszy\n"
            "### Sources\n"
            "- [url](https://example.com/paper1)\n"
            "  - title: Example Paper 1\n"
            "  - type: document\n"
        )
        findings = _extract_findings(body)
        assert len(findings) == 1
        assert findings[0].statement == "The glue protein binds DNA."
        assert findings[0].confidence == "wyzszy"
        assert len(findings[0].sources) == 1
        assert findings[0].sources[0].url == "https://example.com/paper1"

    def test_extract_multiple_findings(self):
        body = (
            "# Findings\n"
            "\n"
            "## Finding 1\n"
            "\n"
            "**Statement:** First finding.\n"
            "### Sources\n"
            "- [url](https://example.com/1)\n"
            "\n"
            "## Finding 2\n"
            "\n"
            "**Statement:** Second finding.\n"
            "### Sources\n"
            "- [url](https://example.com/2)\n"
        )
        findings = _extract_findings(body)
        assert len(findings) == 2
        assert findings[0].statement == "First finding."
        assert findings[1].statement == "Second finding."

    def test_extract_finding_without_statement_skipped(self):
        body = (
            "# Findings\n"
            "\n"
            "## Finding 1\n"
            "\n"
            "### Sources\n"
            "- [url](https://example.com/1)\n"
        )
        findings = _extract_findings(body)
        assert len(findings) == 0

    def test_extract_finding_without_sources_skipped(self):
        body = (
            "# Findings\n"
            "\n"
            "## Finding 1\n"
            "\n"
            "**Statement:** No sources here.\n"
        )
        findings = _extract_findings(body)
        assert len(findings) == 0

    def test_extract_finding_with_topic(self):
        body = (
            "# Findings\n"
            "\n"
            "## Finding 1\n"
            "\n"
            "**Statement:** Test finding.\n"
            "**Topic:** Biochemistry\n"
            "### Sources\n"
            "- [url](https://example.com/1)\n"
        )
        findings = _extract_findings(body)
        assert len(findings) == 1
        assert findings[0].topic == "Biochemistry"

    def test_extract_finding_with_decision_numbers(self):
        body = (
            "# Findings\n"
            "\n"
            "## Finding 1\n"
            "\n"
            "**Statement:** Test finding.\n"
            "**Decision numbers:**\n"
            '  - "005"\n'
            '  - "007"\n'
            "### Sources\n"
            "- [url](https://example.com/1)\n"
        )
        findings = _extract_findings(body)
        assert len(findings) == 1
        assert findings[0].decision_numbers == ["005", "007"]

    def test_extract_finding_empty_decision_numbers(self):
        body = (
            "# Findings\n"
            "\n"
            "## Finding 1\n"
            "\n"
            "**Statement:** Test finding.\n"
            "**Decision numbers:** []\n"
            "### Sources\n"
            "- [url](https://example.com/1)\n"
        )
        findings = _extract_findings(body)
        assert len(findings) == 1
        assert findings[0].decision_numbers == []


# ── Round-trip serialization tests ──────────────────────────────────────

class TestRoundTrip:
    def _make_artifact(self):
        return ResearchArtifact(
            title="Test Artifact",
            artifact_type="report",
            target="GLUE biotech",
            summary="This is a summary.",
            conclusions="These are conclusions.",
            findings=[
                Finding(
                    statement="The protein binds DNA.",
                    topic="Biochemistry",
                    confidence="wyzszy",
                    sources=[
                        Source(
                            url="https://example.com/paper1",
                            title="Paper 1",
                            source_type="document",
                            accessed_at=datetime(2024, 1, 15, 10, 30, 0),
                        ),
                    ],
                    decision_numbers=["005"],
                ),
            ],
            linked_goal_titles=["GLUE biotech research"],
            decision_numbers=["005"],
        )

    def test_serialize_deserialize_roundtrip(self, tmp_path):
        artifact = self._make_artifact()
        serialized = _serialize_artifact(artifact)
        # Write to tmp and parse back
        p = tmp_path / "test.md"
        p.write_text(serialized)
        parsed = _parse_artifact(p)
        assert parsed.title == "Test Artifact"
        assert parsed.artifact_type == "report"
        assert parsed.target == "GLUE biotech"
        assert parsed.summary == "This is a summary."
        assert parsed.conclusions == "These are conclusions."
        assert len(parsed.findings) == 1
        assert parsed.findings[0].statement == "The protein binds DNA."
        assert parsed.findings[0].confidence == "wyzszy"
        assert parsed.findings[0].topic == "Biochemistry"
        assert len(parsed.findings[0].sources) == 1
        assert parsed.findings[0].sources[0].url == "https://example.com/paper1"
        assert parsed.findings[0].sources[0].title == "Paper 1"
        assert parsed.findings[0].sources[0].source_type == "document"
        assert parsed.findings[0].decision_numbers == ["005"]
        assert parsed.linked_goal_titles == ["GLUE biotech research"]
        assert parsed.decision_numbers == ["005"]


# ── Slug tests ───────────────────────────────────────────────────────────

class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_lowercase(self):
        assert _slugify("UPPER") == "upper"

    def test_spaces_to_hyphens(self):
        assert _slugify("a b c") == "a-b-c"

    def test_dedup_hyphens(self):
        assert _slugify("a  b") == "a-b"

    def test_strips_punctuation(self):
        assert _slugify("hello, world!") == "hello-world"

    def test_empty(self):
        assert _slugify("") == "untitled"


# ── Service layer tests ─────────────────────────────────────────────────

class TestResearchArtifactService:
    """Tests that use a temporary RESEARCH_DIR to avoid polluting the real repo."""

    def _make_artifact(self):
        return ResearchArtifact(
            title="Test Artifact",
            artifact_type="report",
            findings=[
                Finding(
                    statement="The protein binds DNA.",
                    sources=[Source(url="https://example.com/paper1", source_type="web")],
                ),
            ],
            summary="Summary text.",
        )

    def test_create_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setattr(RESEARCH_DIR.__class__, "_flavour", type(RESEARCH_DIR._flavour).__new__(RESEARCH_DIR.__class__.__class__) if False else RESEARCH_DIR._flavour)
        # Redirect RESEARCH_DIR to tmp_path
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        monkeypatch.setattr(
            "janus.services.research_artifacts.RESEARCH_DIR",
            tmp_path,
        )
        artifact = self._make_artifact()
        path = create_artifact(artifact)
        assert path.exists()
        assert path.suffix == ".md"

    def test_create_then_load(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        artifact = self._make_artifact()
        path = create_artifact(artifact)

        # Load it back
        loaded = load_artifact(path.stem)
        assert loaded.title == "Test Artifact"
        assert len(loaded.findings) == 1

    def test_load_all_artifacts(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        artifact = self._make_artifact()
        create_artifact(artifact)

        all_loaded = load_all_artifacts()
        assert len(all_loaded) == 1
        assert all_loaded[0].title == "Test Artifact"

    def test_load_all_artifacts_empty_dir(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        result = load_all_artifacts()
        assert result == []

    def test_load_all_artifacts_missing_dir(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path / "nonexistent")
        result = load_all_artifacts()
        assert result == []

    def test_create_duplicate_raises(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        artifact = self._make_artifact()
        create_artifact(artifact)
        with pytest.raises(ValueError, match="already exists"):
            create_artifact(artifact)

    def test_load_artifact_not_found(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        with pytest.raises(ValueError, match="not found"):
            load_artifact("nonexistent")

    def test_update_artifact(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        artifact = self._make_artifact()
        path = create_artifact(artifact)

        # Modify and update
        artifact.summary = "Updated summary."
        update_artifact(artifact, slug=path.stem)

        reloaded = load_artifact(path.stem)
        assert reloaded.summary == "Updated summary."

    def test_update_artifact_not_found(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        artifact = self._make_artifact()
        with pytest.raises(ValueError, match="not found"):
            update_artifact(artifact, slug="nonexistent")


# ── Cross-linking tests ─────────────────────────────────────────────────

class TestCrossLinking:
    """Tests for artifact↔finding↔decision cross-linking via service layer."""

    def _create_artifact_for_link(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        artifact = ResearchArtifact(
            title="Link Test Artifact",
            artifact_type="report",
            findings=[
                Finding(
                    statement="Linked finding.",
                    sources=[Source(url="https://example.com", source_type="web")],
                ),
            ],
        )
        return create_artifact(artifact)

    def test_link_finding_to_decision(self, tmp_path, monkeypatch):
        self._create_artifact_for_link(tmp_path, monkeypatch)
        result = link_finding_to_decision("Link Test Artifact", 0, "005")
        assert result is not None
        assert result.findings[0].decision_numbers == ["005"]
        assert result.decision_numbers == ["005"]

    def test_link_finding_to_decision_idempotent(self, tmp_path, monkeypatch):
        self._create_artifact_for_link(tmp_path, monkeypatch)
        link_finding_to_decision("Link Test Artifact", 0, "005")
        result = link_finding_to_decision("Link Test Artifact", 0, "005")
        assert result.findings[0].decision_numbers == ["005"]

    def test_link_finding_to_decision_out_of_range(self, tmp_path, monkeypatch):
        self._create_artifact_for_link(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="out of range"):
            link_finding_to_decision("Link Test Artifact", 99, "005")

    def test_link_finding_to_decision_not_found(self, tmp_path, monkeypatch):
        import janus.integrations.markdown_research as mod
        monkeypatch.setattr(mod, "RESEARCH_DIR", tmp_path)
        result = link_finding_to_decision("Nonexistent", 0, "005")
        assert result is None

    def test_get_artifacts_for_decision(self, tmp_path, monkeypatch):
        self._create_artifact_for_link(tmp_path, monkeypatch)
        link_finding_to_decision("Link Test Artifact", 0, "005")
        result = get_artifacts_for_decision("005")
        assert result == ["Link Test Artifact"]

    def test_get_artifacts_for_decision_none(self, tmp_path, monkeypatch):
        self._create_artifact_for_link(tmp_path, monkeypatch)
        result = get_artifacts_for_decision("099")
        assert result == []

    def test_get_findings_for_decision(self, tmp_path, monkeypatch):
        self._create_artifact_for_link(tmp_path, monkeypatch)
        link_finding_to_decision("Link Test Artifact", 0, "005")
        result = get_findings_for_decision("005")
        assert result == [("Link Test Artifact", 0)]

    def test_get_findings_for_decision_none(self, tmp_path, monkeypatch):
        self._create_artifact_for_link(tmp_path, monkeypatch)
        result = get_findings_for_decision("099")
        assert result == []
