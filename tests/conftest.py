"""Shared fixtures for the Slide Agent Harness test suite."""

from pathlib import Path

import pytest

from app.schemas.blueprint import BlueprintSlide, DeckBlueprint
from app.schemas.common import Confidence, IssueStatus, Severity, Verdict
from app.schemas.evidence import (
    EntityEntry,
    EvidenceChunk,
    EvidenceState,
    NumericFact,
)
from app.schemas.intent import IntentState
from app.schemas.issue import Issue, IssueEvidence
from app.schemas.repair_unit import RepairUnit

CASE_01_DIR = Path(__file__).resolve().parent.parent / "cases" / "case_01"


@pytest.fixture
def case_01_dir() -> Path:
    """Path to cases/case_01."""
    return CASE_01_DIR


@pytest.fixture
def sample_intent() -> IntentState:
    """Minimal IntentState fixture."""
    return IntentState(
        case_id="test_case",
        deck_type="conference_talk",
        audience="AI/ML researchers",
        page_budget=[8, 10],
        must_cover=[
            "benchmark comparison",
            "latency analysis",
            "cost trade-offs",
        ],
        must_avoid=["marketing language"],
        editable_required=True,
    )


@pytest.fixture
def sample_evidence() -> EvidenceState:
    """EvidenceState with a few chunks, numeric_facts, entities."""
    chunks = [
        EvidenceChunk(
            chunk_id="chunk_001",
            source_file="source_summary.md",
            content="ModelA achieves 78.3% accuracy on ImageQA-Hard.",
            chunk_type="text",
        ),
        EvidenceChunk(
            chunk_id="chunk_002",
            source_file="source_summary.md",
            content="ModelB has the best latency at 180ms per query costing $0.008/query.",
            chunk_type="text",
        ),
        EvidenceChunk(
            chunk_id="chunk_003",
            source_file="source_summary.md",
            content="ModelC excels on creative generation tasks scoring 4.5/5.0.",
            chunk_type="text",
        ),
    ]
    numeric_facts = [
        NumericFact(
            fact_id="fact_001",
            value="78.3%",
            unit="percentage",
            context="ModelA accuracy on ImageQA-Hard",
            source_ref="chunk_001",
        ),
        NumericFact(
            fact_id="fact_002",
            value="180ms",
            unit="latency",
            context="ModelB latency per query",
            source_ref="chunk_002",
        ),
    ]
    entities = [
        EntityEntry(
            entity_id="entity_modela",
            name="ModelA",
            entity_type="model",
            source_refs=["chunk_001"],
        ),
        EntityEntry(
            entity_id="entity_modelb",
            name="ModelB",
            entity_type="model",
            source_refs=["chunk_002"],
        ),
    ]
    return EvidenceState(
        chunks=chunks,
        numeric_facts=numeric_facts,
        entity_registry=entities,
    )


@pytest.fixture
def sample_blueprint() -> DeckBlueprint:
    """DeckBlueprint with 3 slides."""
    slides = [
        BlueprintSlide(
            slide_id=1,
            role="title",
            primary_proposition="Introduction to multi-modal AI comparison",
            narrative_position="opening",
            linked_evidence_ids=["chunk_001"],
        ),
        BlueprintSlide(
            slide_id=2,
            role="results",
            primary_proposition="Quantitative benchmark results",
            narrative_position="body",
            linked_evidence_ids=["chunk_001", "chunk_002"],
        ),
        BlueprintSlide(
            slide_id=3,
            role="conclusion",
            primary_proposition="Recommendations for different use cases",
            narrative_position="closing",
            linked_evidence_ids=["chunk_003"],
        ),
    ]
    return DeckBlueprint(
        case_id="test_case",
        total_slides=3,
        narrative_arc="problem -> results -> recommendations",
        slides=slides,
    )


@pytest.fixture
def sample_issues() -> list[Issue]:
    """List of Issues spanning different rubric families."""
    return [
        Issue(
            issue_id="B3_slide2_overlap_title_body",
            rubric_id="B3",
            issue_type="overlap",
            severity=Severity.MAJOR,
            confidence=Confidence.HIGH,
            affected_slides=[2],
            evidence=IssueEvidence(
                object_refs=["results_title", "results_body"],
                description="Title and body overlap on slide 2",
            ),
            suspected_module="layout_solver",
            verdict=Verdict.FAIL,
            fixability="easy_local_patch",
        ),
        Issue(
            issue_id="A1_narrative_arc",
            rubric_id="A1",
            issue_type="weak_narrative",
            severity=Severity.MINOR,
            confidence=Confidence.MEDIUM,
            affected_slides=[1, 2, 3],
            evidence=IssueEvidence(description="Narrative arc could be stronger"),
            suspected_module="planner",
            verdict=Verdict.FAIL,
        ),
        Issue(
            issue_id="B4_slide3_font",
            rubric_id="B4",
            issue_type="font_too_small",
            severity=Severity.CRITICAL,
            confidence=Confidence.HIGH,
            affected_slides=[3],
            evidence=IssueEvidence(
                object_refs=["rec_body"],
                description="Font 10pt below minimum 18pt",
            ),
            suspected_module="layout_solver",
            verdict=Verdict.FAIL,
            fixability="easy_local_patch",
        ),
        Issue(
            issue_id="C2_missing_limitations",
            rubric_id="C2",
            issue_type="missing_content",
            severity=Severity.MAJOR,
            confidence=Confidence.HIGH,
            affected_slides=[3],
            evidence=IssueEvidence(description="Missing model limitations"),
            suspected_module="planner",
            verdict=Verdict.FAIL,
        ),
    ]


@pytest.fixture
def sample_repair_units() -> list[RepairUnit]:
    """List of RepairUnits with repair_output populated."""
    return [
        RepairUnit(
            repair_unit_id="repair_2_layout_repair",
            issue_cluster=["B3_slide2_overlap_title_body"],
            repair_type="layout_repair",
            affected_slides=[2],
            frozen_objects=[],
            editable_objects=["results_title", "results_body"],
            verify_targets=["B3"],
            status="applied",
            repair_output={
                "slide_changes": [
                    {
                        "slide_id": 2,
                        "object_changes": [
                            {
                                "object_id": "results_body",
                                "bbox": [457200, 1371600, 11277600, 5029200],
                            }
                        ],
                    }
                ]
            },
        ),
        RepairUnit(
            repair_unit_id="repair_3_content_repair",
            issue_cluster=["C2_missing_limitations"],
            repair_type="content_repair",
            affected_slides=[3],
            verify_targets=["C2"],
            status="applied",
            repair_output={
                "slide_changes": [
                    {
                        "slide_id": 3,
                        "title": "Recommendations & Limitations",
                        "primary_message": "Choose based on use case, but note key limitations",
                    }
                ]
            },
        ),
        RepairUnit(
            repair_unit_id="repair_failed",
            issue_cluster=["A1_narrative_arc"],
            repair_type="content_repair",
            affected_slides=[1, 2, 3],
            verify_targets=["A1"],
            status="failed",
            repair_output={"error": "LLM timeout"},
        ),
    ]


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for test outputs."""
    output = tmp_path / "test_output"
    output.mkdir(parents=True, exist_ok=True)
    return output
