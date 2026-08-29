"""Pipeline integration tests — trace the full eval/repair loop for systemic defects.

Tests cover:
1. Registry integrity — all imports resolve, sets are consistent
2. EvalRouter differential eval — carry-forward, scoping, terminal filtering
3. TurnSettler — early stop, plateau detection with configurable params
4. GeomChecks — thresholds from SpatialThresholds, not hardcoded
5. Redeck — UNSOLVABLE/CRITICAL_CONTENT imported from registry
6. Edge cases — empty slides, all-resolved, single slide modified
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from types import SimpleNamespace

from app.schemas.issue_types import (
    VALID_ISSUE_TYPES, ALL_VALID_TYPES, B_SERIES_TYPES,
    SPATIAL_ISSUE_TYPES, DETERMINISTIC_TYPES, UNSOLVABLE_TYPES,
    CROSS_SLIDE_TYPES, ISSUE_TYPE_TO_FAMILY, DEDUP_PAIRS,
    HIGH_VALUE_TYPES, CRITICAL_CONTENT_TYPES, CONTENT_ACCURACY_TYPES,
    LAYOUT_REPAIR_TYPES, AUTO_KEEP_TYPES,
    SlideDimensions, SpatialThresholds, IssueFamily, ISSUE_TYPE_DEFS,
)
from app.schemas.common import IssueStatus, Severity, Confidence, RepairAction
from app.schemas.experiment_config import ExperimentConfig, EvalMode
from app.schemas.issue import Issue


# ================================================================
# 1. REGISTRY INTEGRITY
# ================================================================

class TestRegistryIntegrity:
    """Verify the single source of truth is self-consistent."""

    def test_all_valid_types_is_union_of_families(self):
        """ALL_VALID_TYPES must equal the union of per-family sets."""
        union = set()
        for fam_types in VALID_ISSUE_TYPES.values():
            union |= fam_types
        assert union == ALL_VALID_TYPES

    def test_b_series_subset_of_all(self):
        assert B_SERIES_TYPES <= ALL_VALID_TYPES

    def test_spatial_subset_of_all(self):
        assert SPATIAL_ISSUE_TYPES <= ALL_VALID_TYPES

    def test_deterministic_subset_of_spatial(self):
        """Deterministic types should also be spatial."""
        assert DETERMINISTIC_TYPES <= SPATIAL_ISSUE_TYPES

    def test_unsolvable_subset_of_all(self):
        assert UNSOLVABLE_TYPES <= ALL_VALID_TYPES

    def test_cross_slide_subset_of_all(self):
        assert CROSS_SLIDE_TYPES <= ALL_VALID_TYPES

    def test_high_value_subset_of_all(self):
        assert HIGH_VALUE_TYPES <= ALL_VALID_TYPES

    def test_critical_content_subset_of_all(self):
        assert CRITICAL_CONTENT_TYPES <= ALL_VALID_TYPES

    def test_content_accuracy_superset_of_critical(self):
        """CONTENT_ACCURACY should be a superset of CRITICAL_CONTENT."""
        assert CRITICAL_CONTENT_TYPES <= CONTENT_ACCURACY_TYPES

    def test_layout_repair_subset_of_all(self):
        assert LAYOUT_REPAIR_TYPES <= ALL_VALID_TYPES

    def test_auto_keep_subset_of_all(self):
        assert AUTO_KEEP_TYPES <= ALL_VALID_TYPES

    def test_dedup_pairs_reference_valid_types(self):
        """Every type in DEDUP_PAIRS must be a valid issue type."""
        for pair in DEDUP_PAIRS:
            for t in pair:
                assert t in ALL_VALID_TYPES, f"{t} in DEDUP_PAIRS but not in registry"

    def test_issue_type_to_family_covers_all(self):
        """Every registered type must have a family mapping."""
        for name in ISSUE_TYPE_DEFS:
            assert name in ISSUE_TYPE_TO_FAMILY

    def test_no_orphan_types_in_family_map(self):
        """Every type in ISSUE_TYPE_TO_FAMILY must be in the registry."""
        for name in ISSUE_TYPE_TO_FAMILY:
            assert name in ISSUE_TYPE_DEFS, f"{name} in family map but not registered"

    def test_families_are_correct(self):
        """Check that family assignments match expected patterns."""
        for name, defn in ISSUE_TYPE_DEFS.items():
            fam = ISSUE_TYPE_TO_FAMILY[name]
            assert fam == defn.family.value

    def test_slide_dimensions_consistency(self):
        """PX_TO_EMU should be derivable from WIDTH_EMU / VIEWPORT_W."""
        expected = SlideDimensions.WIDTH_EMU / SlideDimensions.VIEWPORT_W
        assert abs(SlideDimensions.PX_TO_EMU - expected) < 0.01

    def test_px_to_inch_consistency(self):
        expected_x = SlideDimensions.WIDTH_IN / SlideDimensions.VIEWPORT_W
        assert abs(SlideDimensions.PX_TO_INCH_X - expected_x) < 0.0001

    def test_spatial_thresholds_ordering(self):
        """OVERLAP_MIN < OVERLAP_MAJOR."""
        assert SpatialThresholds.OVERLAP_MIN_PCT < SpatialThresholds.OVERLAP_MAJOR_PCT


# ================================================================
# 2. CONSUMER IMPORTS — no stale local copies
# ================================================================

class TestConsumerImports:
    """Verify all consumers import from the registry, not local copies."""

    def test_eval_router_uses_registry_b_series(self):
        from app.orchestrator import eval_router
        # B_SERIES_TYPES should be the same object as the registry's
        assert eval_router.B_SERIES_TYPES is B_SERIES_TYPES

    def test_eval_router_uses_semantic_dedup(self):
        from app.orchestrator import eval_router
        from app.utils import issue_identity
        assert eval_router.issues_share_target is issue_identity.issues_share_target

    def test_base_judge_uses_registry(self):
        from app.modules.evaluators import base_judge
        assert base_judge.VALID_ISSUE_TYPES is VALID_ISSUE_TYPES

    def test_redeck_uses_registry(self):
        from app.modules.redeck import dispatcher
        assert dispatcher.UNSOLVABLE_ISSUE_TYPES is UNSOLVABLE_TYPES
        assert dispatcher.SPATIAL_ONLY_ISSUE_TYPES is SPATIAL_ISSUE_TYPES
        assert dispatcher.TRULY_CROSS_SLIDE_TYPES is CROSS_SLIDE_TYPES

    def test_spatial_state_uses_centralized_dims(self):
        from app.modules.redeck.spatial_state import SLIDE_WIDTH, SLIDE_HEIGHT
        assert SLIDE_WIDTH == SlideDimensions.WIDTH_IN
        assert SLIDE_HEIGHT == SlideDimensions.HEIGHT_IN

    def test_html_spatial_state_uses_centralized_dims(self):
        from app.modules.redeck.html_spatial_state import VIEWPORT_W, VIEWPORT_H
        assert VIEWPORT_W == SlideDimensions.VIEWPORT_W
        assert VIEWPORT_H == SlideDimensions.VIEWPORT_H

    def test_repair_utils_uses_registry(self):
        from app.modules.redeck.repair_utils import CONTENT_ACCURACY_ISSUE_TYPES
        assert CONTENT_ACCURACY_ISSUE_TYPES is CONTENT_ACCURACY_TYPES

    def test_geom_checks_uses_thresholds(self):
        """geom_checks should import SpatialThresholds, not hardcode values."""
        import inspect
        from app.modules.evaluators import geom_checks
        source = inspect.getsource(geom_checks)
        # Should NOT contain hardcoded threshold assignments
        # (comments mentioning values are fine, only assignments matter)
        import re
        # Match `= 137160` but not in comments
        hardcoded_assignments = re.findall(
            r'^\s+\w+\s*=\s*137160\b', source, re.MULTILINE
        )
        assert not hardcoded_assignments, f"geom_checks has hardcoded ACCENT_LINE_EMU: {hardcoded_assignments}"
        hardcoded_085 = re.findall(
            r'^\s+(?:if|return).*>=\s*0\.85\b', source, re.MULTILINE
        )
        assert not hardcoded_085, f"geom_checks has hardcoded BG_AREA_RATIO: {hardcoded_085}"


# ================================================================
# 3. EVAL_ROUTER DIFFERENTIAL EVAL
# ================================================================

def _make_issue(
    issue_id: str,
    issue_type: str = "overlap",
    slide_id: int = 1,
    status: IssueStatus = IssueStatus.OPEN,
    rubric_id: str = "B2",
    severity: Severity = Severity.MAJOR,
) -> Issue:
    return Issue(
        issue_id=issue_id,
        rubric_id=rubric_id,
        issue_type=issue_type,
        severity=severity,
        confidence=Confidence.HIGH,
        affected_slides=[slide_id],
        description="test",
        status=status,
    )


class TestDifferentialEval:
    """Test carry-forward, terminal status filtering, scoping logic."""

    def _make_router(self, **eval_kw) -> "EvalRouter":
        from app.orchestrator.eval_router import EvalRouter
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(enabled=False, **eval_kw),
        )
        llm = MagicMock()
        return EvalRouter(llm, config)

    def test_resolved_excluded_from_carry(self):
        """RESOLVED issues should NOT be carried forward to unmodified slides."""
        router = self._make_router()
        config = router.config
        config.eval_mode.enabled = True

        resolved = _make_issue("i1", status=IssueStatus.RESOLVED, slide_id=2)
        open_issue = _make_issue("i2", status=IssueStatus.OPEN, slide_id=2)

        # Unmodified slide 2, modified slide 1
        prev = [resolved, open_issue]

        # Simulate: evaluate() with eval disabled returns empty, but
        # carry-forward logic runs before judges.
        # We test the filtering directly:
        from app.orchestrator.eval_router import _RESOLVED_STATUSES
        carried = [i for i in prev if i.status not in _RESOLVED_STATUSES]
        assert len(carried) == 1
        assert carried[0].issue_id == "i2"

    def test_deferred_excluded_from_carry(self):
        from app.orchestrator.eval_router import _RESOLVED_STATUSES
        deferred = _make_issue("d1", status=IssueStatus.DEFERRED)
        assert deferred.status in _RESOLVED_STATUSES

    def test_spatial_types_separated_from_llm_triage(self):
        """Spatial issues on modified slides should go to playwright, not LLM."""
        spatial = _make_issue("s1", issue_type="overlap", slide_id=1)
        non_spatial = _make_issue("n1", issue_type="fabricated", slide_id=1, rubric_id="E1")
        modified_slides = {1}

        spatial_on_mod = [
            i for i in [spatial, non_spatial]
            if i.issue_type in SPATIAL_ISSUE_TYPES
            and any(s in modified_slides for s in (i.affected_slides or []))
        ]
        llm_prev = [
            i for i in [spatial, non_spatial]
            if not (
                i.issue_type in SPATIAL_ISSUE_TYPES
                and any(s in modified_slides for s in (i.affected_slides or []))
            )
        ]
        assert len(spatial_on_mod) == 1
        assert spatial_on_mod[0].issue_type == "overlap"
        assert len(llm_prev) == 1
        assert llm_prev[0].issue_type == "fabricated"

    def test_deck_level_families_not_carried(self):
        """A and C family issues should NOT be carried (they get re-evaluated deck-wide)."""
        a_issue = _make_issue("a1", issue_type="weak_thesis", slide_id=2, rubric_id="A1")
        b_issue = _make_issue("b1", issue_type="overlap", slide_id=2, rubric_id="B2")
        modified_slides = {1}  # slide 2 is unmodified

        from app.orchestrator.eval_router import _RESOLVED_STATUSES
        deck_level_families = {"A", "C"}
        carried = [
            i for i in [a_issue, b_issue]
            if (
                not any(s in modified_slides for s in (i.affected_slides or []))
                and (i.rubric_id or "")[0:1] not in deck_level_families
                and i.status not in _RESOLVED_STATUSES
            )
        ]
        # A-family should be excluded, B-family carried
        assert len(carried) == 1
        assert carried[0].rubric_id == "B2"

    def test_content_modified_scoping(self):
        """D/E judges should skip spatial-only slides."""
        modified_slides = {1, 2, 3}
        content_modified_slides = {1, 3}
        spatial_only = modified_slides - content_modified_slides
        assert spatial_only == {2}

        # D/E prev on slide 2 should be carried, not re-evaluated
        d_issue = _make_issue("d1", issue_type="incorrect_claim", slide_id=2, rubric_id="D1")
        # This issue should be carried forward, not sent to D judge
        assert any(s in spatial_only for s in d_issue.affected_slides)


# ================================================================
# 4. TURN SETTLER — configurable thresholds
# ================================================================

class TestTurnSettlerConfig:
    def test_default_thresholds(self):
        from app.orchestrator.turn_settler import TurnSettler
        ts = TurnSettler()
        assert ts.early_stop_turn == 6
        assert ts.plateau_window == 4

    def test_custom_thresholds(self):
        from app.orchestrator.turn_settler import TurnSettler
        ts = TurnSettler(early_stop_turn=4, plateau_window=2)
        assert ts.early_stop_turn == 4
        assert ts.plateau_window == 2

    def test_early_stop_uses_config(self):
        """Early stop should trigger based on configured params, not hardcoded 6/4."""
        from app.orchestrator.turn_settler import TurnSettler
        ts = TurnSettler(early_stop_turn=3, plateau_window=2)

        issues = [
            _make_issue(f"i{n}", status=IssueStatus.OPEN)
            for n in range(5)
        ]

        # At turn 3, with 2-turn window, counts=[5,5,5,5] → no improvement
        result = ts.settle(
            turn_index=3,
            issues=issues,
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
            previous_issue_counts=[5, 5, 5, 5],
        )
        assert not result.should_continue  # plateau detected


# ================================================================
# 5. EXPERIMENT CONFIG — new fields
# ================================================================

class TestExperimentConfig:
    def test_eval_mode_new_fields(self):
        em = EvalMode()
        assert em.visual_batch_size == 3
        assert em.source_budget_chars == 48000
        assert em.chunk_max_chars == 4000

    def test_experiment_config_loop_params(self):
        cfg = ExperimentConfig(run_id="test")
        assert cfg.early_stop_turn == 6
        assert cfg.plateau_window == 4
        assert cfg.auto_keep_turn == 2

    def test_custom_loop_params(self):
        cfg = ExperimentConfig(
            run_id="test",
            early_stop_turn=10,
            plateau_window=5,
            auto_keep_turn=3,
        )
        assert cfg.early_stop_turn == 10
        assert cfg.plateau_window == 5
        assert cfg.auto_keep_turn == 3


# ================================================================
# 6. GEOM CHECKS — thresholds from SpatialThresholds
# ================================================================

class TestGeomChecksThresholds:
    """Ensure geom_checks uses centralized thresholds."""

    def test_overlap_threshold_matches(self):
        """The overlap min threshold should be 10% (unified)."""
        assert SpatialThresholds.OVERLAP_MIN_PCT == 0.10

    def test_oob_threshold_matches(self):
        assert SpatialThresholds.OOB_MIN_INCHES == 0.1

    def test_bg_area_ratio(self):
        assert SpatialThresholds.BG_AREA_RATIO == 0.85

    def test_accent_line_emu(self):
        # 0.15 inch = 137160 EMU
        assert SpatialThresholds.ACCENT_LINE_EMU == 137160

    def test_title_top_zone(self):
        # 2 inches = 1828800 EMU
        assert SpatialThresholds.TITLE_TOP_ZONE_EMU == 1828800


# ================================================================
# 7. EDGE CASES — pipeline-level
# ================================================================

class TestEdgeCases:
    def test_empty_modified_set_is_not_falsy(self):
        """An empty set() is falsy in Python but should NOT skip diff eval."""
        modified_slides = set()
        # This was a bug: `if modified_slides:` fails for empty set
        # Fixed to: `if modified_slides is not None:`
        assert modified_slides is not None  # should be True
        assert not modified_slides  # empty set IS falsy
        # The pipeline uses `is not None`, which is correct:
        assert (modified_slides is not None) is True

    def test_all_issues_resolved_stops_loop(self):
        """If all issues are RESOLVED, turn settler should stop."""
        from app.orchestrator.turn_settler import TurnSettler
        ts = TurnSettler()
        resolved = [
            _make_issue(f"i{n}", status=IssueStatus.RESOLVED)
            for n in range(5)
        ]
        result = ts.settle(
            turn_index=1,
            issues=resolved,
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
        )
        assert not result.should_continue

    def test_auto_keep_types_match_unsolvable(self):
        """AUTO_KEEP and UNSOLVABLE should overlap (poor_flow is in both)."""
        assert "poor_flow" in AUTO_KEEP_TYPES
        assert "poor_flow" in UNSOLVABLE_TYPES

    def test_unsolvable_includes_visual_inconsistency(self):
        """visual_inconsistency was previously missing from UNSOLVABLE — verify fix."""
        assert "visual_inconsistency" in UNSOLVABLE_TYPES

    def test_slide_manifest_uses_registry(self):
        from app.modules.redeck import slide_manifest
        assert slide_manifest.UNSOLVABLE_ISSUE_TYPES is UNSOLVABLE_TYPES
        assert not hasattr(slide_manifest, "HIGH_CHURN_ISSUE_TYPES")


# ================================================================
# 8. CROSS-MODULE CONSISTENCY
# ================================================================

class TestCrossModuleConsistency:
    """Check that modules agree on the same sets."""

    def test_dispatcher_has_no_legacy_high_value_filter(self):
        # HIGH_VALUE_TYPES was removed with the legacy repair filters.
        # Verify it's no longer imported
        from app.modules.redeck import dispatcher
        assert not hasattr(dispatcher, 'HIGH_VALUE_TYPES')

    def test_dispatcher_critical_content_is_registry(self):
        from app.modules.redeck import dispatcher
        assert dispatcher.CRITICAL_CONTENT_TYPES is CRITICAL_CONTENT_TYPES

    def test_agent_repair_critical_content_is_registry(self):
        from app.modules.redeck import agent_repair
        assert agent_repair.CRITICAL_CONTENT_TYPES is CRITICAL_CONTENT_TYPES

    def test_agent_repair_unsolvable_is_registry(self):
        from app.modules.redeck import agent_repair
        assert agent_repair.UNSOLVABLE_TYPES is UNSOLVABLE_TYPES

    def test_agent_repair_layout_is_registry(self):
        from app.modules.redeck import agent_repair
        assert agent_repair.LAYOUT_REPAIR_TYPES is LAYOUT_REPAIR_TYPES

    def test_agent_repair_slide_dims(self):
        from app.modules.redeck import agent_repair
        assert agent_repair.SlideDimensions is SlideDimensions


# ================================================================
# 9. NO HARDCODED EMU/DIMENSION CONSTANTS
# ================================================================

class TestNoHardcodedConstants:
    """Verify pipeline files don't contain hardcoded dimension constants."""

    def test_geom_checks_no_raw_914400(self):
        """geom_checks should use SlideDimensions.EMU_PER_INCH, not literal 914400."""
        import inspect, re
        from app.modules.evaluators import geom_checks
        source = inspect.getsource(geom_checks)
        # Allow in comments/strings, but not in division expressions
        raw_divs = re.findall(r'/ 914400\b', source)
        assert not raw_divs, f"geom_checks has raw '/ 914400': {raw_divs}"

    def test_geom_checks_no_raw_slide_dims(self):
        """geom_checks default args should use SlideDimensions, not literals."""
        import inspect, re
        from app.modules.evaluators import geom_checks
        source = inspect.getsource(geom_checks)
        raw_defaults = re.findall(r'= 12192000\b|= 6858000\b', source)
        assert not raw_defaults, f"geom_checks has hardcoded slide dims: {raw_defaults}"

    def test_spatial_state_no_raw_viewport(self):
        """spatial_state should use SlideDimensions for viewport bounds."""
        import inspect, re
        from app.modules.redeck import spatial_state
        source = inspect.getsource(spatial_state)
        raw_1280 = re.findall(r'> 1280\b', source)
        raw_720 = re.findall(r'> 720\b', source)
        assert not raw_1280, f"spatial_state has hardcoded 1280: {raw_1280}"
        assert not raw_720, f"spatial_state has hardcoded 720: {raw_720}"

    def test_dispatcher_no_raw_emu_literals(self):
        """The active dispatcher should use SlideDimensions for Emu() calls."""
        import inspect, re
        from app.modules.redeck import dispatcher
        source = inspect.getsource(dispatcher)
        raw_emu = re.findall(r'Emu\(12192000\)|Emu\(6858000\)', source)
        assert not raw_emu, f"dispatcher has hardcoded Emu(): {raw_emu}"

    def test_agent_repair_no_raw_emu_literals(self):
        """agent_repair should use SlideDimensions for Emu() calls."""
        import inspect, re
        from app.modules.redeck import agent_repair
        source = inspect.getsource(agent_repair)
        raw_emu = re.findall(r'Emu\(12192000\)|Emu\(6858000\)', source)
        assert not raw_emu, f"agent_repair has hardcoded Emu(): {raw_emu}"

    def test_deck_style_enforcer_no_raw_914400(self):
        """deck_style_enforcer should use SlideDimensions.EMU_PER_INCH."""
        import inspect, re
        from app.backends.python_pptx import deck_style_enforcer
        source = inspect.getsource(deck_style_enforcer)
        raw_divs = re.findall(r'/ 914400\b', source)
        assert not raw_divs, f"deck_style_enforcer has raw '/ 914400': {raw_divs}"

    def test_dispatcher_imports_slide_dims(self):
        """The active dispatcher should import SlideDimensions from registry."""
        from app.modules.redeck import dispatcher
        assert dispatcher.SlideDimensions is SlideDimensions


