"""VisualJudge - evaluates B-series visual rubric items."""

import json
import logging
from pathlib import Path

from ...schemas.extraction import SlideExtraction
from ...schemas.issue import Issue
from ...utils.image_ops import image_to_base64
from .base_judge import BaseJudge

logger = logging.getLogger(__name__)


def _format_spatial_signal(state) -> dict:
    """Extract key signals from SlideState for LLM context.

    Converts Playwright/GeomChecks spatial measurements into a compact
    dict that the VisualJudge LLM can use as objective evidence.
    """
    sig: dict = {}
    if state.overlap_pairs:
        sig["overlap_pairs"] = [
            {"a": a, "b": b, "area_sq_in": round(area, 2)}
            for a, b, area in state.overlap_pairs
        ]
    if state.overflow_blocks:
        overflow_info = []
        for blk_id in state.overflow_blocks:
            blk = next((b for b in state.blocks if b.block_id == blk_id), None)
            if blk:
                overflow_info.append({
                    "block_id": blk_id,
                    "overflow_bottom_px": blk.overflow_bottom_px,
                    "overflow_right_px": blk.overflow_right_px,
                    "scroll_h_px": blk.scroll_h_px,
                    "client_h_px": blk.client_h_px,
                })
            else:
                overflow_info.append({"block_id": blk_id})
        sig["overflow_blocks"] = overflow_info
    if state.oob_blocks:
        sig["oob_blocks"] = list(state.oob_blocks)
    if state.low_contrast_blocks:
        contrast_info = []
        for blk_id in state.low_contrast_blocks:
            blk = next((b for b in state.blocks if b.block_id == blk_id), None)
            if blk:
                contrast_info.append({
                    "block_id": blk_id,
                    "contrast_ratio": round(blk.contrast_ratio, 1),
                    "fg": blk.fg_color,
                    "bg": blk.bg_color,
                })
        sig["low_contrast"] = contrast_info
    if state.clipped_blocks:
        sig["clipped_blocks"] = list(state.clipped_blocks)
    return sig


