"""Tests for DeterministicGeomChecks evaluator."""

import pytest

from app.modules.evaluators.geom_checks import DeterministicGeomChecks
from app.schemas.common import Severity
from app.schemas.extraction import ExtractedObject, SlideExtraction


def _make_extraction(
    slide_id: int,
    objects: list[ExtractedObject],
) -> SlideExtraction:
    """Helper to create a SlideExtraction from objects."""
    total_text = sum(len(o.text_content) for o in objects)
    return SlideExtraction(
        slide_id=slide_id,
        slide_index=slide_id - 1,
        title=objects[0].text_content[:50] if objects and objects[0].text_content else "",
        objects=objects,
        total_text_length=total_text,
        total_objects=len(objects),
    )


def _text_obj(
    object_id: str,
    left: int,
    top: int,
    width: int,
    height: int,
    text: str = "sample text",
    font_sizes: list[float] | None = None,
) -> ExtractedObject:
    """Helper to create a text_box ExtractedObject."""
    return ExtractedObject(
        object_id=object_id,
        object_type="text_box",
        bbox_emu=[left, top, width, height],
        text_content=text,
        font_sizes_pt=font_sizes or [],
    )


class TestDeterministicGeomChecks:
    """Test all geometry-based checks."""

    def test_clean_slide_no_issues(self):
        """A well-formed slide should produce no issues."""
        checker = DeterministicGeomChecks()
        objs = [
            _text_obj("title", 457200, 457200, 5000000, 914400, "Title"),
            _text_obj("body", 457200, 1500000, 5000000, 3000000, "Body text",
                       font_sizes=[18.0]),
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        # Filter out source_attribution and similar non-layout issues
        layout_issues = [i for i in issues if i.issue_type in {
            "overlap", "out_of_bounds", "font_too_small", "text_overflow",
            "empty_slide", "density_exceeded", "text_verbose",
        }]
        assert len(layout_issues) == 0

    def test_empty_slide_detection(self):
        """A slide with no objects should be flagged."""
        checker = DeterministicGeomChecks()
        ext = SlideExtraction(
            slide_id=1,
            slide_index=0,
            objects=[],
            total_text_length=0,
            total_objects=0,
        )
        issues = checker.check_all([ext])
        empty_issues = [i for i in issues if i.issue_type == "empty_slide"]
        assert len(empty_issues) == 1
        assert empty_issues[0].rubric_id == "B2"

    def test_empty_slide_no_text(self):
        """A slide with objects but no text should be flagged."""
        checker = DeterministicGeomChecks()
        obj = ExtractedObject(
            object_id="shape1",
            object_type="shape",
            bbox_emu=[100, 100, 200, 200],
            text_content="",
        )
        ext = _make_extraction(1, [obj])
        # Override total_text_length to 0
        ext.total_text_length = 0
        issues = checker.check_all([ext])
        empty_issues = [i for i in issues if i.issue_type == "empty_slide"]
        assert len(empty_issues) == 1

    def test_overlap_detection(self):
        """Two overlapping objects should produce an overlap issue."""
        checker = DeterministicGeomChecks()
        objs = [
            _text_obj("obj_a", 100, 100, 500, 500, "A"),
            _text_obj("obj_b", 300, 300, 500, 500, "B"),  # overlaps with A
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        overlap_issues = [i for i in issues if i.issue_type == "overlap"]
        assert len(overlap_issues) == 1
        assert overlap_issues[0].rubric_id == "B3"
        assert "obj_a" in overlap_issues[0].evidence.object_refs
        assert "obj_b" in overlap_issues[0].evidence.object_refs

    def test_no_overlap_when_adjacent(self):
        """Two adjacent (non-overlapping) objects should not trigger overlap."""
        checker = DeterministicGeomChecks()
        objs = [
            _text_obj("obj_a", 0, 0, 500, 500, "A"),
            _text_obj("obj_b", 500, 0, 500, 500, "B"),  # starts exactly where A ends
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        overlap_issues = [i for i in issues if i.issue_type == "overlap"]
        assert len(overlap_issues) == 0

    def test_out_of_bounds_detection(self):
        """An object extending beyond slide boundary should be flagged."""
        checker = DeterministicGeomChecks(
            slide_width_emu=12192000,
            slide_height_emu=6858000,
        )
        objs = [
            _text_obj("oob_right", 11000000, 100, 2000000, 500, "OOB Right"),
            # left=11000000, width=2000000 -> right=13000000 > 12192000
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        oob_issues = [i for i in issues if i.issue_type == "out_of_bounds"]
        assert len(oob_issues) == 1
        assert oob_issues[0].rubric_id == "B3"

    def test_out_of_bounds_bottom(self):
        """Object extending below slide bottom."""
        checker = DeterministicGeomChecks(
            slide_width_emu=12192000,
            slide_height_emu=6858000,
        )
        objs = [
            _text_obj("oob_bottom", 100, 6000000, 1000, 2000000, "OOB Bottom"),
            # top=6000000, height=2000000 -> bottom=8000000 > 6858000
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        oob_issues = [i for i in issues if i.issue_type == "out_of_bounds"]
        assert len(oob_issues) == 1

    def test_no_oob_when_within_bounds(self):
        """An object fully within slide bounds should not trigger OOB."""
        checker = DeterministicGeomChecks()
        objs = [
            _text_obj("inside", 457200, 457200, 5000000, 3000000, "Inside"),
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        oob_issues = [i for i in issues if i.issue_type == "out_of_bounds"]
        assert len(oob_issues) == 0

    @pytest.mark.xfail(reason="Font checks removed in HTML mode — detected by Playwright/visual judge instead")
    def test_font_too_small_detection(self):
        """Font below minimum should be flagged."""
        checker = DeterministicGeomChecks(min_font_pt=18.0)
        objs = [
            # Use realistic bbox (>2" wide, >0.3" tall) and text >30 chars
            _text_obj("small_font", 100, 100, 3000000, 914400,
                       "This is a body text paragraph with small font that should be flagged for readability issues",
                       font_sizes=[10.0]),
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        font_issues = [i for i in issues if i.issue_type == "font_too_small"]
        assert len(font_issues) == 1
        assert font_issues[0].rubric_id == "B4"

    @pytest.mark.xfail(reason="Font checks removed in HTML mode — detected by Playwright/visual judge instead")
    def test_font_very_small_is_major(self):
        """Font significantly below threshold should be MAJOR."""
        checker = DeterministicGeomChecks(min_font_pt=18.0)
        objs = [
            # 8pt < 18*0.75 = 13.5 -> MAJOR
            _text_obj("tiny", 100, 100, 3000000, 914400,
                       "This is a long paragraph with tiny font that needs to be flagged as a major readability issue",
                       font_sizes=[8.0]),
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        font_issues = [i for i in issues if i.issue_type == "font_too_small"]
        assert len(font_issues) == 1
        assert font_issues[0].severity == Severity.MAJOR

    @pytest.mark.xfail(reason="Font checks removed in HTML mode — detected by Playwright/visual judge instead")
    def test_font_slightly_small_is_minor(self):
        """Font just below threshold should be MINOR."""
        checker = DeterministicGeomChecks(min_font_pt=18.0)
        objs = [
            # 16pt > 18*0.75=13.5 -> MINOR
            _text_obj("small", 100, 100, 3000000, 914400,
                       "This is a paragraph with slightly small font that should be flagged as minor issue for readability",
                       font_sizes=[16.0]),
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        font_issues = [i for i in issues if i.issue_type == "font_too_small"]
        assert len(font_issues) == 1
        assert font_issues[0].severity == Severity.MINOR

    def test_font_size_ok(self):
        """Font at or above minimum should not be flagged."""
        checker = DeterministicGeomChecks(min_font_pt=18.0)
        objs = [
            _text_obj("ok_font", 100, 100, 5000, 2000, "OK", font_sizes=[18.0]),
        ]
        ext = _make_extraction(1, objs)
        issues = checker.check_all([ext])
        font_issues = [i for i in issues if i.issue_type == "font_too_small"]
        assert len(font_issues) == 0

    def test_multiple_slides(self):
        """Check that issues are found across multiple slides."""
        checker = DeterministicGeomChecks()
        ext1 = _make_extraction(1, [
            _text_obj("ok", 100, 100, 5000, 2000, "OK text", font_sizes=[20.0]),
        ])
        ext2 = SlideExtraction(
            slide_id=2,
            slide_index=1,
            objects=[],
            total_text_length=0,
            total_objects=0,
        )
        issues = checker.check_all([ext1, ext2])
        assert any(i.affected_slides == [2] for i in issues)
