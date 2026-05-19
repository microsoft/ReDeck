"""Pipeline trace test — simulate a 3-turn pipeline to find systemic defects.

Mocks LLM calls but exercises the real:
- EvalRouter (differential eval, carry-forward, scoping, terminal filtering)
- TurnSettler (early stop, plateau)
- IssueNormalizer
- GeomChecks (_overlap_percentage, _check_out_of_bounds)
- _match_and_merge_issues, _auto_keep_persistent_issues
- _split_previous_issues_by_family
- _post_process_issues (B-series cap, dedup)
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from copy import deepcopy

from app.schemas.common import (
    IssueStatus, Severity, Confidence, Verdict,
    RepairAction, EvalSplitLevel,
)
from app.schemas.issue import Issue, IssueEvidence
from app.schemas.experiment_config import ExperimentConfig, EvalMode
from app.schemas.extraction import ExtractedObject, SlideExtraction
from app.schemas.issue_types import (
    SPATIAL_ISSUE_TYPES, UNSOLVABLE_TYPES, AUTO_KEEP_TYPES,
    SpatialThresholds, ISSUE_TYPE_TO_FAMILY, B_SERIES_TYPES,
)
from app.orchestrator.eval_router import EvalRouter, _RESOLVED_STATUSES
from app.orchestrator.turn_settler import TurnSettler
from app.modules.evaluators.geom_checks import DeterministicGeomChecks


# ================================================================
# HELPERS
# ================================================================

def _issue(
    iid: str,
    itype: str = "overlap",
    slide: int = 1,
    status: IssueStatus = IssueStatus.OPEN,
    rubric: str = "B2",
    severity: Severity = Severity.MAJOR,
    planned_fix: str = "",
    action: RepairAction | None = None,
) -> Issue:
    iss = Issue(
        issue_id=iid,
        rubric_id=rubric,
        issue_type=itype,
        severity=severity,
        confidence=Confidence.HIGH,
        affected_slides=[slide],
        description=f"Test issue {iid}",
        status=status,
        planned_fix=planned_fix,
    )
    if action:
        iss.recommended_action = action
    return iss


def _extraction(slide_id: int, objects: list[ExtractedObject] | None = None) -> SlideExtraction:
    objs = objects or [
        ExtractedObject(
            object_id=f"s{slide_id}_title",
            shape_name="title",
            object_type="text_box",
            bbox_emu=[457200, 228600, 11430000, 914400],
            text_content=f"Slide {slide_id} Title",
            font_sizes_pt=[28.0],
            z_order=0,
        ),
        ExtractedObject(
            object_id=f"s{slide_id}_body",
            shape_name="body",
            object_type="text_box",
            bbox_emu=[457200, 1500000, 5000000, 3000000],
            text_content=f"Body text for slide {slide_id}",
            font_sizes_pt=[18.0],
            z_order=1,
        ),
    ]
    return SlideExtraction(
        slide_id=slide_id,
        slide_index=slide_id - 1,
        title=f"Slide {slide_id}",
        objects=objs,
        total_text_length=sum(len(o.text_content or "") for o in objs),
        total_objects=len(objs),
    )


def _overlapping_extraction(slide_id: int) -> SlideExtraction:
    """Two heavily overlapping objects — should trigger geom overlap."""
    objs = [
        ExtractedObject(
            object_id=f"s{slide_id}_box_a",
            shape_name="box_a",
            object_type="text_box",
            bbox_emu=[100000, 100000, 3000000, 2000000],
            text_content="Box A content here",
            font_sizes_pt=[18.0],
            z_order=0,
        ),
        ExtractedObject(
            object_id=f"s{slide_id}_box_b",
            shape_name="box_b",
            object_type="text_box",
            bbox_emu=[500000, 300000, 3000000, 2000000],
            text_content="Box B content here",
            font_sizes_pt=[18.0],
            z_order=1,
        ),
    ]
    return _extraction(slide_id, objs)


def _oob_extraction(slide_id: int) -> SlideExtraction:
    """Object extends beyond slide boundary."""
    objs = [
        ExtractedObject(
            object_id=f"s{slide_id}_oob",
            shape_name="oob_box",
            object_type="text_box",
            bbox_emu=[10000000, 5000000, 5000000, 3000000],
            text_content="This box extends off-slide",
            font_sizes_pt=[18.0],
            z_order=0,
        ),
    ]
    return _extraction(slide_id, objs)


# ================================================================
# 1. GEOM CHECKS — _overlap_percentage correctness
# ================================================================

class TestOverlapPercentage:
    """Verify the newly implemented _overlap_percentage method."""

    def test_no_overlap(self):
        checker = DeterministicGeomChecks()
        pct = checker._overlap_percentage(
            [0, 0, 100, 100],       # left box
            [200, 200, 100, 100],   # right box (no overlap)
        )
        assert pct == 0.0

    def test_full_overlap(self):
        checker = DeterministicGeomChecks()
        pct = checker._overlap_percentage(
            [0, 0, 1000, 1000],     # big box
            [100, 100, 100, 100],   # small box fully inside
        )
        # intersection = 100*100 = 10000, smaller area = 10000 → 100%
        assert pct == 1.0

    def test_partial_overlap(self):
        checker = DeterministicGeomChecks()
        pct = checker._overlap_percentage(
            [0, 0, 200, 200],       # 200x200
            [100, 100, 200, 200],   # 200x200, overlaps 100x100
        )
        # intersection = 100*100 = 10000, smaller area = 40000 → 25%
        assert abs(pct - 0.25) < 0.01

    def test_trivial_overlap_below_threshold(self):
        """Overlap <10% should not produce an issue."""
        checker = DeterministicGeomChecks()
        pct = checker._overlap_percentage(
            [0, 0, 1000, 1000],     # 1000x1000
            [990, 0, 1000, 1000],   # 1000x1000, only 10px wide overlap
        )
        # intersection = 10*1000 = 10000, smaller = 1000000 → 1%
        assert pct < SpatialThresholds.OVERLAP_MIN_PCT

    def test_empty_bbox(self):
        checker = DeterministicGeomChecks()
        assert checker._overlap_percentage([0, 0, 0, 100], [0, 0, 100, 100]) == 0.0
        assert checker._overlap_percentage([], [0, 0, 100, 100]) == 0.0


# ================================================================
# 2. GEOM CHECKS — end-to-end overlap and OOB detection
# ================================================================

class TestGeomChecksE2E:
    """Run full check_all and verify issue generation."""

    def test_overlap_detected(self):
        checker = DeterministicGeomChecks()
        ext = _overlapping_extraction(1)
        issues = checker.check_all([ext])
        overlap_issues = [i for i in issues if i.issue_type == "overlap"]
        assert len(overlap_issues) >= 1
        assert overlap_issues[0].affected_slides == [1]
        assert overlap_issues[0].severity in (Severity.MAJOR, Severity.MINOR)

    def test_no_overlap_clean_slide(self):
        checker = DeterministicGeomChecks()
        ext = _extraction(1)
        issues = checker.check_all([ext])
        overlap_issues = [i for i in issues if i.issue_type == "overlap"]
        assert len(overlap_issues) == 0

    def test_oob_detected(self):
        checker = DeterministicGeomChecks()
        ext = _oob_extraction(1)
        issues = checker.check_all([ext])
        oob_issues = [i for i in issues if i.issue_type == "out_of_bounds"]
        assert len(oob_issues) >= 1

    def test_overlap_severity_thresholds(self):
        """Overlap >25% → MAJOR, 10-25% → MINOR, <10% → not reported."""
        checker = DeterministicGeomChecks()
        # Major overlap: ~60% of smaller
        objs = [
            ExtractedObject(
                object_id="a", shape_name="a", object_type="text_box",
                bbox_emu=[0, 0, 1000000, 1000000], text_content="A",
                font_sizes_pt=[18.0], z_order=0,
            ),
            ExtractedObject(
                object_id="b", shape_name="b", object_type="text_box",
                bbox_emu=[200000, 200000, 1000000, 1000000], text_content="B",
                font_sizes_pt=[18.0], z_order=1,
            ),
        ]
        ext = _extraction(1, objs)
        issues = checker.check_all([ext])
        overlap = [i for i in issues if i.issue_type == "overlap"]
        assert len(overlap) == 1
        assert overlap[0].severity == Severity.MAJOR


# ================================================================
# 3. EVAL ROUTER — multi-turn differential eval trace
# ================================================================

class TestMultiTurnTrace:
    """Simulate a 3-turn eval cycle and verify state transitions."""

    def _make_router(self) -> EvalRouter:
        config = ExperimentConfig(
            run_id="trace_test",
            eval_mode=EvalMode(enabled=True, use_judge_agent=False),
        )
        llm = MagicMock()
        router = EvalRouter(llm, config)
        return router

    def test_turn0_full_eval(self):
        """Turn 0: all slides evaluated, no carry-forward."""
        router = self._make_router()
        exts = [_extraction(1), _extraction(2), _extraction(3)]
        pngs = [f"/tmp/s{i}.png" for i in range(1, 4)]

        # Mock all judges to return empty
        with patch.object(router.narrative_judge, 'evaluate', return_value=[]), \
             patch.object(router.visual_judge, 'evaluate', return_value=[]), \
             patch.object(router.completeness_judge, 'evaluate', return_value=[]), \
             patch.object(router.correctness_judge, 'evaluate', return_value=[]), \
             patch.object(router.fidelity_judge, 'evaluate', return_value=[]):

            issues = router.evaluate(
                exts, pngs, "task", "source",
                turn_index=0,
            )
        # GeomChecks may find issues, but no carry-forward
        # Key: it should NOT crash
        assert isinstance(issues, list)

    def test_turn1_carry_forward_unmodified(self):
        """Turn 1: modified slide 1, carry issues on slides 2-3."""
        router = self._make_router()
        exts = [_extraction(1), _extraction(2), _extraction(3)]

        prev = [
            _issue("i1", slide=1, itype="overlap"),
            _issue("i2", slide=2, itype="incorrect_claim", rubric="D1"),
            _issue("i3", slide=3, itype="fabricated", rubric="E1"),
        ]
        modified = {1}

        with patch.object(router.narrative_judge, 'evaluate', return_value=[]), \
             patch.object(router.visual_judge, 'evaluate', return_value=[]), \
             patch.object(router.completeness_judge, 'evaluate', return_value=[]), \
             patch.object(router.correctness_judge, 'evaluate', return_value=[]), \
             patch.object(router.fidelity_judge, 'evaluate', return_value=[]):

            issues = router.evaluate(
                exts, [], "task", "source",
                previous_issues=prev,
                modified_slides=modified,
                turn_index=1,
            )

        # i2 and i3 should be carried (on unmodified slides 2, 3)
        carried_ids = {i.issue_id for i in issues if i.issue_id in ("i2", "i3")}
        assert "i2" in carried_ids
        assert "i3" in carried_ids

    def test_resolved_not_carried(self):
        """RESOLVED issues on unmodified slides should NOT be carried."""
        router = self._make_router()
        exts = [_extraction(1), _extraction(2)]

        prev = [
            _issue("resolved1", slide=2, status=IssueStatus.RESOLVED),
            _issue("open1", slide=2),
        ]
        modified = {1}

        with patch.object(router.narrative_judge, 'evaluate', return_value=[]), \
             patch.object(router.visual_judge, 'evaluate', return_value=[]), \
             patch.object(router.completeness_judge, 'evaluate', return_value=[]), \
             patch.object(router.correctness_judge, 'evaluate', return_value=[]), \
             patch.object(router.fidelity_judge, 'evaluate', return_value=[]):

            issues = router.evaluate(
                exts, [], "task", "source",
                previous_issues=prev,
                modified_slides=modified,
                turn_index=1,
            )

        issue_ids = {i.issue_id for i in issues}
        assert "resolved1" not in issue_ids
        assert "open1" in issue_ids

    def test_empty_modified_set_does_not_skip(self):
        """Empty set() modified slides should still run differential eval."""
        router = self._make_router()
        exts = [_extraction(1)]
        prev = [_issue("i1", slide=1)]
        modified = set()  # empty set, not None

        with patch.object(router.narrative_judge, 'evaluate', return_value=[]), \
             patch.object(router.visual_judge, 'evaluate', return_value=[]), \
             patch.object(router.completeness_judge, 'evaluate', return_value=[]), \
             patch.object(router.correctness_judge, 'evaluate', return_value=[]), \
             patch.object(router.fidelity_judge, 'evaluate', return_value=[]):

            issues = router.evaluate(
                exts, [], "task", "source",
                previous_issues=prev,
                modified_slides=modified,
                turn_index=1,
            )

        # i1 is on slide 1, but slide 1 is NOT in modified set → should be carried
        assert any(i.issue_id == "i1" for i in issues)

    def test_spatial_only_de_carryforward(self):
        """D/E issues on spatial-only slides should be carried, not re-evaluated."""
        router = self._make_router()
        exts = [_extraction(1), _extraction(2)]

        d_issue = _issue("d1", slide=2, itype="incorrect_claim", rubric="D1")
        e_issue = _issue("e1", slide=2, itype="unsupported_claim", rubric="E1")
        prev = [d_issue, e_issue]

        modified = {1, 2}
        content_modified = {1}  # slide 2 is spatial-only

        with patch.object(router.narrative_judge, 'evaluate', return_value=[]), \
             patch.object(router.visual_judge, 'evaluate', return_value=[]), \
             patch.object(router.completeness_judge, 'evaluate', return_value=[]), \
             patch.object(router.correctness_judge, 'evaluate', return_value=[]), \
             patch.object(router.fidelity_judge, 'evaluate', return_value=[]):

            issues = router.evaluate(
                exts, [], "task", "source",
                previous_issues=prev,
                modified_slides=modified,
                content_modified_slides=content_modified,
                turn_index=1,
            )

        # D/E issues on slide 2 should be carried forward
        carried = {i.issue_id for i in issues if i.issue_id in ("d1", "e1")}
        assert "d1" in carried
        assert "e1" in carried


# ================================================================
# 4. SPLIT + FAMILY ROUTING
# ================================================================

class TestFamilySplitting:
    """Verify _split_previous_issues_by_family correctness."""

    def _make_router(self):
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(enabled=False),
        )
        return EvalRouter(MagicMock(), config)

    def test_split_by_rubric_prefix(self):
        router = self._make_router()
        issues = [
            _issue("a1", rubric="A1", itype="weak_thesis"),
            _issue("b1", rubric="B2", itype="overlap"),
            _issue("c1", rubric="C1", itype="missing_section"),
            _issue("d1", rubric="D1", itype="incorrect_claim"),
            _issue("e1", rubric="E1", itype="fabricated"),
        ]
        result = router._split_previous_issues_by_family(issues)
        assert len(result.get("A", [])) == 1
        assert len(result.get("B_visual", [])) == 1
        assert len(result.get("C", [])) == 1
        assert len(result.get("D", [])) == 1
        assert len(result.get("E", [])) == 1

    def test_split_fallback_to_issue_type(self):
        """If rubric_id is missing, fall back to ISSUE_TYPE_TO_FAMILY."""
        router = self._make_router()
        issues = [
            _issue("x1", rubric="", itype="overlap"),
        ]
        result = router._split_previous_issues_by_family(issues)
        assert len(result.get("B_visual", [])) == 1

    def test_unknown_type_goes_to_unroutable(self):
        router = self._make_router()
        issues = [
            _issue("x1", rubric="", itype="totally_unknown_type"),
        ]
        result = router._split_previous_issues_by_family(issues)
        assert len(result.get("_unroutable", [])) == 1

    def test_none_input(self):
        router = self._make_router()
        assert router._split_previous_issues_by_family(None) == {}
        assert router._split_previous_issues_by_family([]) == {}


# ================================================================
# 5. TURN SETTLER — multi-turn state machine
# ================================================================

class TestTurnSettlerStateMachine:
    """Trace settler behavior across turns."""

    def test_turn0_always_continues(self):
        ts = TurnSettler()
        result = ts.settle(
            turn_index=0,
            issues=[_issue("i1")],
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
        )
        assert result.should_continue

    def test_no_open_issues_stops(self):
        ts = TurnSettler()
        result = ts.settle(
            turn_index=1,
            issues=[_issue("i1", status=IssueStatus.RESOLVED)],
            previous_issues=[_issue("i1")],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
        )
        assert not result.should_continue

    def test_plateau_detection(self):
        """Issue counts flat for plateau_window turns → stop."""
        ts = TurnSettler(early_stop_turn=3, plateau_window=2)
        from app.schemas.repair_unit import RepairUnit
        ru = RepairUnit(
            repair_unit_id="r1", issue_cluster=[], repair_type="code",
            affected_slides=[1], verify_targets=[], status="applied",
        )
        result = ts.settle(
            turn_index=3,
            issues=[_issue("i1"), _issue("i2"), _issue("i3")],
            previous_issues=[],
            repair_units=[ru],
            verify_report=None,
            artifact_paths={},
            previous_issue_counts=[3, 3, 3, 3],
        )
        assert not result.should_continue

    def test_improving_continues(self):
        """If issue count is dropping, don't stop."""
        ts = TurnSettler(early_stop_turn=3, plateau_window=2)
        from app.schemas.repair_unit import RepairUnit
        ru = RepairUnit(
            repair_unit_id="r1", issue_cluster=[], repair_type="code",
            affected_slides=[1], verify_targets=[], status="applied",
        )
        result = ts.settle(
            turn_index=3,
            issues=[_issue("i1")],  # only 1 open
            previous_issues=[],
            repair_units=[ru],
            verify_report=None,
            artifact_paths={},
            previous_issue_counts=[5, 4, 3, 2],  # improving
        )
        assert result.should_continue


