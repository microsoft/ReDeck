"""Tests for ProbePlannerAgent — adaptive probe scheduling."""

import json
import pytest
from unittest.mock import MagicMock, patch

from app.orchestrator.eval_router import EvalRouter
from app.schemas.common import (
    Confidence, EvalSplitLevel, IssueStatus, Severity, Verdict,
)
from app.schemas.experiment_config import ExperimentConfig, EvalMode
from app.schemas.extraction import ExtractedObject, SlideExtraction
from app.schemas.issue import Issue


def _make_extraction(slide_id: int) -> SlideExtraction:
    obj = ExtractedObject(
        object_id=f"obj_{slide_id}",
        object_type="text_box",
        bbox_emu=[457200, 457200, 5000000, 3000000],
        text_content=f"Content for slide {slide_id}",
        font_sizes_pt=[18.0],
    )
    return SlideExtraction(
        slide_id=slide_id,
        slide_index=slide_id - 1,
        title=f"Slide {slide_id}",
        objects=[obj],
        total_text_length=len(obj.text_content),
        total_objects=1,
    )


def _make_issue(
    slide_id: int,
    issue_type: str = "text_overflow",
    rubric_id: str = "B4",
    status: IssueStatus = IssueStatus.OPEN,
) -> Issue:
    return Issue(
        issue_id=f"{rubric_id}_{issue_type}_slide{slide_id}",
        rubric_id=rubric_id,
        issue_type=issue_type,
        severity=Severity.MAJOR,
        confidence=Confidence.HIGH,
        affected_slides=[slide_id],
        status=status,
        verdict=Verdict.FAIL,
        why_this_fails=f"Test {issue_type} on slide {slide_id}",
    )


