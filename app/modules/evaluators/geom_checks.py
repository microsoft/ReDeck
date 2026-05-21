"""DeterministicGeomChecks - geometry-based evaluation without LLM."""

import logging
from pathlib import Path

from ...schemas.common import Confidence, IssueStatus, Severity, Verdict
from ...schemas.extraction import SlideExtraction
from ...schemas.issue import Issue, IssueEvidence
from ...schemas.issue_types import SlideDimensions, SpatialThresholds

logger = logging.getLogger(__name__)


class DeterministicGeomChecks:
    """Run deterministic geometric checks on extracted slide data.

    This evaluator does NOT call any LLM.
    It checks: overlap, overflow, out-of-bounds, font lower bound,
    empty slide, missing asset, object anomalies.
    """

    def __init__(
        self,
        min_font_pt: float = 10.0,
        slide_width_emu: int = SlideDimensions.WIDTH_EMU,
        slide_height_emu: int = SlideDimensions.HEIGHT_EMU,
        margin_emu: int = 0,
        html_mode: bool = False,
    ):
        self.min_font_pt = min_font_pt
        self.slide_width = slide_width_emu
        self.slide_height = slide_height_emu
        self.margin = margin_emu
        self.html_mode = html_mode

    def check_all(self, extractions: list[SlideExtraction]) -> list[Issue]:
        """Run all deterministic checks on all slides."""
        issues = []
        for ext in extractions:
            issues.extend(self._check_slide(ext))
        # Tag all geom issues with source_probe_id for regression tracking
        for iss in issues:
            if not iss.source_probe_id:
                iss.source_probe_id = f"geom_{iss.issue_type}"
        logger.info("DeterministicGeomChecks found %d issues", len(issues))
        return issues

    def _check_slide(self, ext: SlideExtraction) -> list[Issue]:
        """Run all checks on a single slide.

        Font/text-overflow/narrow checks removed — only relevant for PPTX mode
        which is no longer supported. HTML overflow is detected by Playwright.
        """
        issues = []
        issues.extend(self._check_empty_slide(ext))
        issues.extend(self._check_empty_placeholders(ext))
        # Overlap & out-of-bounds: always run (Playwright bboxes are accurate)
        issues.extend(self._check_overlaps(ext))
        issues.extend(self._check_out_of_bounds(ext))
        issues.extend(self._check_meta_content(ext))
        issues.extend(self._check_spelling(ext))
        issues.extend(self._check_non_slide_content(ext))
        issues.extend(self._check_bullet_count(ext))
        return issues

    def check_spatial_only(self, ext: SlideExtraction) -> list[Issue]:
        """Run only spatial checks (overlap, OOB, meta-content).

        Lighter-weight alternative to _check_slide for use in codegen
        validation gate where only spatial/content issues matter.
        """
        issues = []
        issues.extend(self._check_overlaps(ext))
        issues.extend(self._check_out_of_bounds(ext))
        issues.extend(self._check_meta_content(ext))
        return issues

    # ── Helper: identify decorative / structural objects ──────────────

    def _is_background_rect(self, obj) -> bool:
        """Return True if this object is a background / section rectangle.

        Heuristic: a "Rectangle" that spans the full slide width (≥95%)
        and covers ≥40% of slide area is almost certainly a background
        fill, not real content.  Also matches full-slide backgrounds (≥85%).
        """
        if obj.object_type != "shape" and "rectangle" not in obj.object_id.lower():
            return False
        if len(obj.bbox_emu) < 4:
            return False
        _, _, w, h = obj.bbox_emu
        obj_area = w * h
        slide_area = self.slide_width * self.slide_height
        if slide_area <= 0:
            return False
        area_ratio = obj_area / slide_area
        width_ratio = w / self.slide_width if self.slide_width > 0 else 0

        # Full-slide background
        if area_ratio >= SpatialThresholds.BG_AREA_RATIO:
            return True
        # Full-width section background (sidebar / banner)
        if width_ratio >= SpatialThresholds.BG_WIDTH_RATIO and area_ratio >= SpatialThresholds.BG_MIN_AREA_RATIO:
            return True
        return False

    @staticmethod
    def _is_accent_line(obj) -> bool:
        """Return True if this object is a thin decorative accent line.

        Accent lines are typically rectangles < 0.15 inch in one dimension
        AND have no text content.  Thin TextBoxes (e.g. subtitle boxes with
        height < 0.15") are NOT accent lines — they contain real content.
        0.15 inch = 137160 EMU.
        """
        if len(obj.bbox_emu) < 4:
            return False
        _, _, w, h = obj.bbox_emu
        thin_threshold = SpatialThresholds.ACCENT_LINE_EMU
        if min(w, h) >= thin_threshold:
            return False
        # Shapes with text content are NOT accent lines — they are thin
        # textboxes (e.g. subtitle placeholders) whose overlaps matter.
        if obj.text_content and len(obj.text_content.strip()) > 0:
            return False
        return True

    @staticmethod
    def _is_accent_adjacent(accent, other) -> bool:
        """Return True if accent line is adjacent to (not cutting through) the other shape.

        An accent line is "adjacent" when its vertical centre is within 0.15"
        of the top or bottom edge of the other shape.  If the accent's centre
        is deeper inside the other shape, it is cutting through content and the
        overlap is NOT intentional.
        """
        if len(accent.bbox_emu) < 4 or len(other.bbox_emu) < 4:
            return False

        accent_top = accent.bbox_emu[1]
        accent_h = accent.bbox_emu[3]
        accent_cy = accent_top + accent_h / 2

        other_top = other.bbox_emu[1]
        other_h = other.bbox_emu[3]
        other_bottom = other_top + other_h

        # Tolerance: accent line adjacency threshold
        edge_tolerance = SpatialThresholds.ACCENT_LINE_EMU

        # Adjacent to top edge
        if abs(accent_cy - other_top) < edge_tolerance:
            return True
        # Adjacent to bottom edge
        if abs(accent_cy - other_bottom) < edge_tolerance:
            return True

        # If accent centre is well inside the other shape, it's cutting through
        return False

    def _is_intentional_overlap(self, a, b) -> bool:
        """Return True if the overlap between a and b is intentional design.

        Intentional patterns:
        1. Background rectangle overlapping anything
        2. Accent line ADJACENT to a text box (title underline pattern)
           — only exempt if accent is near the edge of the other shape,
           not cutting through its middle
        3. Text placed on a decorative shape (text-on-card)
        4. Child element fully contained inside a parent container (card pattern)
        5. Title/subtitle textbox vertical adjacency (phantom overlap from allocated height)
        """
        # Pattern 1: background rectangle
        if self._is_background_rect(a) or self._is_background_rect(b):
            return True

        # Pattern 2: accent line ADJACENT to content (title underline)
        # Only exempt if the accent line is near the top/bottom edge of
        # the other shape — NOT if it cuts through the shape's interior.
        if self._is_accent_line(a) or self._is_accent_line(b):
            accent = a if self._is_accent_line(a) else b
            other = b if self._is_accent_line(a) else a
            if self._is_accent_adjacent(accent, other):
                return True

        # Pattern 4: Child element fully contained inside a parent container.
        # This catches the very common "card" design pattern where a Rectangle
        # (header bar), TextBox (content), Picture, or Table sits inside a
        # Rounded Rectangle (card background).  If the smaller object's bbox
        # is ≥85% contained within the larger object, it's intentional.
        # EXCEPTION: Two TextBoxes both with substantial text are NOT a
        # card pattern — they are overlapping text that creates visual mess.
        a_is_textbox = (a.object_type == "text_box"
                        or "textbox" in a.object_id.lower())
        b_is_textbox = (b.object_type == "text_box"
                        or "textbox" in b.object_id.lower())
        a_has_text = bool(a.text_content and len(a.text_content.strip()) > 5)
        b_has_text = bool(b.text_content and len(b.text_content.strip()) > 5)
        both_text_with_content = a_is_textbox and b_is_textbox and a_has_text and b_has_text

        # HTML inline-in-block pattern: <strong>/<span>/<em>/<a>/<code> inside
        # <li>/<p>/<td>/<div>/<h1-h6> is normal nesting, not a real overlap.
        # The inline element is always fully contained in the block parent.
        if self.html_mode and self._is_html_inline_containment(a, b):
            return True

        if not both_text_with_content and self._is_containment(a, b):
            return True

        # Pattern 5: Title/Subtitle vertical adjacency.
        # TextBoxes with single-line titles are often allocated taller than
        # their rendered text.  Two vertically adjacent TextBoxes whose
        # bounding boxes slightly overlap (< 0.3 inch) are not a real issue.
        if self._is_title_subtitle_adjacency(a, b):
            return True

        # Pattern 3: text-on-shape card (TextBox inside a named shape like
        # "Rounded Rectangle").  The textbox's centre sits within the shape.
        # (a_is_textbox, b_is_textbox already computed above)
        a_is_shape = (a.object_type == "shape"
                      or "rectangle" in a.object_id.lower()
                      or "oval" in a.object_id.lower()
                      or "rounded" in a.object_id.lower())
        b_is_shape = (b.object_type == "shape"
                      or "rectangle" in b.object_id.lower()
                      or "oval" in b.object_id.lower()
                      or "rounded" in b.object_id.lower())

        if (a_is_textbox and b_is_shape) or (b_is_textbox and a_is_shape):
            # Check if the textbox centre is inside the shape
            tb = a if a_is_textbox else b
            sh = b if a_is_textbox else a
            if len(tb.bbox_emu) >= 4 and len(sh.bbox_emu) >= 4:
                tb_cx = tb.bbox_emu[0] + tb.bbox_emu[2] / 2
                tb_cy = tb.bbox_emu[1] + tb.bbox_emu[3] / 2
                sh_l, sh_t, sh_w, sh_h = sh.bbox_emu[:4]
                if sh_l <= tb_cx <= sh_l + sh_w and sh_t <= tb_cy <= sh_t + sh_h:
                    return True

        return False

    @staticmethod
    def _is_html_inline_containment(a, b) -> bool:
        """Return True if one element is an HTML inline element contained in a block parent.

        In HTML slides, <strong>, <span>, <em>, <a>, <code> inside
        <li>, <p>, <td>, <div>, <h1>-<h6> create 100% overlap in the
        DOM bounding box model — but this is normal nesting, not a real
        spatial conflict.
        """
        _INLINE_TAGS = frozenset({"strong", "span", "em", "a", "code", "b", "i", "u", "mark", "sub", "sup"})
        _BLOCK_TAGS = frozenset({"li", "p", "td", "th", "div", "h1", "h2", "h3", "h4", "h5", "h6", "section", "header", "footer", "figcaption", "blockquote"})

        a_tag = (a.shape_name or "").split()[-1].lower() if a.shape_name else ""
        b_tag = (b.shape_name or "").split()[-1].lower() if b.shape_name else ""

        # inline inside block
        if a_tag in _INLINE_TAGS and b_tag in _BLOCK_TAGS:
            return True
        if b_tag in _INLINE_TAGS and a_tag in _BLOCK_TAGS:
            return True

        return False

    @staticmethod
    def _is_containment(a, b) -> bool:
        """Return True if one object is largely contained within the other.

        Catches card patterns: header bar (Rectangle) inside card (Rounded Rectangle),
        image (Picture) inside card, table inside card, etc.
        A containment ratio ≥ 85% of the smaller object means intentional nesting.
        """
        if len(a.bbox_emu) < 4 or len(b.bbox_emu) < 4:
            return False

        a_l, a_t, a_w, a_h = a.bbox_emu[:4]
        b_l, b_t, b_w, b_h = b.bbox_emu[:4]

        a_area = a_w * a_h
        b_area = b_w * b_h

        if a_area <= 0 or b_area <= 0:
            return False

        # Determine which is the potential container (larger) and child (smaller)
        if a_area >= b_area:
            container_l, container_t, container_w, container_h = a_l, a_t, a_w, a_h
            child_l, child_t, child_w, child_h = b_l, b_t, b_w, b_h
            child_area = b_area
        else:
            container_l, container_t, container_w, container_h = b_l, b_t, b_w, b_h
            child_l, child_t, child_w, child_h = a_l, a_t, a_w, a_h
            child_area = a_area

        # Compute intersection
        ix_left = max(container_l, child_l)
        iy_top = max(container_t, child_t)
        ix_right = min(container_l + container_w, child_l + child_w)
        iy_bottom = min(container_t + container_h, child_t + child_h)

        if ix_right <= ix_left or iy_bottom <= iy_top:
            return False

        intersection = (ix_right - ix_left) * (iy_bottom - iy_top)
        containment_ratio = intersection / child_area

        return containment_ratio >= SpatialThresholds.CONTAINMENT_RATIO

    @staticmethod
    def _is_title_subtitle_adjacency(a, b) -> bool:
        """Return True if two TextBoxes are vertically adjacent title/subtitle.

        Detects when allocated TextBox heights cause phantom overlap between
        a title and subtitle that are visually separate.  Conditions:
        - Both are TextBoxes
        - Both are in the top 2 inches of the slide
        - Vertical overlap is < 0.3 inch (274320 EMU)
        - Both span a wide portion of the slide (> 6 inches)
        """
        a_is_tb = (getattr(a, 'object_type', '') == "text_box"
                   or "textbox" in a.object_id.lower())
        b_is_tb = (getattr(b, 'object_type', '') == "text_box"
                   or "textbox" in b.object_id.lower())
        if not a_is_tb or not b_is_tb:
            return False
        if len(a.bbox_emu) < 4 or len(b.bbox_emu) < 4:
            return False

        a_l, a_t, a_w, a_h = a.bbox_emu[:4]
        b_l, b_t, b_w, b_h = b.bbox_emu[:4]

        # Both must be in the top portion of the slide (top < 2 inches = 1828800 EMU)
        top_zone = SpatialThresholds.TITLE_TOP_ZONE_EMU
        if a_t > top_zone or b_t > top_zone:
            return False

        # Both must be wide (> 6 inches = 5486400 EMU) — typical for title/subtitle
        wide_threshold = SpatialThresholds.TITLE_WIDE_EMU
        if a_w < wide_threshold or b_w < wide_threshold:
            return False

        # Compute vertical overlap
        upper = a if a_t <= b_t else b
        lower = b if a_t <= b_t else a
        u_bottom = upper.bbox_emu[1] + upper.bbox_emu[3]
        l_top = lower.bbox_emu[1]

        vertical_overlap = u_bottom - l_top
        if vertical_overlap <= 0:
            return False  # No overlap

        # Allow a small amount of title phantom overlap.
        max_phantom = SpatialThresholds.TITLE_PHANTOM_OVERLAP_EMU
        return vertical_overlap <= max_phantom

    def _check_empty_slide(self, ext: SlideExtraction) -> list[Issue]:
        """Check for empty slides."""
        if ext.total_objects == 0 or ext.total_text_length == 0:
            return [Issue(
                issue_id=f"B_geom_slide{ext.slide_id}_empty",
                rubric_id="B2",
                issue_type="empty_slide",
                severity=Severity.MAJOR,
                confidence=Confidence.HIGH,
                affected_slides=[ext.slide_id],
                evidence=IssueEvidence(
                    description=f"Slide {ext.slide_id} has {ext.total_objects} objects "
                               f"and {ext.total_text_length} chars of text",
                ),
                suspected_module="codegen_compiler",
                verdict=Verdict.FAIL,
                why_this_fails="Empty or near-empty slide provides no content value",
                fixability="medium",
                planned_fix=f"Regenerate slide {ext.slide_id} with substantial content. "
                           f"Add at least a title, 4-5 bullet points, and an accent shape.",
            )]
        return []

    def _check_empty_placeholders(self, ext: SlideExtraction) -> list[Issue]:
        """Check for large empty shapes with no text or image content.

        These appear as big blank rectangles on the rendered slide,
        hurting visual quality (MI2.2.2, MI2.2.5, MI2.2.11).
        """
        issues = []
        EMU_PER_INCH = SlideDimensions.EMU_PER_INCH
        MIN_W_IN = 1.5
        MIN_H_IN = 0.5

        for obj in ext.objects:
            # Skip objects that have content
            if obj.text_content and obj.text_content.strip():
                continue
            if obj.has_image:
                continue
            if obj.object_type in ("chart", "table", "picture"):
                continue

            # Check size
            if len(obj.bbox_emu) < 4:
                continue
            w_in = obj.bbox_emu[2] / EMU_PER_INCH
            h_in = obj.bbox_emu[3] / EMU_PER_INCH
            if w_in > MIN_W_IN and h_in > MIN_H_IN:
                issues.append(Issue(
                    issue_id=f"B_geom_slide{ext.slide_id}_empty_placeholder_{obj.object_id}",
                    rubric_id="B2",
                    issue_type="empty_placeholder",
                    severity=Severity.MAJOR,
                    confidence=Confidence.HIGH,
                    affected_slides=[ext.slide_id],
                    evidence=IssueEvidence(
                        description=(
                            f"Slide {ext.slide_id}: shape '{obj.shape_name or obj.object_id}' "
                            f"({w_in:.1f}\"×{h_in:.1f}\") has no text or image content. "
                            f"It renders as a large empty box."
                        ),
                        object_refs=[obj.object_id],
                    ),
                    suspected_module="codegen_compiler",
                    verdict=Verdict.FAIL,
                    why_this_fails="Large empty shapes waste slide space and look unprofessional",
                    fixability="easy",
                    planned_fix=f"Delete the empty shape '{obj.shape_name or obj.object_id}' "
                               f"using delete_shape or remove it from the code.",
                ))
        return issues

    def _check_overlaps(self, ext: SlideExtraction) -> list[Issue]:
        """Check for overlapping objects.

        Only flags overlaps where the intersection area is >10% of the
        smaller object's area, to ignore trivial 1-pixel overlaps between
        adjacent elements (e.g., accent line touching a textbox).

        Also skips intentional design patterns:
        - Background rectangles overlapping content
        - Accent lines near title text
        - Text placed on decorative shapes (cards)
        """
        issues = []
        objects = ext.objects
        for i in range(len(objects)):
            for j in range(i + 1, len(objects)):
                a = objects[i]
                b = objects[j]

                # Skip intentional design patterns
                if self._is_intentional_overlap(a, b):
                    continue

                overlap_pct = self._overlap_percentage(a.bbox_emu, b.bbox_emu)
                if overlap_pct > SpatialThresholds.OVERLAP_MIN_PCT:  # significant overlap
                    severity = Severity.MAJOR if overlap_pct > SpatialThresholds.OVERLAP_MAJOR_PCT else Severity.MINOR

                    # Generate pattern-specific planned_fix for actionable repair
                    planned_fix = self._generate_overlap_fix(a, b, overlap_pct, ext.slide_id)

                    issues.append(Issue(
                        issue_id=f"B3_slide{ext.slide_id}_overlap_{a.object_id}_{b.object_id}",
                        rubric_id="B3",
                        issue_type="overlap",
                        severity=severity,
                        confidence=Confidence.HIGH,
                        affected_slides=[ext.slide_id],
                        evidence=IssueEvidence(
                            object_refs=[a.object_id, b.object_id],
                            description=f"Objects '{a.object_id}' and '{b.object_id}' overlap "
                                       f"by {overlap_pct:.0%} on slide {ext.slide_id}",
                        ),
                        suspected_module="codegen_compiler",
                        verdict=Verdict.FAIL,
                        why_this_fails="Overlapping objects create visual ambiguity",
                        fixability="easy_local_patch",
                        planned_fix=planned_fix,
                    ))
        return issues

    @staticmethod
    def _overlap_percentage(
        bbox_a: list[int], bbox_b: list[int],
    ) -> float:
        """Return overlap as fraction of the smaller object's area.

        bbox format: [left, top, width, height] in EMU.
        Returns 0.0 if no overlap or invalid bbox.
        """
        if len(bbox_a) < 4 or len(bbox_b) < 4:
            return 0.0
        a_l, a_t, a_w, a_h = bbox_a[:4]
        b_l, b_t, b_w, b_h = bbox_b[:4]
        if a_w <= 0 or a_h <= 0 or b_w <= 0 or b_h <= 0:
            return 0.0

        # Intersection rectangle
        ix_left = max(a_l, b_l)
        iy_top = max(a_t, b_t)
        ix_right = min(a_l + a_w, b_l + b_w)
        iy_bottom = min(a_t + a_h, b_t + b_h)

        if ix_right <= ix_left or iy_bottom <= iy_top:
            return 0.0

        intersection = (ix_right - ix_left) * (iy_bottom - iy_top)
        smaller_area = min(a_w * a_h, b_w * b_h)
        if smaller_area <= 0:
            return 0.0
        return intersection / smaller_area

    def _generate_overlap_fix(self, a, b, overlap_pct: float, slide_id: int) -> str:
        """Generate pattern-specific planned_fix text for overlap issues.

        Detects the overlap pattern (accent-through-card, title/subtitle,
        generic) and returns actionable fix instructions for the repair LLM.
        """
        # Pattern A: Accent line cutting through a content shape.
        # The accent line is decorative and should be DELETED.
        a_is_accent = self._is_accent_line(a)
        b_is_accent = self._is_accent_line(b)
        if a_is_accent or b_is_accent:
            accent = a if a_is_accent else b
            other = b if a_is_accent else a
            accent_y_in = (accent.bbox_emu[1] + accent.bbox_emu[3] / 2) / SlideDimensions.EMU_PER_INCH
            return (
                f"DELETE the decorative accent line '{accent.object_id}' — it is a thin "
                f"Rectangle (h<0.15\") at y≈{accent_y_in:.2f}\" that cuts through "
                f"'{other.object_id}'. Remove ALL code lines that create this shape: "
                f"the add_shape() call, fill, and line settings. The accent bar is "
                f"purely decorative and conflicts with content below it."
            )

        # Pattern B: Title/subtitle text overlap.
        # Two TextBoxes with text in the top zone overlapping each other.
        a_is_tb = "textbox" in a.object_id.lower()
        b_is_tb = "textbox" in b.object_id.lower()
        a_has_text = bool(a.text_content and len(a.text_content.strip()) > 3)
        b_has_text = bool(b.text_content and len(b.text_content.strip()) > 3)
        top_zone = SpatialThresholds.TITLE_TOP_ZONE_EMU  # 2 inches in EMU

        if a_is_tb and b_is_tb and a_has_text and b_has_text:
            a_top = a.bbox_emu[1]
            b_top = b.bbox_emu[1]
            both_in_top = a_top < top_zone and b_top < top_zone

            if both_in_top:
                # Determine upper (title) and lower (subtitle)
                if a_top <= b_top:
                    upper, lower = a, b
                else:
                    upper, lower = b, a
                upper_bottom_in = (upper.bbox_emu[1] + upper.bbox_emu[3]) / SlideDimensions.EMU_PER_INCH
                lower_top_in = lower.bbox_emu[1] / SlideDimensions.EMU_PER_INCH
                new_y = upper_bottom_in + 0.05
                return (
                    f"Title/subtitle overlap: '{upper.object_id}' bottom ({upper_bottom_in:.2f}\") "
                    f"overlaps '{lower.object_id}' top ({lower_top_in:.2f}\"). "
                    f"Fix: change '{lower.object_id}' y-position to Inches({new_y:.2f}) "
                    f"(just below the title). If the title TextBox height is excessive, "
                    f"reduce it to fit the actual text content (typically 0.5-0.6\")."
                )

        # Pattern C: Generic overlap — default fix
        return (
            f"Reposition '{a.object_id}' or '{b.object_id}' to eliminate "
            f"{overlap_pct:.0%} overlap. Move one object vertically or "
            f"reduce width to create clear separation."
        )

    def _check_out_of_bounds(self, ext: SlideExtraction) -> list[Issue]:
        """Check for objects extending beyond slide boundaries."""
        issues = []
        for obj in ext.objects:
            if len(obj.bbox_emu) < 4:
                continue
            # Skip background rectangles and accent lines
            if self._is_background_rect(obj) or self._is_accent_line(obj):
                continue

            left, top, width, height = obj.bbox_emu
            right = left + width
            bottom = top + height

            if left < -self.margin or top < -self.margin or \
               right > self.slide_width + self.margin or \
               bottom > self.slide_height + self.margin:
                # Convert to inches for actionable description
                obj_w_in = width / SlideDimensions.EMU_PER_INCH
                obj_h_in = height / SlideDimensions.EMU_PER_INCH
                top_in = top / SlideDimensions.EMU_PER_INCH
                left_in = left / SlideDimensions.EMU_PER_INCH
                slide_w_in = self.slide_width / SlideDimensions.EMU_PER_INCH
                slide_h_in = self.slide_height / SlideDimensions.EMU_PER_INCH
                overflow_bottom = max(0, (bottom - self.slide_height) / SlideDimensions.EMU_PER_INCH)
                overflow_right = max(0, (right - self.slide_width) / SlideDimensions.EMU_PER_INCH)

                desc_parts = [
                    f"Object '{obj.object_id}' ({obj.object_type}) extends beyond slide boundary."
                ]
                if overflow_bottom > SpatialThresholds.OOB_MIN_INCHES:
                    max_h = slide_h_in - top_in - 0.3
                    desc_parts.append(
                        f"Height is {obj_h_in:.1f}\" but max available from Y={top_in:.1f}\" "
                        f"is {max_h:.1f}\". Reduce height to {max_h:.1f}\" "
                        f"(overflow: {overflow_bottom:.1f}\")."
                    )
                    if obj.object_type == "picture":
                        desc_parts.append(
                            f"If this is an image, reduce display width proportionally "
                            f"to cap height at {max_h:.1f}\"."
                        )
                if overflow_right > SpatialThresholds.OOB_MIN_INCHES:
                    desc_parts.append(
                        f"Right edge at {right/SlideDimensions.EMU_PER_INCH:.1f}\" exceeds slide width "
                        f"{slide_w_in:.1f}\" by {overflow_right:.1f}\"."
                    )

                issues.append(Issue(
                    issue_id=f"B3_slide{ext.slide_id}_oob_{obj.object_id}",
                    rubric_id="B3",
                    issue_type="out_of_bounds",
                    severity=Severity.MAJOR,
                    confidence=Confidence.HIGH,
                    affected_slides=[ext.slide_id],
                    evidence=IssueEvidence(
                        object_refs=[obj.object_id],
                        description=" ".join(desc_parts),
                    ),
                    suspected_module="codegen_compiler",
                    verdict=Verdict.FAIL,
                    why_this_fails="Content clipped by slide boundary is unreadable",
                    fixability="easy_local_patch",
                    planned_fix=" ".join(desc_parts[1:]) if len(desc_parts) > 1
                               else f"Reduce size or reposition '{obj.object_id}' to stay within slide bounds (13.333\" x 7.5\").",
                ))
        return issues

    # ── Meta-content leakage check ──────────────────────────────────

    _META_PATTERNS = [
        "[RECURRING]", "[TODO]", "[FIX]", "[NOTE]", "[EDIT]",
        "Note to editor", "Restore or add",
        "[PLACEHOLDER]", "[INSERT", "[REPLACE",
        "Revise the setup", "Revise the ",
        "Add a slide that", "Add opening slides",
    ]

    def _check_meta_content(self, ext: SlideExtraction) -> list[Issue]:
        """Flag text boxes containing meta-instructions or editorial notes."""
        issues = []
        for obj in ext.objects:
            if obj.object_type not in ("text_box", "shape"):
                continue
            if not obj.text_content:
                continue
            text = obj.text_content
            for pattern in self._META_PATTERNS:
                if pattern.lower() in text.lower():
                    issues.append(Issue(
                        issue_id=f"A7_slide{ext.slide_id}_meta_{obj.object_id}",
                        rubric_id="A7",
                        issue_type="content_anomaly",
                        severity=Severity.CRITICAL,
                        confidence=Confidence.HIGH,
                        affected_slides=[ext.slide_id],
                        evidence=IssueEvidence(
                            description=(
                                f"Text in '{obj.shape_name}' contains meta-instruction "
                                f"or editorial note: '{pattern}'. This must be removed — "
                                f"only presentation-ready content should appear on slides."
                            ),
                            source_refs=[],
                        ),
                        status=IssueStatus.OPEN,
                        verdict=Verdict.FAIL,
                    ))
                    break  # one issue per object is enough
        return issues

    def _check_spelling(self, ext: SlideExtraction) -> list[Issue]:
        """Flag common spelling errors in slide text."""
        import re
        KNOWN_TYPOS = {
            "acheive": "achieve", "acheived": "achieved", "acheives": "achieves",
            "accomodate": "accommodate", "achivement": "achievement",
            "algorythm": "algorithm", "anomoly": "anomaly",
            "architechture": "architecture", "artifical": "artificial",
            "assesment": "assessment", "auxilary": "auxiliary", "auxillary": "auxiliary",
            "benchamrk": "benchmark", "catagory": "category", "comparision": "comparison",
            "concensus": "consensus", "consistant": "consistent",
            "dependant": "dependent", "deterministc": "deterministic",
            "efficency": "efficiency", "efficent": "efficient",
            "enviroment": "environment", "equivilant": "equivalent",
            "evalution": "evaluation", "experimetal": "experimental",
            "explaination": "explanation", "guarentee": "guarantee",
            "heirarchy": "hierarchy", "hypotheisis": "hypothesis",
            "implemention": "implementation", "improvment": "improvement",
            "independant": "independent", "infomation": "information",
            "initalize": "initialize", "knowlege": "knowledge",
            "langauge": "language", "likelyhood": "likelihood",
            "maintainance": "maintenance", "mechnism": "mechanism",
            "neccessary": "necessary", "occured": "occurred", "occurence": "occurrence",
            "optimze": "optimize", "paramater": "parameter", "parallell": "parallel",
            "performace": "performance", "persistant": "persistent",
            "preformance": "performance", "propogation": "propagation",
            "reccomend": "recommend", "relavent": "relevant",
            "represention": "representation", "seperate": "separate",
            "signficant": "significant", "similiar": "similar",
            "straegy": "strategy", "sucess": "success",
            "techique": "technique", "threshhold": "threshold",
            "transfered": "transferred", "trasformer": "transformer",
            "vulnerablity": "vulnerability",
        }
        issues = []
        for obj in ext.objects:
            if not obj.text_content:
                continue
            words = re.findall(r'\b[a-zA-Z]{4,}\b', obj.text_content.lower())
            found_typos = []
            for word in words:
                if word in KNOWN_TYPOS:
                    found_typos.append((word, KNOWN_TYPOS[word]))
            if found_typos:
                typo_list = ", ".join(f'"{t}" → "{c}"' for t, c in found_typos[:5])
                issues.append(Issue(
                    issue_id=f"A_spell_slide{ext.slide_id}_{found_typos[0][0]}",
                    rubric_id="A",
                    issue_type="spelling_error",
                    severity=Severity.MINOR,
                    confidence=Confidence.HIGH,
                    affected_slides=[ext.slide_id],
                    evidence=IssueEvidence(
                        description=(
                            f"Slide {ext.slide_id}: spelling error(s): {typo_list}. "
                            f"Fix the misspelled word(s)."
                        ),
                        source_refs=[],
                    ),
                    status=IssueStatus.OPEN,
                    verdict=Verdict.FAIL,
                ))
        return issues

    def _check_non_slide_content(self, ext: SlideExtraction) -> list[Issue]:
        """Flag text that looks like speaker notes, placeholders, or boilerplate.

        Note: meta-instructions like [TODO], [FIX] are already caught by
        _check_meta_content. This method focuses on different patterns.
        """
        import re
        NON_SLIDE_PATTERNS = [
            r'click to (?:edit|add)',
            r'speaker notes?:',
            r'note to (?:editor|self)',
            r'insert (?:image|chart|diagram) here',
            r'lorem ipsum',
        ]
        combined = re.compile('|'.join(NON_SLIDE_PATTERNS), re.IGNORECASE)
        issues = []
        for obj in ext.objects:
            if not obj.text_content:
                continue
            if combined.search(obj.text_content):
                match = combined.search(obj.text_content).group()
                issues.append(Issue(
                    issue_id=f"A_meta_slide{ext.slide_id}_{match[:20]}",
                    rubric_id="A",
                    issue_type="non_slide_content",
                    severity=Severity.MAJOR,
                    confidence=Confidence.HIGH,
                    affected_slides=[ext.slide_id],
                    evidence=IssueEvidence(
                        description=(
                            f"Slide {ext.slide_id}: contains non-slide content: "
                            f'"{match}". Remove or replace with actual presentation content.'
                        ),
                        source_refs=[],
                    ),
                    status=IssueStatus.OPEN,
                    verdict=Verdict.FAIL,
                ))
                break  # One issue per slide is enough
        return issues

    def _check_bullet_count(self, ext: SlideExtraction) -> list[Issue]:
        """Flag slides with more than 6 bullet-like items (judges always penalize)."""
        import re
        bullet_count = 0
        for obj in ext.objects:
            if not obj.text_content:
                continue
            text = obj.text_content.strip()
            # Count list items and bullet-prefixed lines
            tag = (obj.shape_type or "").lower()
            if tag in ("li", "listitem"):
                bullet_count += 1
            elif text.startswith(("•", "–", "-", "▸", "●")):
                bullet_count += 1
            elif re.match(r'^\d+[\.\)]\s', text):
                bullet_count += 1

        if bullet_count > 8:
            return [Issue(
                issue_id=f"A_bullets_slide{ext.slide_id}",
                rubric_id="A",
                issue_type="too_many_bullets",
                severity=Severity.MINOR,
                confidence=Confidence.HIGH,
                affected_slides=[ext.slide_id],
                evidence=IssueEvidence(
                    description=(
                        f"Slide has {bullet_count} bullet points (max 8 allowed). "
                        f"Remove {bullet_count - 8} bullet(s) by merging or deleting "
                        f"the least important items. For multi-column layouts, "
                        f"use max 2 items per column in 3-column, max 3 per column in 2-column."
                    ),
                ),
                verdict=Verdict.FAIL,
            )]
        return []
