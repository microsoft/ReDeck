"""Tests for EvalRouter with mocked LLM calls."""

import pytest
import json
from unittest.mock import MagicMock, patch

from app.orchestrator.eval_router import EvalRouter
from app.schemas.experiment_config import ExperimentConfig, EvalMode
from app.schemas.extraction import ExtractedObject, SlideExtraction


def _make_extraction(slide_id: int) -> SlideExtraction:
    """Create a simple extraction for testing."""
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


class TestEvalRouter:
    """Test EvalRouter routing logic with mocked LLM."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM client."""
        llm = MagicMock()
        llm.call_text.return_value = '{"issues": []}'
        llm.call_vision.return_value = '{"issues": []}'
        llm.call_multiturn.return_value = '{"issues": []}'
        llm.call_json.return_value = {"issues": []}
        llm.call_vision_json.return_value = {"issues": []}
        return llm

    @pytest.fixture
    def default_config(self):
        return ExperimentConfig(run_id="test_run")

    @pytest.fixture
    def extractions(self):
        return [_make_extraction(1), _make_extraction(2)]

    def test_eval_disabled_returns_empty(self, mock_llm, extractions):
        """When eval is disabled, no issues should be returned."""
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(enabled=False),
        )
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt", return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            issues = router.evaluate(extractions, [], "brief", "summary")
            assert len(issues) == 0
            mock_llm.call_text.assert_not_called()

    def test_family_split_routes_all_judges(self, mock_llm, extractions):
        """FAMILY split level should call all LLM judges."""
        from app.schemas.common import EvalSplitLevel
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.FAMILY,
            ),
        )
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt", return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            issues = router.evaluate(extractions, [], "brief", "summary")
            # Should call call_text for narrative, completeness, visual (3 judges)
            # and call_multiturn for correctness, fidelity (2 agent judges)
            total_calls = (
                mock_llm.call_text.call_count
                + mock_llm.call_multiturn.call_count
                + mock_llm.call_vision.call_count
            )
            assert total_calls >= 4

    def test_monolithic_split(self, mock_llm, extractions):
        """MONOLITHIC split level uses only narrative judge."""
        from app.schemas.common import EvalSplitLevel
        config = ExperimentConfig(
            run_id="test",
            eval_mode=EvalMode(
                enabled=True,
                split_level=EvalSplitLevel.MONOLITHIC,
            ),
        )
        with patch("app.modules.evaluators.base_judge.BaseJudge._load_prompt", return_value="mock prompt"):
            router = EvalRouter(mock_llm, config)
            issues = router.evaluate(extractions, [], "brief", "summary")
            # In monolithic mode, only narrative judge is called
            assert mock_llm.call_text.call_count >= 1

    def test_visual_judge_includes_exact_visible_text(self, mock_llm, default_config, extractions):
        """Typography findings can be checked against extracted characters."""
        with patch(
            "app.modules.evaluators.base_judge.BaseJudge._load_prompt",
            return_value="mock prompt",
        ):
            router = EvalRouter(mock_llm, default_config)
            router.visual_judge.evaluate(extractions, [], scope_slides=[1])

        user_content = mock_llm.call_text.call_args.kwargs["user_content"]
        assert '"visible_text": "Content for slide 1"' in user_content

    def test_local_coverage_probe_receives_deck_context(
        self, mock_llm, default_config, extractions,
    ):
        from app.schemas.issue_types import PROBE_REGISTRY

        with patch(
            "app.modules.evaluators.base_judge.BaseJudge._load_prompt",
            return_value="mock prompt",
        ):
            router = EvalRouter(mock_llm, default_config)
            payload = router.svg_visual_probe._build_content_probe_content(
                PROBE_REGISTRY["C03"],
                [1],
                extractions,
                "source",
                None,
                None,
                None,
            )

        data = json.loads(payload)
        assert [slide["slide_id"] for slide in data["slide_content"]] == [1]
        assert [slide["slide_id"] for slide in data["deck_context"]] == [1, 2]
