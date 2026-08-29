"""Tests for all 17 Pydantic schema models."""

import json

import pytest
from pydantic import ValidationError

from app.schemas.blueprint import BlueprintSlide, DeckBlueprint
from app.schemas.case_state import CaseState
from app.schemas.common import (
    BasePacket,
    Confidence,
    EvalSplitLevel,
    IssueStatus,
    RenderBackendType,
    RenderClass,
    Severity,
    Status,
    Verdict,
)
from app.schemas.compile_manifest import CompiledObjectRecord, CompileManifest
from app.schemas.eval_unit import EvalUnit
from app.schemas.evidence import (
    EntityEntry,
    EvidenceChunk,
    EvidenceState,
    FigureRef,
    NumericFact,
    TableRef,
)
from app.schemas.experiment_config import (
    EvalMode,
    ExperimentConfig,
    ModelConfig,
    RenderMode,
)
from app.schemas.extraction import ExtractedObject, SlideExtraction
from app.schemas.intent import IntentState
from app.schemas.issue import Issue, IssueEvidence
from app.schemas.module_log import ModuleCallLog
from app.schemas.render_result import RenderMeta, RenderResult
from app.schemas.repair_unit import RepairUnit
from app.schemas.turn_summary import TurnSummary
from app.schemas.verify_report import VerifyItem, VerifyReport


# ─── Enum Tests ────────────────────────────────────────────────────────────────

class TestEnums:
    """Test that all enums work with string values."""

    def test_status_from_string(self):
        assert Status("ok") == Status.OK
        assert Status("error") == Status.ERROR

    def test_severity_from_string(self):
        assert Severity("critical") == Severity.CRITICAL
        assert Severity("major") == Severity.MAJOR
        assert Severity("minor") == Severity.MINOR

    def test_confidence_from_string(self):
        assert Confidence("high") == Confidence.HIGH
        assert Confidence("medium") == Confidence.MEDIUM
        assert Confidence("low") == Confidence.LOW

    def test_issue_status_from_string(self):
        assert IssueStatus("open") == IssueStatus.OPEN
        assert IssueStatus("resolved") == IssueStatus.RESOLVED
        assert IssueStatus("wont_fix") == IssueStatus.WONT_FIX

    def test_verdict_from_string(self):
        assert Verdict("pass") == Verdict.PASS
        assert Verdict("fail") == Verdict.FAIL

    def test_render_class_from_string(self):
        assert RenderClass("approx_render") == RenderClass.APPROX_RENDER

    def test_plan_split_level(self):
        # PlanSplitLevel deleted (rule-based only)
        pass

    def test_eval_split_level(self):
        assert EvalSplitLevel("family") == EvalSplitLevel.FAMILY

    def test_layout_strategy(self):
        # LayoutStrategy deleted (rule-based only)
        pass

    def test_repair_routing(self):
        # RepairRouting deleted (rule-based only)
        pass

    def test_render_backend_type(self):
        assert RenderBackendType("linux_lo_pdf") == RenderBackendType.LINUX_LO_PDF

    def test_infeasibility_reason(self):
        # InfeasibilityReason deleted (rule-based only)
        pass

    def test_feasibility_result(self):
        # FeasibilityResult deleted (rule-based only)
        pass

    def test_invalid_enum_value_raises(self):
        with pytest.raises(ValueError):
            Status("invalid_value")
        with pytest.raises(ValueError):
            Severity("extreme")


# ─── IntentState Tests ─────────────────────────────────────────────────────────