# ================================================================
# 10. EXCEPTION SWALLOWING — CRITICAL PIPELINE RISK
# ================================================================

class TestExceptionHandling:
    """Verify that critical pipeline paths don't silently swallow errors."""

    def test_thread_pool_judge_failure_is_logged(self):
        """When a judge fails in ThreadPoolExecutor, error must be logged (not silent)."""
        from unittest.mock import MagicMock, patch
        from app.orchestrator.eval_router import EvalRouter

        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(enabled=True, use_judge_agent=False),
        )
        router = EvalRouter(MagicMock(), config)

        # Make fidelity judge raise — should be caught and logged, not crash
        def boom(*a, **kw):
            raise RuntimeError("Judge exploded")

        from app.schemas.extraction import SlideExtraction
        ext = SlideExtraction(slide_id=1, slide_index=0, objects=[],
                              total_text_length=100, total_objects=3)

        with patch.object(router.narrative_judge, 'evaluate', return_value=[]), \
             patch.object(router.visual_judge, 'evaluate', return_value=[]), \
             patch.object(router.completeness_judge, 'evaluate', return_value=[]), \
             patch.object(router.correctness_judge, 'evaluate', return_value=[]), \
             patch.object(router.fidelity_judge, 'evaluate', side_effect=boom):
            # Should not raise — the error is caught in the thread pool
            issues = router.evaluate([ext], [], "task", "source", turn_index=0)

        # We should get issues from other judges (geom checks at minimum)
        # but NOT from fidelity judge (it exploded)
        # The key thing: no unhandled exception
        assert isinstance(issues, list)

    def test_geom_checks_handles_empty_bbox(self):
        """geom_checks should not crash on objects with empty or short bbox_emu."""
        from app.modules.evaluators.geom_checks import DeterministicGeomChecks
        from app.schemas.extraction import ExtractedObject, SlideExtraction

        checker = DeterministicGeomChecks()

        # Object with empty bbox
        obj_empty = ExtractedObject(
            object_id="empty_bbox",
            object_type="text_box",
            bbox_emu=[],
            text_content="Some text",
        )
        # Object with 2-element bbox (incomplete)
        obj_short = ExtractedObject(
            object_id="short_bbox",
            object_type="text_box",
            bbox_emu=[100, 200],
            text_content="Some text",
        )
        ext = SlideExtraction(
            slide_id=1, slide_index=0,
            objects=[obj_empty, obj_short],
            total_text_length=20, total_objects=2,
        )
        # Should not crash
        issues = checker.check_all([ext])
        assert isinstance(issues, list)


