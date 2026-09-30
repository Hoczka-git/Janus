"""Tests for NarrativeEngine — Phase B (Evidence & Audit)."""

from datetime import datetime

import pytest

from janus.models.narrative_engine import (
    NarrativeExplanation,
    ExplanationType,
    NarrativeEngine,
)


class TestNarrativeExplanation:
    """Tests for the NarrativeExplanation model."""

    def test_create_minimal(self):
        """Test creating a minimal NarrativeExplanation."""
        explanation = NarrativeExplanation(
            id="ne-1",
            explanation_type=ExplanationType.PROGRESS,
            subject="Task 1",
        )
        assert explanation.id == "ne-1"
        assert explanation.explanation_type == ExplanationType.PROGRESS
        assert explanation.subject == "Task 1"
        assert explanation.explanation == ""
        assert explanation.evidence_ids == []
        assert explanation.outcome_ids == []
        assert explanation.verification_ids == []
        assert explanation.confidence == 0.5
        assert explanation.created_at is not None

    def test_create_full(self):
        """Test creating a full NarrativeExplanation."""
        now = datetime.now()
        explanation = NarrativeExplanation(
            id="ne-2",
            explanation_type=ExplanationType.REGRESSION,
            subject="Goal 1",
            explanation="Progress regressed due to...",
            evidence_ids=["ev-1", "ev-2"],
            outcome_ids=["or-1"],
            verification_ids=["vr-1"],
            created_at=now,
            confidence=0.8,
        )
        assert explanation.id == "ne-2"
        assert explanation.explanation_type == ExplanationType.REGRESSION
        assert explanation.subject == "Goal 1"
        assert explanation.explanation == "Progress regressed due to..."
        assert explanation.evidence_ids == ["ev-1", "ev-2"]
        assert explanation.outcome_ids == ["or-1"]
        assert explanation.verification_ids == ["vr-1"]
        assert explanation.created_at == now
        assert explanation.confidence == 0.8

    def test_empty_id_raises(self):
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id must not be empty"):
            NarrativeExplanation(
                id="",
                explanation_type=ExplanationType.PROGRESS,
                subject="Test",
            )

    def test_empty_subject_raises(self):
        """Test that empty subject raises ValueError."""
        with pytest.raises(ValueError, match="subject must not be empty"):
            NarrativeExplanation(
                id="ne-1",
                explanation_type=ExplanationType.PROGRESS,
                subject="",
            )

    def test_invalid_explanation_type_raises(self):
        """Test that invalid explanation_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid explanation_type"):
            NarrativeExplanation(
                id="ne-1",
                explanation_type="invalid",
                subject="Test",
            )

    def test_invalid_confidence_raises(self):
        """Test that invalid confidence raises ValueError."""
        with pytest.raises(ValueError, match="Invalid confidence"):
            NarrativeExplanation(
                id="ne-1",
                explanation_type=ExplanationType.PROGRESS,
                subject="Test",
                confidence=1.5,
            )

    def test_to_dict(self):
        """Test serialization to dict."""
        explanation = NarrativeExplanation(
            id="ne-1",
            explanation_type=ExplanationType.PROGRESS,
            subject="Test",
        )
        d = explanation.to_dict()
        assert d["id"] == "ne-1"
        assert d["explanation_type"] == "progress"
        assert d["subject"] == "Test"
        assert "created_at" in d


class TestNarrativeEngine:
    """Tests for the NarrativeEngine."""

    def test_create_engine(self):
        """Test creating a NarrativeEngine."""
        engine = NarrativeEngine()
        assert engine._explanations == []

    def test_add_explanation(self):
        """Test adding an explanation."""
        engine = NarrativeEngine()
        explanation = NarrativeExplanation(
            id="ne-1",
            explanation_type=ExplanationType.PROGRESS,
            subject="Test",
        )
        engine.add_explanation(explanation)
        assert len(engine._explanations) == 1

    def test_get_explanations(self):
        """Test getting explanations."""
        engine = NarrativeEngine()
        e1 = NarrativeExplanation(
            id="ne-1",
            explanation_type=ExplanationType.PROGRESS,
            subject="Task 1",
        )
        e2 = NarrativeExplanation(
            id="ne-2",
            explanation_type=ExplanationType.REGRESSION,
            subject="Goal 1",
        )
        engine.add_explanation(e1)
        engine.add_explanation(e2)

        all_explanations = engine.get_explanations()
        assert len(all_explanations) == 2

        progress = engine.get_explanations(explanation_type=ExplanationType.PROGRESS)
        assert len(progress) == 1
        assert progress[0].id == "ne-1"

        task1 = engine.get_explanations(subject="Task 1")
        assert len(task1) == 1
        assert task1[0].id == "ne-1"

    def test_generate_progress_explanation(self):
        """Test generating a progress explanation."""
        engine = NarrativeEngine()
        explanation = engine.generate_progress_explanation(
            subject="Task 1",
            evidence_ids=["ev-1"],
            outcome_ids=["or-1"],
            verification_ids=["vr-1"],
        )
        assert explanation.id == "narrative-1"
        assert explanation.explanation_type == ExplanationType.PROGRESS
        assert explanation.subject == "Task 1"
        assert explanation.evidence_ids == ["ev-1"]
        assert explanation.outcome_ids == ["or-1"]
        assert explanation.verification_ids == ["vr-1"]
        assert explanation.confidence > 0.0

    def test_confidence_calculation(self):
        """Test confidence calculation."""
        engine = NarrativeEngine()
        # No evidence = 0.0
        assert engine._compute_confidence([], [], []) == 0.0
        # Some evidence > 0.0
        assert engine._compute_confidence(["ev-1"], [], []) > 0.0
        # More evidence = higher confidence
        assert engine._compute_confidence(["ev-1", "ev-2"], ["or-1"], ["vr-1"]) > \
               engine._compute_confidence(["ev-1"], [], [])