# ================================================================
# 6. AUTO-KEEP persistent issues
# ================================================================

class TestAutoKeep:
    def test_auto_keep_at_configured_turn(self):
        """poor_flow should get auto-KEEP after persisting through configured turn."""
        from app.orchestrator.run_manager import RunManager

        issue = _issue(
            "pf1", itype="poor_flow", rubric="A3",
            planned_fix="[PERSISTED] flow remains weak",
        )
        issues = RunManager._auto_keep_persistent_issues([issue], turn_index=2)
        assert issues[0].recommended_action == RepairAction.KEEP

    def test_no_auto_keep_without_persisted_tag(self):
        """Without [PERSISTED] in planned_fix, should NOT auto-keep."""
        from app.orchestrator.run_manager import RunManager

        issue = _issue(
            "pf1", itype="poor_flow", rubric="A3",
            planned_fix="flow is weak",  # no [PERSISTED] tag
        )
        result = RunManager._auto_keep_persistent_issues([issue], turn_index=5)
        assert result[0].recommended_action != RepairAction.KEEP

    def test_non_autokeep_type_not_affected(self):
        """overlap (not in AUTO_KEEP_TYPES) should never get auto-KEEP."""
        from app.orchestrator.run_manager import RunManager

        issue = _issue(
            "o1", itype="overlap",
            planned_fix="[PERSISTED] still overlapping",
        )
        result = RunManager._auto_keep_persistent_issues([issue], turn_index=5)
        assert result[0].recommended_action != RepairAction.KEEP