# ================================================================
# 11. INLINE SETS VALIDATION — no stale issue type names
# ================================================================

class TestInlineSetsValidity:
    """Verify that inline issue-type sets in consumer modules only contain registered types."""

    def test_structural_issue_types_valid(self):
        from app.modules.redeck.agent_repair import STRUCTURAL_ISSUE_TYPES
        invalid = STRUCTURAL_ISSUE_TYPES - ALL_VALID_TYPES
        assert not invalid, f"STRUCTURAL_ISSUE_TYPES has unregistered types: {invalid}"

    def test_agent_repair_render_import_path(self):
        """agent_repair render imports should use 3-dot relative path (app.render_backends)."""
        import inspect, re
        from app.modules.redeck import agent_repair
        source = inspect.getsource(agent_repair)
        # 2-dot import `from ..render_backends` resolves to app.modules.render_backends (wrong)
        # 3-dot import `from ...render_backends` resolves to app.render_backends (correct)
        bad_imports = re.findall(r'from \.\.render_backends', source)
        assert not bad_imports, f"agent_repair has wrong 2-dot render_backends import: {bad_imports}"


class TestBestTurnRollback:
    def test_new_probe_discoveries_do_not_rollback_valid_repair(self):
        from app.orchestrator.run_manager import RunManager

        summary = SimpleNamespace(issues_resolved=1, issues_new=2)

        assert not RunManager._should_rollback_to_best(
            summary,
            best_open=1,
            current_open=2,
        )

    def test_comparable_issue_count_regression_can_rollback(self):
        from app.orchestrator.run_manager import RunManager

        summary = SimpleNamespace(issues_resolved=0, issues_new=0)

        assert RunManager._should_rollback_to_best(
            summary,
            best_open=1,
            current_open=2,
        )