class TestIntentState:

    def test_minimal_creation(self):
        intent = IntentState(
            case_id="c1",
            deck_type="report",
            audience="executives",
            page_budget=[5, 10],
        )
        assert intent.case_id == "c1"
        assert intent.must_cover == []
        assert intent.must_avoid == []
        assert intent.editable_required is True
        assert intent.additional_constraints == {}

    def test_full_creation(self):
        intent = IntentState(
            case_id="c2",
            deck_type="conference_talk",
            audience="researchers",
            page_budget=[8, 12],
            must_cover=["topic_a", "topic_b"],
            must_avoid=["marketing"],
            editable_required=False,
            additional_constraints={"max_bullets": 5},
        )
        assert intent.must_cover == ["topic_a", "topic_b"]
        assert intent.editable_required is False

    def test_serialization(self):
        intent = IntentState(
            case_id="c1",
            deck_type="report",
            audience="execs",
            page_budget=[5, 10],
        )
        d = intent.model_dump()
        assert d["case_id"] == "c1"
        assert isinstance(d["page_budget"], list)

        j = intent.model_dump_json()
        parsed = json.loads(j)
        assert parsed["deck_type"] == "report"

    def test_invalid_page_budget_length(self):
        with pytest.raises(ValidationError):
            IntentState(
                case_id="c1",
                deck_type="report",
                audience="execs",
                page_budget=[5],
            )

    def test_page_budget_too_many_elements(self):
        with pytest.raises(ValidationError):
            IntentState(
                case_id="c1",
                deck_type="report",
                audience="execs",
                page_budget=[1, 2, 3],
            )


# ─── EvidenceState Tests ──────────────────────────────────────────────────────

class TestEvidenceState:

    def test_empty_evidence(self):
        ev = EvidenceState()
        assert ev.chunks == []
        assert ev.figures == []
        assert ev.tables == []
        assert ev.numeric_facts == []
        assert ev.entity_registry == []

    def test_evidence_chunk_creation(self):
        c = EvidenceChunk(
            chunk_id="c001",
            source_file="doc.md",
            content="Hello world",
            chunk_type="text",
        )
        assert c.chunk_id == "c001"
        assert c.page_ref is None
        assert c.metadata == {}

    def test_figure_ref(self):
        f = FigureRef(figure_id="f1", source_file="img.png")
        assert f.caption == ""
        assert f.image_path is None

    def test_table_ref(self):
        t = TableRef(table_id="t1", source_file="data.csv")
        assert t.row_count == 0
        assert t.headers == []

    def test_numeric_fact(self):
        nf = NumericFact(fact_id="nf1", value="78.3%")
        assert nf.unit == ""
        assert nf.context == ""

    def test_entity_entry(self):
        e = EntityEntry(entity_id="e1", name="ModelA", entity_type="model")
        assert e.aliases == []
        assert e.source_refs == []

    def test_full_evidence_state(self, sample_evidence):
        assert len(sample_evidence.chunks) == 3
        assert len(sample_evidence.numeric_facts) == 2
        assert len(sample_evidence.entity_registry) == 2

    def test_serialization(self):
        ev = EvidenceState(
            chunks=[EvidenceChunk(
                chunk_id="c1",
                source_file="f.md",
                content="text",
                chunk_type="text",
            )]
        )
        d = ev.model_dump()
        assert len(d["chunks"]) == 1
        j = ev.model_dump_json()
        assert "c1" in j


# ─── Blueprint Tests ──────────────────────────────────────────────────────────

class TestBlueprint:

    def test_blueprint_slide_creation(self):
        bs = BlueprintSlide(
            slide_id=1,
            role="title",
            primary_proposition="Intro",
            narrative_position="opening",
        )
        assert bs.linked_evidence_ids == []
        assert bs.notes == ""

    def test_deck_blueprint_creation(self, sample_blueprint):
        assert sample_blueprint.total_slides == 3
        assert len(sample_blueprint.slides) == 3
        assert sample_blueprint.slides[0].role == "title"

    def test_serialization(self, sample_blueprint):
        d = sample_blueprint.model_dump()
        assert d["case_id"] == "test_case"
        j = sample_blueprint.model_dump_json()
        assert "narrative_arc" in j


# ─── Issue Tests ──────────────────────────────────────────────────────────────

