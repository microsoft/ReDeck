"""Tests for CaseLoader module."""

import pytest

from app.modules.case_loader import CaseLoader
from app.schemas.case_state import CaseState


class TestCaseLoader:
    """Test CaseLoader with real case_01 data."""

    def test_load_case_01_successfully(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        case_state = loader.load("case_01")
        assert isinstance(case_state, CaseState)
        assert case_state.case_id == "case_01"

    def test_intent_extraction(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        case_state = loader.load("case_01")
        intent = case_state.intent
        assert intent.audience == "AI/ML researchers"
        assert intent.deck_type == "conference_talk"
        assert intent.page_budget == [8, 10]
        assert intent.editable_required is True

    def test_must_cover_extraction(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        case_state = loader.load("case_01")
        must_cover = case_state.intent.must_cover
        # The task brief has a "Must-Cover Points" section with bullet items
        assert len(must_cover) > 0
        # Check at least some expected topics
        cover_text = " ".join(must_cover).lower()
        assert "benchmark" in cover_text or "model" in cover_text or "accuracy" in cover_text

    def test_task_brief_loaded(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        case_state = loader.load("case_01")
        assert len(case_state.task_brief) > 0
        assert "Multi-Modal" in case_state.task_brief or "multi-modal" in case_state.task_brief

    def test_constraints_loaded(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        case_state = loader.load("case_01")
        assert case_state.constraints.get("case_id") == "case_01"
        assert "page_budget" in case_state.constraints

    def test_case_dir_stored(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        case_state = loader.load("case_01")
        assert "case_01" in case_state.case_dir

    def test_loading_nonexistent_case_raises(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        with pytest.raises(FileNotFoundError, match="Case directory not found"):
            loader.load("case_nonexistent_999")

    def test_loading_from_nonexistent_dir_raises(self, tmp_path):
        loader = CaseLoader(cases_dir=tmp_path / "no_such_dir")
        with pytest.raises(FileNotFoundError):
            loader.load("case_01")

    def test_empty_case_directory(self, tmp_path):
        """A case directory with no task_brief or constraints should still load."""
        case_dir = tmp_path / "empty_case"
        case_dir.mkdir()
        loader = CaseLoader(cases_dir=tmp_path)
        case_state = loader.load("empty_case")
        assert case_state.case_id == "empty_case"
        assert case_state.task_brief == ""
        assert case_state.constraints == {}

    def test_must_avoid_extraction(self, case_01_dir):
        loader = CaseLoader(cases_dir=case_01_dir.parent)
        case_state = loader.load("case_01")
        must_avoid = case_state.intent.must_avoid
        # case_01 task_brief has a "Must-Avoid" section
        assert len(must_avoid) > 0
        avoid_text = " ".join(must_avoid).lower()
        assert "marketing" in avoid_text or "unsupported" in avoid_text

    def test_extract_must_cover_private_method(self):
        """Test the _extract_must_cover parser on synthetic text."""
        loader = CaseLoader()
        brief = (
            "## Must-Cover Points\n"
            "- Topic A\n"
            "- Topic B\n"
            "- Topic C\n"
            "\n"
            "## Next Section\n"
            "Other stuff\n"
        )
        result = loader._extract_must_cover(brief)
        assert result == ["Topic A", "Topic B", "Topic C"]

    def test_extract_must_avoid_private_method(self):
        """Test the _extract_must_avoid parser on synthetic text."""
        loader = CaseLoader()
        brief = (
            "## Must-Avoid\n"
            "- Bad thing 1\n"
            "- Bad thing 2\n"
            "\n"
            "## Next Section\n"
        )
        result = loader._extract_must_avoid(brief)
        assert result == ["Bad thing 1", "Bad thing 2"]
