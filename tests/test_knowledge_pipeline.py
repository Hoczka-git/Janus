"""Tests for the knowledge summary pipeline — Phases 3, 4, and 5.

Phase 5: end-to-end tests covering the full promotion flow from research
artifact through the curation gate to the Obsidian promotion record.

See: docs/guides/knowledge_summary_obsidian_pipeline_design.md
     docs/specs/research_knowledge_pipeline_specification.md
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from janus.models.curation_proposal import (
    CurationGateState,
    CurationProposal,
    CurationGateError,
    StaleStateError,
)
from janus.models.knowledge_summary import (
    KnowledgeSummary,
    TopicBlock,
)
from janus.models.research_artifact import (
    CONFIDENCE_LEVELS,
    Finding,
    ResearchArtifact,
    Source,
)
from janus.services.knowledge_pipeline import (
    validate_artifact,
    generate_summary,
)
from janus.services.obsidian_promoter import (
    propose_note_content,
    curate_proposal,
    expire_stale_proposals,
    promote_to_obsidian,
    persist_promotion_record,
    load_record,
    _resolve_vault,
    _is_vault_unconfigured,
)


# =============================================================================
# Helpers
# =============================================================================

def _mk_source(url: str = "https://example.com",
               title: str = "Example",
               source_type: str = "web") -> Source:
    return Source(url=url, title=title,
                  accessed_at=datetime.now(timezone.utc),
                  source_type=source_type)


def _mk_finding(statement: str,
                topic: str = "test",
                confidence: str = "wyzszy",
                url: str = "https://example.com") -> Finding:
    return Finding(statement=statement, topic=topic,
                   confidence=confidence, sources=[_mk_source(url=url)])


def _mk_artifact(title: str = "Test",
                 target: str = "research",
                 summary: str = "Test summary",
                 conclusions: str = "Test conclusions",
                 findings: list[Finding] | None = None,
                 version: int = 1,
                 ) -> ResearchArtifact:
    return ResearchArtifact(
        title=title,
        summary=summary,
        conclusions=conclusions,
        findings=findings or [_mk_finding(f"Finding for {title}")],
        version=version,
        target=target,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _mk_summary(title: str = "Test",
                target: str = "research",
                topic_blocks: list[TopicBlock] | None = None,
                knowledge_gaps: list[str] | None = None,
                ) -> KnowledgeSummary:
    tb = topic_blocks or [
        TopicBlock(topic="test", findings=[
            _mk_finding(f"Finding for {title}"),
        ]),
    ]
    return KnowledgeSummary(
        title=title,
        target=target,
        summary_text=f"Summary for {title}",
        conclusions=f"Conclusions for {title}",
        topic_blocks=tb,
        knowledge_gaps=knowledge_gaps or [],
        generated_at=datetime.now(timezone.utc),
    )


def _mk_proposal(slug: str = "test-proposal",
                 state: CurationGateState = CurationGateState.PENDING,
                 ) -> CurationProposal:
    now = datetime.now(timezone.utc)
    return CurationProposal(
        slug=slug,
        artifact_title="Test Artifact",
        target="research",
        note_content="# Test Artifact\n\nSome note content.",
        finding_indices=(0,),
        source_path=None,
        decision_adr="ADR-002",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        state=state,
    )


# =============================================================================
# Phase 3: Curation Gate — State Transitions
# =============================================================================

class TestCurationGateStateTransitions:
    """CurationProposal transitions: approve / reject / cancel / expire."""

    def test_approve_transitions_pending_to_approved(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        approved = p.approve()
        assert approved.state == CurationGateState.APPROVED
        assert p.state == CurationGateState.PENDING  # original unchanged

    def test_reject_transitions_pending_to_rejected(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        rejected = p.reject(reason="not needed")
        assert rejected.state == CurationGateState.REJECTED

    def test_cancel_transitions_pending_to_cancelled(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        cancelled = p.cancel()
        assert cancelled.state == CurationGateState.CANCELLED

    def test_expire_transitions_pending_to_expired(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        expired = p.expire()
        assert expired.state == CurationGateState.EXPIRED

    def test_approve_from_non_pending_raises_stale_state(self) -> None:
        p = _mk_proposal(state=CurationGateState.APPROVED)
        with pytest.raises(StaleStateError,
                           match="Cannot approve proposal in state approved"):
            p.approve()

    def test_reject_from_approved_raises_stale_state(self) -> None:
        p = _mk_proposal(state=CurationGateState.APPROVED)
        with pytest.raises(StaleStateError,
                           match="Cannot reject proposal in state approved"):
            p.reject()

    def test_cancel_from_approved_raises_stale_state(self) -> None:
        p = _mk_proposal(state=CurationGateState.APPROVED)
        with pytest.raises(StaleStateError,
                           match="Cannot cancel proposal in state approved"):
            p.cancel()

    def test_approve_is_immutable(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        _ = p.approve()
        assert p.state == CurationGateState.PENDING

    def test_reject_is_immutable(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        _ = p.reject()
        assert p.state == CurationGateState.PENDING

    def test_cancel_is_immutable(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        _ = p.cancel()
        assert p.state == CurationGateState.PENDING

    def test_expire_is_immutable(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        _ = p.expire()
        assert p.state == CurationGateState.PENDING

    def test_content_hash_is_deterministic(self) -> None:
        p1 = _mk_proposal(slug="alpha")
        p2 = _mk_proposal(slug="alpha")
        assert p1.content_hash == p2.content_hash

    def test_content_hash_changes_with_content(self) -> None:
        p1 = CurationProposal(
            slug="test", artifact_title="T", target="r",
            note_content="# A\n", finding_indices=(),
            source_path=None, decision_adr="ADR-002",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        p2 = CurationProposal(
            slug="test", artifact_title="T", target="r",
            note_content="# B\n", finding_indices=(),
            source_path=None, decision_adr="ADR-002",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert p1.content_hash != p2.content_hash

    def test_is_conflicting_matches_same_slug_both_pending(self) -> None:
        a = _mk_proposal(slug="same")
        b = _mk_proposal(slug="same")
        assert a.is_conflicting_with(b)
        assert b.is_conflicting_with(a)

    def test_is_conflicting_returns_false_when_different_slug(self) -> None:
        a = _mk_proposal(slug="alpha")
        b = _mk_proposal(slug="beta")
        assert not a.is_conflicting_with(b)

    def test_is_conflicting_returns_false_when_one_not_pending(self) -> None:
        a = _mk_proposal(slug="same", state=CurationGateState.APPROVED)
        b = _mk_proposal(slug="same", state=CurationGateState.PENDING)
        assert not a.is_conflicting_with(b)
        assert not b.is_conflicting_with(a)

    def test_is_terminal_true_for_approved(self) -> None:
        p = _mk_proposal(state=CurationGateState.APPROVED)
        assert p.is_terminal

    def test_is_terminal_true_for_rejected(self) -> None:
        p = _mk_proposal(state=CurationGateState.REJECTED)
        assert p.is_terminal

    def test_is_terminal_true_for_cancelled(self) -> None:
        p = _mk_proposal(state=CurationGateState.CANCELLED)
        assert p.is_terminal

    def test_is_terminal_true_for_expired(self) -> None:
        p = _mk_proposal(state=CurationGateState.EXPIRED)
        assert p.is_terminal

    def test_is_terminal_false_for_pending(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        assert not p.is_terminal

    def test_expiry_window_positive_defaults_to_one_hour(self) -> None:
        p = _mk_proposal()
        delta = p.expires_at - p.created_at
        assert timedelta(0) < delta <= timedelta(hours=2)

    def test_from_summary_builds_valid_proposal(self) -> None:
        summary = _mk_summary(title="Test Company", target="research")
        p = CurationProposal.from_summary(summary, source_path=None, ttl_seconds=3600)
        assert p.slug == "test-company"
        assert p.artifact_title == "Test Company"
        assert p.target == "research"
        assert CurationGateState.PENDING == p.state
        assert p.note_content
        assert len(p.note_content) > 0
        assert p.content_hash

    def test_from_summary_with_finding_indices(self) -> None:
        tb1 = TopicBlock(topic="t1", findings=[_mk_finding("f1"), _mk_finding("f2")])
        tb2 = TopicBlock(topic="t2", findings=[_mk_finding("f3")])
        summary = _mk_summary(title="T", target="r",
                              topic_blocks=[tb1, tb2])
        p = CurationProposal.from_summary(summary, finding_indices=(0, 2),
                                          source_path=None)
        assert p.finding_indices == (0, 2)

    def test_from_summary_default_indices_all_blocks(self) -> None:
        tb1 = TopicBlock(topic="t1", findings=[_mk_finding("f1")])
        tb2 = TopicBlock(topic="t2", findings=[_mk_finding("f2")])
        summary = _mk_summary(title="T", target="r",
                              topic_blocks=[tb1, tb2])
        p = CurationProposal.from_summary(summary, source_path=None)
        assert len(p.finding_indices) == 2


# =============================================================================
# Phase 3: curate_proposal dispatcher
# =============================================================================

class TestCurateProposalDispatcher:
    """curate_proposal maps string actions onto Proposal transitions."""

    def test_approve_dispatches(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        out = curate_proposal(p, "approve")
        assert out.state == CurationGateState.APPROVED

    def test_reject_dispatches(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        out = curate_proposal(p, "reject")
        assert out.state == CurationGateState.REJECTED

    def test_cancel_dispatches(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        out = curate_proposal(p, "cancel")
        assert out.state == CurationGateState.CANCELLED

    def test_unknown_action_raises_curation_gate_error(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        with pytest.raises(CurationGateError,
                           match="Unknown curation action"):
            curate_proposal(p, "bogus")

    def test_approve_preserves_immutability(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        _ = curate_proposal(p, "approve")
        assert p.state == CurationGateState.PENDING


# =============================================================================
# Phase 3: expire_stale_proposals
# =============================================================================

class TestExpireStaleProposals:
    """expire_stale_proposals ages out past-TTL PENDING proposals."""

    def test_expires_pending_past_ttl(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)
        p = CurationProposal(
            slug="x", artifact_title="X", target="r",
            note_content="# x", finding_indices=(),
            source_path=None, decision_adr="ADR-002",
            created_at=past, expires_at=now,
        )
        out = expire_stale_proposals([p])
        assert out[0].state == CurationGateState.EXPIRED

    def test_keeps_pending_within_ttl(self) -> None:
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=1)
        p = CurationProposal(
            slug="x", artifact_title="X", target="r",
            note_content="# x", finding_indices=(),
            source_path=None, decision_adr="ADR-002",
            created_at=now, expires_at=future,
        )
        out = expire_stale_proposals([p])
        assert out[0].state == CurationGateState.PENDING

    def test_keeps_terminal_unchanged(self) -> None:
        now = datetime.now(timezone.utc)
        for st in (CurationGateState.APPROVED, CurationGateState.REJECTED,
                   CurationGateState.CANCELLED, CurationGateState.EXPIRED):
            p = CurationProposal(
                slug="x", artifact_title="X", target="r",
                note_content="# x", finding_indices=(),
                source_path=None, decision_adr="ADR-002",
                created_at=now, expires_at=now,
                state=st,
            )
            out = expire_stale_proposals([p])
            assert out[0].state == st


# =============================================================================
# Phase 4: promote_to_obsidian — Vault Resolution
# =============================================================================

class TestPromoteToObsidianVaultResolution:
    """Vault resolution and unconfigured-path handling."""

    def test_promote_requires_approved_proposal(self) -> None:
        p = _mk_proposal(state=CurationGateState.PENDING)
        with pytest.raises(CurationGateError, match="must be APPROVED"):
            promote_to_obsidian(p)

    def test_promote_approved_raises_if_vault_unconfigured(self,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JANUS_OBSIDIAN_VAULT", raising=False)
        p = _mk_proposal(state=CurationGateState.APPROVED)
        with pytest.raises(CurationGateError, match="Obsidian vault path is not configured"):
            promote_to_obsidian(p)

    def test_promote_with_valid_vault_path(self, tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JANUS_OBSIDIAN_VAULT", str(tmp_path))
        p = _mk_proposal(state=CurationGateState.APPROVED)
        # The promoter writes to Knowledge/ subdirectory — we need it to exist
        vault = tmp_path / "Knowledge"
        vault.mkdir(exist_ok=True)
        report = promote_to_obsidian(p)
        assert report["promoted"] is True
        assert report["adapter"] is False
        assert report["path"] is not None

    def test_promote_with_explicit_vault_override(self, tmp_path: Path) -> None:
        vault = tmp_path / "custom_vault" / "Knowledge"
        vault.mkdir(parents=True, exist_ok=True)
        p = _mk_proposal(state=CurationGateState.APPROVED)
        report = promote_to_obsidian(p, vault_path=vault.parent)
        assert report["promoted"] is True
        assert report["adapter"] is False
        assert report["path"] is not None
        assert vault.parent in Path(report["path"]).parents


# =============================================================================
# Phase 4: propose_note_content — Deterministic Rendering
# =============================================================================

class TestProposeNoteContent:
    """propose_note_content produces deterministic Obsidian markdown."""

    def test_contains_frontmatter(self) -> None:
        summary = _mk_summary(title="FC", target="test")
        body = propose_note_content(summary)
        assert body.startswith("---")
        assert "created:" in body
        assert "target:" in body
        assert "version:" in body
        assert "confidence:" in body
        # Frontmatter section should have at least 3 lines
        fm_section = body.split("---", 2)[1]
        assert fm_section.count("\n") >= 3

    def test_contains_title_heading(self) -> None:
        summary = _mk_summary(title="FC", target="test")
        body = propose_note_content(summary)
        assert "# FC" in body

    def test_contains_topic_heading(self) -> None:
        summary = _mk_summary(title="pipeline", target="pipeline")
        body = propose_note_content(summary)
        # _mk_summary hardcodes topic block topic to "test" regardless of title/target.
        assert "## test" in body

    def test_contains_finding_statements(self) -> None:
        summary = _mk_summary(title="FC", target="test")
        body = propose_note_content(summary)
        assert "Finding for FC" in body

    def test_contains_conclusions_section(self) -> None:
        summary = _mk_summary(title="FC", target="test")
        body = propose_note_content(summary)
        assert "Conclusions:" in body

    def test_contains_source_urls_when_present(self) -> None:
        tb = TopicBlock(topic="t", findings=[
            Finding(statement="Established", topic="t", confidence="wyzszy",
                    sources=[_mk_source(url="https://example.com/paper")]),
        ])
        summary = KnowledgeSummary(
            title="FC", target="test", summary_text="S",
            conclusions="C", topic_blocks=[tb], generated_at=datetime.now(timezone.utc),
        )
        body = propose_note_content(summary)
        assert "https://example.com/paper" in body

    def test_contains_knowledge_gaps_section_when_gaps_exist(self) -> None:
        summary = _mk_summary(
            title="FC", target="test",
            knowledge_gaps=["Gap one", "Gap two"],
        )
        body = propose_note_content(summary)
        assert "## Knowledge gaps" in body
        assert "Gap one" in body
        assert "Gap two" in body

    def test_deterministic_same_summary_same_output(self) -> None:
        summary = _mk_summary(title="FC", target="test")
        a = propose_note_content(summary)
        b = propose_note_content(summary)
        assert a == b

    def test_different_summaries_produce_different_output(self) -> None:
        s1 = _mk_summary(title="A", target="test")
        s2 = _mk_summary(title="B", target="test")
        assert propose_note_content(s1) != propose_note_content(s2)


# =============================================================================
# Phase 3 (downstream): CurationProposal.from_summary
# =============================================================================

class TestFromSummaryFindingIndices:
    """CurationProposal.from_summary finding_indices selection."""

    def test_default_indices_cover_all_blocks(self) -> None:
        tb1 = TopicBlock(topic="a", findings=[_mk_finding("fa", topic="a")])
        tb2 = TopicBlock(topic="b", findings=[_mk_finding("fb", topic="b")])
        summary = KnowledgeSummary(
            title="T", target="r", summary_text="S", conclusions="C",
            topic_blocks=[tb1, tb2], generated_at=datetime.now(timezone.utc),
        )
        p = CurationProposal.from_summary(summary, source_path=None)
        assert p.finding_indices == (0, 1)

    def test_explicit_indices_subset(self) -> None:
        tb1 = TopicBlock(topic="a", findings=[_mk_finding("fa", topic="a")])
        tb2 = TopicBlock(topic="b", findings=[_mk_finding("fb", topic="b")])
        summary = KnowledgeSummary(
            title="T", target="r", summary_text="S", conclusions="C",
            topic_blocks=[tb1, tb2], generated_at=datetime.now(timezone.utc),
        )
        p = CurationProposal.from_summary(summary, finding_indices=(0,), source_path=None)
        assert p.finding_indices == (0,)


# =============================================================================
# Phase 4 (downstream): Validation warnings feed the curate gate
# =============================================================================

class TestValidationToCurationBridge:
    """validate_artifact surfaces low-confidence findings for the gate."""

    def test_niski_finding_produces_warning(self) -> None:
        art = _mk_artifact(findings=[
            _mk_finding("Low confidence finding", confidence="niski"),
        ])
        warnings = validate_artifact(art)
        low_conf = [w for w in warnings if w.category == "low_confidence"]
        assert len(low_conf) == 1
        assert "niski" in low_conf[0].message

    def test_no_low_confidence_warnings_when_all_high(self) -> None:
        art = _mk_artifact(findings=[
            _mk_finding("Solid finding", confidence="wyzszy"),
        ])
        warnings = validate_artifact(art)
        low_conf = [w for w in warnings if w.category == "low_confidence"]
        assert len(low_conf) == 0

    def test_empty_summary_completeness_warning(self) -> None:
        art = _mk_artifact(summary="", conclusions="",
                           findings=[_mk_finding("F")])
        warnings = validate_artifact(art)
        completeness = [w for w in warnings if w.category == "completeness"]
        assert len(completeness) >= 1


# =============================================================================
# Phase 2 (downstream): generate_summary feeds the promoter
# =============================================================================

class TestGenerateSummaryToPromoterBridge:
    """generate_summary output is renderable by propose_note_content."""

    def test_summary_roundtrips_to_note(self) -> None:
        art = _mk_artifact(
            title="Roundtrip Co", target="research",
            summary="Research on Roundtrip",
            conclusions="Roundtrip conclusions",
            findings=[
                _mk_finding("Established fact", confidence="wyzszy"),
                _mk_finding("Tentative finding", confidence="sredni"),
            ],
        )
        warnings = validate_artifact(art)
        summary = generate_summary(art, warnings=warnings)
        note = propose_note_content(summary)
        assert "Roundtrip Co" in note
        assert "Established fact" in note
        assert "Tentative finding" in note


# =============================================================================
# Phase 4: Persistence Bridge — promotion records
# =============================================================================

class TestPersistPromotionRecord:
    """persist_promotion_record writes audit JSON; load_record reads it back."""

    def test_persist_writes_json(self, tmp_path: Path) -> None:
        p = _mk_proposal(slug="persist-test", state=CurationGateState.APPROVED)
        rec_dir = tmp_path / "records"
        rec = persist_promotion_record(
            p, {"promoted": True, "path": None, "promoted_at": "2026-01-01T00:00:00Z"},
            record_dir=rec_dir,
        )
        assert rec is not None
        assert rec.name == "persist-test.json"
        data = json.loads(rec.read_text())
        assert data["slug"] == "persist-test"
        assert data["target"] == "research"
        assert data["state"] == "approved"
        assert data["promoted"] is True

    def test_load_record_returns_dict(self, tmp_path: Path) -> None:
        p = _mk_proposal(slug="load-test", state=CurationGateState.APPROVED)
        rec_dir = tmp_path / "records"
        rec = persist_promotion_record(
            p, {"promoted": True, "path": None, "promoted_at": "2026-01-01T00:00:00Z"},
            record_dir=rec_dir,
        )
        loaded = load_record(rec)
        assert loaded["slug"] == "load-test"
        assert loaded["target"] == "research"

    def test_load_record_file_not_found_returns_none(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.json"
        assert load_record(missing) is None

    def test_persist_creates_dir(self, tmp_path: Path) -> None:
        p = _mk_proposal(slug="mkdir-test", state=CurationGateState.APPROVED)
        rec_dir = tmp_path / "deep" / "nested" / "records"
        rec = persist_promotion_record(
            p, {"promoted": False, "path": None, "promoted_at": None},
            record_dir=rec_dir,
        )
        assert rec is not None
        assert rec.parent.exists()


# =============================================================================
# Phase 4: Vault Resolution Helpers
# =============================================================================

class TestVaultResolution:
    """_resolve_vault and _is_vault_unconfigured honour the env flag."""

    def test_unconfigured_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JANUS_OBSIDIAN_VAULT", raising=False)
        assert _is_vault_unconfigured() is True

    def test_configured_path_exists_returns_false(self, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JANUS_OBSIDIAN_VAULT", str(tmp_path))
        assert _is_vault_unconfigured() is False

    def test_configured_path_missing_returns_true(self, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        missing = tmp_path / "does-not-exist"
        monkeypatch.setenv("JANUS_OBSIDIAN_VAULT", str(missing))
        assert _is_vault_unconfigured() is True

    def test_resolve_vault_with_env(self, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JANUS_OBSIDIAN_VAULT", str(tmp_path))
        vault = _resolve_vault(None)
        assert vault == tmp_path

    def test_resolve_vault_with_arg_overrides_env(self, tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    another_path) -> None:
        another_path.mkdir(exist_ok=True)
        monkeypatch.setenv("JANUS_OBSIDIAN_VAULT", str(tmp_path))
        vault = _resolve_vault(another_path)
        assert vault == another_path

    def test_resolve_vault_arg_nonexistent_returns_none(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nope"
        assert _resolve_vault(nonexistent) is None


# =============================================================================
# Phase 4: Promotion Report is JSON-serializable
# =============================================================================

class TestPromotionReportSerializable:
    """promote_to_obsidian reports survive JSON round-trips."""

    def test_report_json_roundtrip(self, monkeypatch: pytest.MonkeyPatch,
                                    tmp_path: Path) -> None:
        monkeypatch.setenv("JANUS_OBSIDIAN_VAULT", str(tmp_path))
        vault = tmp_path / "Knowledge"
        vault.mkdir(exist_ok=True)
        p = _mk_proposal(slug="json-test", state=CurationGateState.APPROVED)
        report = promote_to_obsidian(p)
        payload = json.dumps(report, default=str)
        restored = json.loads(payload)
        assert restored["slug"] == "json-test"
        assert restored["promoted"] is True
        assert restored["action"] == "promote_to_obsidian"


# =============================================================================
# Phase 5: CLI Surface
# =============================================================================

class TestKnowledgeCliSurface:
    """janus knowledge promote is dispatched and surfaces a proposal."""

    def test_knowledge_help_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        from janus.knowledge_cli import print_knowledge_help
        print_knowledge_help()
        captured = capsys.readouterr()
        assert "research" in captured.out
        assert "knowledge promote" in captured.out
        assert "--vault" in captured.out


# =============================================================================
# Phase 5: End-to-end — promotion_records data directory lifecycle
# =============================================================================

class TestPromotionRecordsDataDirectory:
    """Phase 5: promotion_records dir is created, records are written/read."""

    def test_records_dir_created_on_first_persist(self, tmp_path: Path) -> None:
        p = _mk_proposal(slug="dir-test", state=CurationGateState.APPROVED)
        rec_dir = tmp_path / "knowledge" / "promotion_records"
        rec = persist_promotion_record(
            p, {"promoted": False, "path": None, "promoted_at": None},
            record_dir=rec_dir,
        )
        assert rec is not None
        assert rec.parent.exists()
        assert rec.parent.name == "promotion_records"

    def test_multiple_records_coexist(self, tmp_path: Path) -> None:
        rec_dir = tmp_path / "records"
        now = datetime.now(timezone.utc)
        for slug in ("alpha", "beta", "gamma"):
            p = CurationProposal(
                slug=slug, artifact_title=slug.upper(), target="research",
                note_content=f"# {slug}\n", finding_indices=(),
                source_path=None, decision_adr="ADR-002",
                created_at=now, expires_at=now + timedelta(hours=1),
                state=CurationGateState.APPROVED,
            )
            persist_promotion_record(
                p, {"promoted": True, "path": None, "promoted_at": now.isoformat()},
                record_dir=rec_dir,
            )
        files = sorted(rec_dir.glob("*.json"))
        assert len(files) == 3
        assert {f.stem for f in files} == {"alpha", "beta", "gamma"}

    def test_record_contains_content_hash_for_audit(self, tmp_path: Path) -> None:
        p = _mk_proposal(slug="audit-hash", state=CurationGateState.APPROVED)
        rec_dir = tmp_path / "records"
        rec = persist_promotion_record(
            p, {"promoted": True, "path": None, "promoted_at": "2026-01-01T00:00:00Z"},
            record_dir=rec_dir,
        )
        data = json.loads(rec.read_text())
        assert data["content_hash"] == p.content_hash
        assert len(data["content_hash"]) == 64


# =============================================================================
# Phase 5: Full pipeline end-to-end
# =============================================================================

class TestFullPipelineE2E:
    """The full pipeline: artifact → validate → generate → propose → curate → promote."""

    def test_e2e_generate_summary_to_promote_note(self) -> None:
        art = _mk_artifact(
            title="E2E Company",
            target="research",
            summary="E2E summary text",
            conclusions="E2E conclusions",
            findings=[
                _mk_finding("Finding one", confidence="wyzszy"),
                _mk_finding("Finding two", confidence="sredni"),
                _mk_finding("Finding three", confidence="niski"),
            ],
        )
        warnings = validate_artifact(art)
        summary = generate_summary(art, warnings=warnings)
        note = propose_note_content(summary)
        proposal = CurationProposal.from_summary(summary, finding_indices=(0, 1, 2),
                                                  source_path=None)
        assert proposal.artifact_title == "E2E Company"
        assert proposal.target == "research"
        assert len(proposal.finding_indices) == 3
        assert note.startswith("---")
        assert "# E2E Company" in note
        assert "Finding one" in note
        assert "Finding two" in note
        assert "Finding three" in note
        # knowledge gaps
        assert "Knowledge gaps" in note or "No knowledge gaps" in note

    def test_e2e_curation_gate_then_promote(self, tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JANUS_OBSIDIAN_VAULT", str(tmp_path))
        vault = tmp_path / "Knowledge"
        vault.mkdir(exist_ok=True)
        art = _mk_artifact(
            title="E2E Promote",
            target="research",
            summary="E2E summary",
            conclusions="E2E conclusions",
            findings=[_mk_finding("Promotable finding")],
        )
        warnings = validate_artifact(art)
        summary = generate_summary(art, warnings=warnings)
        proposal = CurationProposal.from_summary(summary, finding_indices=(0, 1, 2),
                                                  source_path=None)
        # Curate
        curated = curate_proposal(proposal, "approve")
        assert curated.state == CurationGateState.APPROVED
        # Promote
        report = promote_to_obsidian(curated)
        assert report["promoted"] is True
        assert report["adapter"] is False
        assert report["path"] is not None
        # Verify file exists
        path = Path(report["path"])
        assert path.exists()
        content = path.read_text()
        assert "E2E Promote" in content
        assert "Promotable finding" in content

    def test_e2e_pending_proposal_cannot_be_promoted(self) -> None:
        art = _mk_artifact(title="Pending", target="research",
                           summary="S", conclusions="C",
                           findings=[_mk_finding("F")])
        summary = generate_summary(art, warnings=validate_artifact(art))
        proposal = CurationProposal.from_summary(summary, finding_indices=(0, 1, 2),
                                                  source_path=None)
        assert proposal.state == CurationGateState.PENDING
        with pytest.raises(CurationGateError, match="must be APPROVED"):
            promote_to_obsidian(proposal)