class TestIssue:

    def test_minimal_creation(self):
        issue = Issue(
            issue_id="i1",
            rubric_id="B3",
            issue_type="overlap",
            severity=Severity.MAJOR,
        )
        assert issue.confidence == Confidence.HIGH
        assert issue.status == IssueStatus.OPEN
        assert issue.verdict == Verdict.FAIL
        assert issue.affected_slides == []

    def test_full_creation(self, sample_issues):
        assert len(sample_issues) == 4
        critical_issues = [i for i in sample_issues if i.severity == Severity.CRITICAL]
        assert len(critical_issues) == 1

    def test_issue_evidence(self):
        ev = IssueEvidence(
            render_ref="slide_2.png",
            object_refs=["obj1", "obj2"],
            description="Objects overlap",
        )
        assert len(ev.object_refs) == 2

    def test_serialization(self, sample_issues):
        issue = sample_issues[0]
        d = issue.model_dump()
        assert d["severity"] == "major"
        assert d["verdict"] == "fail"

    def test_severity_enum_in_model(self):
        # Ensure severity works with string values
        issue = Issue(
            issue_id="i2",
            rubric_id="A1",
            issue_type="weak_narrative",
            severity="minor",  # type: ignore
        )
        assert issue.severity == Severity.MINOR


# ─── RepairUnit Tests ─────────────────────────────────────────────────────────

class TestRepairUnit:

    def test_minimal_creation(self):
        ru = RepairUnit(
            repair_unit_id="r1",
            issue_cluster=["i1"],
            repair_type="content_repair",
        )
        assert ru.status == "pending"
        assert ru.repair_output == {}
        assert ru.frozen_objects == []

    def test_with_repair_output(self, sample_repair_units):
        applied_units = [u for u in sample_repair_units if u.status == "applied"]
        assert len(applied_units) == 2
        failed_units = [u for u in sample_repair_units if u.status == "failed"]
        assert len(failed_units) == 1


# ─── Extraction Tests ─────────────────────────────────────────────────────────

class TestExtraction:

    def test_extracted_object(self):
        obj = ExtractedObject(
            object_id="shape_1",
            object_type="text_box",
        )
        assert obj.bbox_emu == []
        assert obj.text_content == ""
        assert obj.font_sizes_pt == []
        assert obj.has_image is False

    def test_slide_extraction(self):
        ext = SlideExtraction(
            slide_id=1,
            slide_index=0,
        )
        assert ext.title == ""
        assert ext.objects == []
        assert ext.total_objects == 0

    def test_full_extraction(self):
        obj1 = ExtractedObject(
            object_id="title",
            object_type="text_box",
            bbox_emu=[100, 200, 5000, 1000],
            text_content="Hello World",
            font_sizes_pt=[28.0],
        )
        ext = SlideExtraction(
            slide_id=1,
            slide_index=0,
            title="Hello World",
            objects=[obj1],
            total_text_length=11,
            total_objects=1,
        )
        assert ext.total_objects == 1
        d = ext.model_dump()
        assert d["objects"][0]["object_id"] == "title"


# ─── CompileManifest Tests ────────────────────────────────────────────────────

class TestCompileManifest:

    def test_minimal_creation(self):
        cm = CompileManifest(
            pptx_path="output.pptx",
            total_slides=3,
        )
        assert cm.compile_backend == "python_pptx"
        assert cm.objects == []
        assert cm.warnings == []

    def test_with_objects(self):
        obj = CompiledObjectRecord(
            object_id="title",
            slide_id=1,
            object_type="text_box",
        )
        cm = CompileManifest(
            pptx_path="out.pptx",
            total_slides=1,
            objects=[obj],
        )
        assert len(cm.objects) == 1
        assert cm.objects[0].editable is True


# ─── TurnSummary Tests ────────────────────────────────────────────────────────

class TestTurnSummary:

    def test_minimal_creation(self):
        ts = TurnSummary(turn_index=0)
        assert ts.status == Status.OK
        assert ts.should_continue is False
        assert ts.issues_open == 0

    def test_full_creation(self):
        ts = TurnSummary(
            turn_index=1,
            status=Status.OK,
            total_issues_found=10,
            issues_open=3,
            issues_resolved=5,
            issues_new=2,
            should_continue=True,
            reason="3 open issues remain, continuing",
        )
        assert ts.issues_resolved == 5
        d = ts.model_dump()
        assert d["status"] == "ok"


# ─── CaseState Tests ─────────────────────────────────────────────────────────

class TestCaseState:

    def test_creation(self, sample_intent, sample_evidence):
        cs = CaseState(
            case_id="c1",
            case_dir="/path/to/case",
            intent=sample_intent,
            evidence=sample_evidence,
            task_brief="Test brief",
        )
        assert cs.case_id == "c1"
        assert cs.constraints == {}
        assert cs.revision_cards == []