class VisualJudge(BaseJudge):
    """Evaluates visual design: B1, B2, B5-B9."""

    rubric_family = "B_visual"
    module_name = "visual_judge"
    prompt_filename = "visual_judge.system.md"

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        png_paths: list[str],
        scope_slides: list[int] | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
        spatial_signals: dict | None = None,
    ) -> list[Issue]:
        """Evaluate visual quality using rendered slide images."""
        if scope_slides is None:
            scope_slides = [ext.slide_id for ext in extractions]

        # Build text context with spatial signals for quantitative judgment
        slide_info = []
        for ext in extractions:
            if ext.slide_id in scope_slides:
                # Compute spatial signals from extraction objects
                total_words = 0
                min_font = 999
                max_font = 0
                has_image = False
                for obj in ext.objects:
                    if obj.has_image:
                        has_image = True
                    if obj.text_content:
                        words = len(obj.text_content.split())
                        total_words += words
                    if obj.font_sizes_pt:
                        for fs in obj.font_sizes_pt:
                            if fs > 0:
                                min_font = min(min_font, fs)
                                max_font = max(max_font, fs)

                info = {
                    "slide_id": ext.slide_id,
                    "title": ext.title,
                    "object_count": ext.total_objects,
                    "text_length": ext.total_text_length,
                    "total_words": total_words,
                    "has_image": has_image,
                }
                if min_font < 999:
                    info["min_font_pt"] = round(min_font, 1)
                    info["max_font_pt"] = round(max_font, 1)
                # Flag only extremely sparse slides so judge has quantitative basis
                if total_words < 15 and not has_image:
                    info["WARNING"] = f"Only {total_words} words — likely over-condensed or placeholder"
                elif total_words < 30 and not has_image:
                    info["NOTE"] = f"Low word count ({total_words}) — verify slide has adequate content"
                slide_info.append(info)

        # Build spatial signals context for scoped slides
        spatial_context = {}
        if spatial_signals:
            for sid in scope_slides:
                state = spatial_signals.get(sid)
                if state:
                    spatial_context[sid] = _format_spatial_signal(state)

        user_data = {
            "scope_slides": scope_slides,
            "slide_info": slide_info,
        }
        if spatial_context:
            user_data["spatial_signals"] = spatial_context

        user_text = json.dumps(user_data, indent=2, ensure_ascii=False)

        # Append previous issues context for differential evaluation
        # NOTE: Previous issues are handled separately in _triage_previous_issues
        # (Call 1). The main evaluate call (Call 2) runs WITHOUT previous issues
        # to avoid format confusion that caused verdict drops.

        # Encode slide images
        # Map PNG paths to slide IDs via extractions (not index+1, since
        # slide_ids may not be contiguous when differential eval is active)
        image_urls = []
        encoded_slide_ids: list[int] = []  # tracks which slides actually got encoded
        for ext_idx, png_path in enumerate(png_paths):
            slide_num = (
                extractions[ext_idx].slide_id
                if ext_idx < len(extractions)
                else ext_idx + 1
            )
            if slide_num in scope_slides and Path(png_path).exists():
                try:
                    b64 = image_to_base64(png_path, max_size=1920)
                    image_urls.append(b64)
                    encoded_slide_ids.append(slide_num)
                except Exception as e:
                    logger.warning("Failed to encode slide %d image: %s", slide_num, e)

        model = self.config.models.get_model(self.module_name)

        # Batch slides to avoid attention dilution in VLM when many images
        BATCH_SIZE = 3
        all_issues: list[Issue] = []

        # --- STEP 1: Triage previous issues (batched per slide group) ---
        triaged_issues: list[Issue] = []
        if previous_issues:
            if len(scope_slides) <= BATCH_SIZE:
                triaged_issues = self._triage_previous_issues(
                    previous_issues, scope_slides, user_text, model,
                    turn_index, image_urls=image_urls if image_urls else None,
                )
            else:
                # Batch triage to match fresh-judge batching
                # Use encoded_slide_ids (aligned with image_urls) for batching
                for batch_start in range(0, len(encoded_slide_ids), BATCH_SIZE):
                    batch_slide_ids = encoded_slide_ids[batch_start:batch_start + BATCH_SIZE]
                    batch_imgs = image_urls[batch_start:batch_start + BATCH_SIZE] if image_urls else None
                    batch_info = [si for si in slide_info if si["slide_id"] in batch_slide_ids]
                    batch_data = {
                        "scope_slides": batch_slide_ids,
                        "slide_info": batch_info,
                    }
                    if spatial_context:
                        batch_spatial = {sid: spatial_context[sid] for sid in batch_slide_ids if sid in spatial_context}
                        if batch_spatial:
                            batch_data["spatial_signals"] = batch_spatial
                    batch_user_text = json.dumps(batch_data, indent=2, ensure_ascii=False)
                    batch_triaged = self._triage_previous_issues(
                        previous_issues, batch_slide_ids, batch_user_text, model,
                        turn_index, image_urls=batch_imgs,
                    )
                    triaged_issues.extend(batch_triaged)
                # Dedup cross-batch: an issue affecting slides in multiple
                # batches can be triaged twice. Keep the first occurrence.
                seen_ids: set[str] = set()
                deduped: list[Issue] = []
                for iss in triaged_issues:
                    if iss.issue_id not in seen_ids:
                        seen_ids.add(iss.issue_id)
                        deduped.append(iss)
                triaged_issues = deduped

        # --- STEP 2: Fresh judge — with persistent issue awareness ---
        # Inject known persistent issues so LLM avoids re-reporting them
        step2_user_text = user_text
        if triaged_issues:
            persistent_ctx = self._format_persistent_context(triaged_issues)
            if persistent_ctx:
                step2_user_text = user_text + persistent_ctx

        if image_urls:
            if len(image_urls) <= BATCH_SIZE:
                # Small batch — send all at once
                raw = self.llm.call_vision(
                    system_prompt=self.system_prompt,
                    text_content=step2_user_text,
                    image_urls=image_urls,
                    model=model,
                    module_name=self.module_name,
                    prompt_version="visual_judge.system.v1",
                    max_tokens=4096,
                )
                all_issues = self._parse_issues(raw, scope_slides, previous_issues=None, turn_index=turn_index)
            else:
                # Split into batches for better per-slide attention
                for batch_start in range(0, len(image_urls), BATCH_SIZE):
                    batch_imgs = image_urls[batch_start:batch_start + BATCH_SIZE]
                    # Use encoded_slide_ids (aligned with image_urls) not scope_slides
                    batch_slide_ids = encoded_slide_ids[batch_start:batch_start + BATCH_SIZE]
                    # Filter slide_info for this batch
                    batch_info = [si for si in slide_info if si["slide_id"] in batch_slide_ids]
                    batch_data = {
                        "scope_slides": batch_slide_ids,
                        "slide_info": batch_info,
                    }
                    if spatial_context:
                        batch_spatial = {sid: spatial_context[sid] for sid in batch_slide_ids if sid in spatial_context}
                        if batch_spatial:
                            batch_data["spatial_signals"] = batch_spatial
                    batch_user_text = json.dumps(batch_data, indent=2, ensure_ascii=False)
                    # Inject persistent context into batch
                    if triaged_issues:
                        persistent_ctx = self._format_persistent_context(triaged_issues)
                        if persistent_ctx:
                            batch_user_text += persistent_ctx

                    logger.info("Visual judge batch: slides %s (%d images)", batch_slide_ids, len(batch_imgs))
                    raw = self.llm.call_vision(
                        system_prompt=self.system_prompt,
                        text_content=batch_user_text,
                        image_urls=batch_imgs,
                        model=model,
                        module_name=self.module_name,
                        prompt_version="visual_judge.system.v1",
                        max_tokens=4096,
                    )
                    batch_issues = self._parse_issues(raw, batch_slide_ids, previous_issues=None, turn_index=turn_index)
                    all_issues.extend(batch_issues)
        else:
            # Fallback to text-only if no images
            raw = self.llm.call_text(
                system_prompt=self.system_prompt,
                user_content=step2_user_text + "\n\n[No slide images available for visual inspection]",
                model=model,
                module_name=self.module_name,
                prompt_version="visual_judge.system.v1",
                max_tokens=4096,
            )
            all_issues = self._parse_issues(raw, scope_slides, previous_issues=None, turn_index=turn_index)

        # --- STEP 3: Dedup new issues against triaged previous issues ---
        if triaged_issues:
            all_issues = self._dedup_new_against_triaged(all_issues, triaged_issues)

        return triaged_issues + all_issues