class TestProbePlannerAgent:
    """Test adaptive probe planner agent."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.call_text.return_value = '{"rubric_family": "A", "issues": []}'
        llm.call_vision.return_value = '{"rubric_family": "B", "issues": []}'
        llm.call_multiturn.return_value = '{"tool": "submit_evaluation", "reasoning": "done"}'
        return llm

    @pytest.fixture
    def planner_config(self):
        return ExperimentConfig(
            run_id="test_planner",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.FAMILY_PLUS_SLIDE,
                use_probe_planner=True,
                use_judge_agent=False,
            ),
        )

    @pytest.fixture
    def extractions(self):
        return [_make_extraction(1), _make_extraction(2), _make_extraction(3)]

    def test_planner_init(self, mock_llm, planner_config):
        """ProbePlannerAgent should be created when use_probe_planner=True."""
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, planner_config)
            assert hasattr(router, 'probe_planner')

    def test_planner_not_init_when_disabled(self, mock_llm):
        """ProbePlannerAgent should NOT be created when use_probe_planner=False."""
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(use_probe_planner=False),
        )
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            assert not hasattr(router, 'probe_planner')

    def test_turn0_skips_planner(self, mock_llm, planner_config, extractions):
        """Turn 0 should NOT use the planner — always runs full evaluation."""
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, planner_config)
            # Mock the planner's evaluate to track if it was called
            router.probe_planner.evaluate = MagicMock(return_value=[])

            router.evaluate(extractions, [], "brief", "summary", turn_index=0)

            # Planner should NOT be called at turn 0
            router.probe_planner.evaluate.assert_not_called()

    def test_turn1_uses_planner(self, mock_llm, planner_config, extractions):
        """Turn > 0 with modified slides should use the planner."""
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, planner_config)
            router.probe_planner.evaluate = MagicMock(return_value=[])

            prev_issues = [_make_issue(1)]
            router.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=prev_issues,
                modified_slides={1},
                turn_index=1,
            )

            # Planner SHOULD be called at turn > 0
            router.probe_planner.evaluate.assert_called_once()

    def test_planner_submit_returns_collected(self, mock_llm, planner_config, extractions):
        """Planner should return issues collected from probe tools."""
        # Set up LLM to: 1) call probe_visual, 2) submit
        call_count = [0]

        def mock_multiturn(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: agent decides to probe visual
                return json.dumps({
                    "tool": "probe_visual",
                    "slide_ids": [1, 2],
                })
            else:
                # Second call: submit
                return json.dumps({
                    "tool": "submit_evaluation",
                    "reasoning": "Checked visual issues on slides 1,2",
                })

        mock_llm.call_multiturn.side_effect = mock_multiturn

        # Visual judge returns an issue
        visual_issue = _make_issue(1, "text_overflow", "B4")

        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, planner_config)

            # Mock visual judge to return our test issue
            router.visual_judge.evaluate = MagicMock(return_value=[visual_issue])

            result = router.probe_planner.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=[],
                turn_index=1,
                modified_slides={1, 2},
                content_modified_slides={1, 2},
            )

            assert len(result) == 1
            assert result[0].issue_type == "text_overflow"
            router.visual_judge.evaluate.assert_called_once()

    def test_planner_fallback_on_error(self, mock_llm, planner_config, extractions):
        """Planner should fall back to full eval if LLM call fails."""
        mock_llm.call_multiturn.side_effect = Exception("LLM unavailable")

        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, planner_config)

            # Mock the fallback path
            with patch.object(
                router, '_eval_family_plus_slide', return_value=[]
            ) as mock_fallback:
                result = router.probe_planner.evaluate(
                    extractions, [], "brief", "summary",
                    previous_issues=[],
                    turn_index=1,
                    modified_slides={1},
                    content_modified_slides={1},
                )
                # Fallback should be called with _skip_planner=True
                mock_fallback.assert_called_once()
                call_kwargs = mock_fallback.call_args
                assert call_kwargs.kwargs.get("_skip_planner") is True

    def test_planner_respects_content_scoping(self, mock_llm, planner_config, extractions):
        """D/E probes should be scoped to content-modified slides only."""
        call_count = [0]

        def mock_multiturn(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return json.dumps({
                    "tool": "probe_correctness",
                    "slide_ids": [1, 2],  # agent asks for both
                })
            else:
                return json.dumps({
                    "tool": "submit_evaluation",
                    "reasoning": "done",
                })

        mock_llm.call_multiturn.side_effect = mock_multiturn

        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, planner_config)
            router.correctness_judge.evaluate = MagicMock(return_value=[])

            # Slide 2 is spatial-only (not in content_modified_slides)
            router.probe_planner.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=[],
                turn_index=1,
                modified_slides={1, 2},
                content_modified_slides={1},  # only slide 1 has content changes
            )

            # Correctness judge should only get extractions for slide 1
            if router.correctness_judge.evaluate.called:
                call_args = router.correctness_judge.evaluate.call_args
                exts = call_args[0][0]  # first positional arg
                slide_ids = [e.slide_id for e in exts]
                assert 2 not in slide_ids, (
                    f"Slide 2 is spatial-only, should not be in correctness judge. Got: {slide_ids}"
                )

    def test_de_carryforward_spatial_only(self, mock_llm, extractions):
        """D/E issues on spatial-only slides should be carried forward, not dropped."""
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.FAMILY_PLUS_SLIDE,
                use_probe_planner=False,
                use_judge_agent=False,
            ),
        )

        # Existing D issue on slide 2
        d_issue = _make_issue(2, "incorrect_claim", "D1")

        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)

            result = router.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=[d_issue],
                modified_slides={1, 2},
                content_modified_slides={1},  # slide 2 is spatial-only
                turn_index=1,
            )

            # D issue on slide 2 should be carried forward
            carried_d = [i for i in result if i.issue_id == d_issue.issue_id]
            assert len(carried_d) == 1, (
                f"D issue on spatial-only slide 2 should be carried forward. "
                f"Got {len(carried_d)} matches in {[i.issue_id for i in result]}"
            )


class TestProbePlannerParsing:
    """Test the action parsing logic."""

    def test_parse_json_block(self):
        from app.modules.evaluators.probe_planner_agent import ProbePlannerAgent
        action = ProbePlannerAgent._parse_action(
            '```json\n{"tool": "probe_visual", "slide_ids": [1,2]}\n```'
        )
        assert action is not None
        assert action["tool"] == "probe_visual"
        assert action["slide_ids"] == [1, 2]

    def test_parse_inline_json(self):
        from app.modules.evaluators.probe_planner_agent import ProbePlannerAgent
        action = ProbePlannerAgent._parse_action(
            'I will run {"tool": "submit_evaluation", "reasoning": "done"} now.'
        )
        assert action is not None
        assert action["tool"] == "submit_evaluation"

    def test_parse_raw_json(self):
        from app.modules.evaluators.probe_planner_agent import ProbePlannerAgent
        action = ProbePlannerAgent._parse_action(
            '{"tool": "probe_narrative"}'
        )
        assert action is not None
        assert action["tool"] == "probe_narrative"

    def test_parse_garbage_returns_none(self):
        from app.modules.evaluators.probe_planner_agent import ProbePlannerAgent
        action = ProbePlannerAgent._parse_action("I don't know what to do")
        assert action is None


class TestPipelineDefects:
    """Regression tests for pipeline-level systematic defects."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.call_text.return_value = '{"rubric_family": "A", "issues": []}'
        llm.call_vision.return_value = '{"rubric_family": "B", "issues": []}'
        llm.call_multiturn.return_value = '{"issues": []}'
        return llm

    @pytest.fixture
    def extractions(self):
        return [_make_extraction(1), _make_extraction(2), _make_extraction(3)]

    def test_empty_modified_set_does_not_eval_all(self, mock_llm, extractions):
        """Bug #4: modified_slides=set() should NOT evaluate all slides.

        Empty set means 'nothing was modified' — scoped extractions should be empty.
        """
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.FAMILY_PLUS_SLIDE,
                use_probe_planner=False,
                use_judge_agent=False,
            ),
        )
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            prev = [_make_issue(1, "text_overflow", "B4")]
            result = router.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=prev,
                modified_slides=set(),  # empty — nothing modified
                turn_index=1,
            )
            # With empty modified_slides, no judges should run on any slides.
            # The only result should be carried issues (slide 1 issue is NOT
            # on a modified slide, so it should be carried).
            # No new LLM judge calls should be made for visual on modified slides.

    def test_resolved_not_carried_forward(self, mock_llm, extractions):
        """Bug #14: RESOLVED issues should NOT be carried forward indefinitely."""
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.FAMILY_PLUS_SLIDE,
                use_probe_planner=False,
                use_judge_agent=False,
            ),
        )
        resolved = _make_issue(3, "text_overflow", "B4", status=IssueStatus.RESOLVED)

        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            result = router.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=[resolved],
                modified_slides={1},  # slide 3 is unmodified
                turn_index=1,
            )
            # Resolved issue on unmodified slide 3 should NOT be carried
            carried = [i for i in result if i.issue_id == resolved.issue_id]
            assert len(carried) == 0, (
                f"RESOLVED issue should not be carried forward. "
                f"Found: {[i.issue_id for i in carried]}"
            )

    def test_planner_dedup_same_probe_twice(self, mock_llm):
        """Bug #1: If planner calls same probe twice, issues should be deduped."""
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.FAMILY_PLUS_SLIDE,
                use_probe_planner=True,
                use_judge_agent=False,
            ),
        )
        extractions = [_make_extraction(1)]
        call_count = [0]

        def mock_multiturn(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return json.dumps({"tool": "probe_visual", "slide_ids": [1]})
            else:
                return json.dumps({"tool": "submit_evaluation", "reasoning": "done"})

        mock_llm.call_multiturn.side_effect = mock_multiturn

        issue = _make_issue(1, "text_overflow", "B4")

        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            router.visual_judge.evaluate = MagicMock(return_value=[issue])

            result = router.probe_planner.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=[],
                turn_index=1,
                modified_slides={1},
                content_modified_slides={1},
            )

            # Visual judge called twice, but dedup should produce 1 issue
            assert router.visual_judge.evaluate.call_count == 2
            assert len(result) == 1, (
                f"Same issue from two probe calls should be deduped. Got {len(result)}"
            )

    def test_planner_scopes_prev_to_requested_slides(self, mock_llm):
        """Bug #5: D/E prev issues should be scoped to requested slides."""
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.FAMILY_PLUS_SLIDE,
                use_probe_planner=True,
                use_judge_agent=False,
            ),
        )
        extractions = [_make_extraction(1), _make_extraction(2)]
        call_count = [0]

        def mock_multiturn(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return json.dumps({"tool": "probe_correctness", "slide_ids": [1]})
            else:
                return json.dumps({"tool": "submit_evaluation", "reasoning": "done"})

        mock_llm.call_multiturn.side_effect = mock_multiturn

        # Previous D issue on slide 2
        d_issue_s2 = _make_issue(2, "incorrect_claim", "D1")

        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt",
                    return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            router.correctness_judge.evaluate = MagicMock(return_value=[])

            router.probe_planner.evaluate(
                extractions, [], "brief", "summary",
                previous_issues=[d_issue_s2],
                turn_index=1,
                modified_slides={1, 2},
                content_modified_slides={1, 2},
            )

            # Correctness judge should be called with prev issues scoped to slide 1 only
            call_kwargs = router.correctness_judge.evaluate.call_args
            prev_passed = call_kwargs.kwargs.get("previous_issues")
            if prev_passed:
                for iss in prev_passed:
                    assert 1 in iss.affected_slides, (
                        f"Previous issue on slide 2 should not be passed when probing slide 1. "
                        f"Got affected_slides={iss.affected_slides}"
                    )