# ─── EvalUnit Tests ───────────────────────────────────────────────────────────

class TestEvalUnit:

    def test_creation(self):
        eu = EvalUnit(
            eval_unit_id="eu1",
            rubric_family="B_geom",
            rubric_ids=["B3", "B4"],
            scope="slide_2",
            packet_type="geometry_packet",
        )
        assert eu.scope_slides == []
        assert eu.input_artifacts == []


# ─── ExperimentConfig Tests ───────────────────────────────────────────────────

class TestExperimentConfig:

    def test_defaults(self):
        ec = ExperimentConfig(run_id="run_001")
        assert ec.max_turns == 10
        assert ec.eval_mode.enabled is True
        assert ec.use_html_codegen is True
        assert ec.repair_strategy == "redeck"
        assert ec.layout_strategy == "template"
        assert ec.models.default == "gpt-5.5"

    def test_model_config_get_model(self):
        mc = ModelConfig(default="gpt-4o", narrative_judge="gpt-5.4")
        assert mc.get_model("narrative_judge") == "gpt-5.4"
        assert mc.get_model("visual_judge") == "gpt-4o"
        assert mc.get_model("nonexistent") == "gpt-4o"

    def test_slide_repair_model_is_independent(self):
        mc = ModelConfig(
            default="gpt-5.5",
            slide_codegen="gpt-5.4",
            slide_repair="gpt-5.5",
        )
        assert mc.get_model("slide_codegen") == "gpt-5.4"
        assert mc.get_model("slide_repair") == "gpt-5.5"
        assert mc.get_slide_repair_model() == "gpt-5.5"

    def test_slide_repair_model_inherits_codegen_for_legacy_configs(self):
        mc = ModelConfig(default="gpt-5.5", slide_codegen="gpt-5.4")
        assert mc.get_slide_repair_model() == "gpt-5.4"


# ─── RenderResult Tests ──────────────────────────────────────────────────────

class TestRenderResult:

    def test_minimal(self):
        rr = RenderResult(
            backend_name="libreoffice",
            status=Status.OK,
        )
        assert rr.pdf_path == ""
        assert rr.png_paths == []

    def test_with_meta(self):
        meta = RenderMeta(
            backend_name="libreoffice",
            render_class=RenderClass.APPROX_RENDER,
            office_family="libreoffice",
        )
        rr = RenderResult(
            backend_name="libreoffice",
            status=Status.OK,
            render_meta=meta,
        )
        assert rr.render_meta.render_class == RenderClass.APPROX_RENDER


# ─── VerifyReport Tests ──────────────────────────────────────────────────────

class TestVerifyReport:

    def test_empty_report(self):
        vr = VerifyReport(turn_index=0)
        assert vr.items == []
        assert vr.total_checked == 0

    def test_with_items(self):
        item = VerifyItem(
            issue_id="i1",
            rubric_id="B3",
            repair_unit_id="r1",
            verdict=Verdict.PASS,
        )
        vr = VerifyReport(
            turn_index=1,
            items=[item],
            total_checked=1,
            passed=1,
            failed=0,
        )
        assert vr.passed == 1


# ─── ModuleCallLog Tests ─────────────────────────────────────────────────────

class TestModuleCallLog:

    def test_creation(self):
        log = ModuleCallLog(module="test_module")
        assert log.status == "ok"
        assert log.timestamp  # auto-generated
        assert log.token_usage == {}

    def test_serialization(self):
        log = ModuleCallLog(
            module="deck_planner",
            model="gpt-5.4",
            timing_sec=1.23,
            token_usage={"prompt_tokens": 100, "completion_tokens": 50},
        )
        d = log.model_dump()
        assert d["model"] == "gpt-5.4"
        assert d["token_usage"]["prompt_tokens"] == 100


# ─── BasePacket Tests ─────────────────────────────────────────────────────────

class TestBasePacket:

    def test_extra_fields_allowed(self):
        bp = BasePacket(extra_field="hello")
        assert bp.extra_field == "hello"  # type: ignore