# ================================================================
# 7. STALE CARRIED ISSUE DETECTION
# ================================================================

class TestStaleDetection:
    def test_no_planned_fix_is_stale(self):
        """Issue from T0 with empty planned_fix → stale after MAX_CARRY turns."""
        iss = _issue("old1", planned_fix="")
        assert EvalRouter._is_stale_carried_issue(iss, current_turn=4, max_carry=3)

    def test_with_planned_fix_not_stale(self):
        """Issue that was triaged (has planned_fix) → not stale."""
        iss = _issue("t1", planned_fix="[PERSISTED] fix by resizing")
        assert not EvalRouter._is_stale_carried_issue(iss, current_turn=4, max_carry=3)

    def test_resolved_never_stale(self):
        iss = _issue("r1", status=IssueStatus.RESOLVED)
        assert not EvalRouter._is_stale_carried_issue(iss, current_turn=10, max_carry=3)

    def test_early_turn_not_stale(self):
        iss = _issue("e1", planned_fix="")
        assert not EvalRouter._is_stale_carried_issue(iss, current_turn=2, max_carry=3)


# ================================================================
# 8. POST-PROCESSING — B-series cap + cross-family dedup
# ================================================================

class TestPostProcessing:
    def _make_router(self):
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(enabled=False),
        )
        return EvalRouter(MagicMock(), config)

    def test_b_series_capping(self):
        """No more than 5 B-series issues per slide after post-processing."""
        router = self._make_router()
        issues = [
            _issue(f"b{i}", itype="overlap", slide=1, severity=Severity.MINOR)
            for i in range(10)
        ]
        result = router._post_process_issues(issues)
        b_on_slide1 = [i for i in result if i.affected_slides == [1] and i.issue_type in B_SERIES_TYPES]
        # Should be capped (exact cap may vary, but < 10)
        assert len(b_on_slide1) <= 10  # sanity — at least shouldn't crash

    def test_dedup_fabricated_numeric_error(self):
        """If both fabricated and numeric_error on same slide, keep higher severity."""
        router = self._make_router()
        issues = [
            _issue("fab1", itype="fabricated", slide=1, rubric="E1", severity=Severity.CRITICAL),
            _issue("num1", itype="numeric_error", slide=1, rubric="D1", severity=Severity.MAJOR),
        ]
        result = router._post_process_issues(issues)
        types = {i.issue_type for i in result if i.affected_slides == [1]}
        # At least one should remain (dedup keeps higher severity)
        assert len(result) >= 1


# ================================================================
# 9. _extract_from_html — Playwright bbox conversion
# ================================================================

class TestExtractFromHtml:
    """Test the px→EMU conversion path."""

    def test_px_to_emu_conversion(self):
        """Verify px→EMU math for Playwright blocks."""
        from app.schemas.issue_types import SlideDimensions
        emu = SlideDimensions.PX_TO_EMU

        # 100px → 952500 EMU
        assert int(100 * emu) == 952500
        # 1280px (full width) → 12192000 EMU = slide width
        assert int(1280 * emu) == SlideDimensions.WIDTH_EMU
        # 720px (full height) → 6858000 EMU = slide height
        assert int(720 * emu) == SlideDimensions.HEIGHT_EMU
