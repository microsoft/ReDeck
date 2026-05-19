"""EvalRouter - routes evaluation tasks to appropriate judges."""

import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..llm_client import LLMClient
from ..schemas.blueprint import DeckBlueprint
from ..schemas.common import EvalSplitLevel, IssueStatus
from ..schemas.evidence import EvidenceState
from ..schemas.experiment_config import ExperimentConfig
from ..schemas.extraction import SlideExtraction
from ..schemas.issue import Issue
from ..schemas.issue_types import (
    B_SERIES_TYPES,
    DEDUP_PAIRS,
    ISSUE_TYPE_TO_FAMILY,
)
from ..modules.evaluators.narrative_judge import NarrativeJudge
from ..modules.evaluators.visual_judge import VisualJudge
from ..modules.evaluators.completeness_judge import CompletenessJudge
from ..modules.evaluators.correctness_judge import CorrectnessJudge
from ..modules.evaluators.fidelity_judge import FidelityJudge
from ..modules.evaluators.evaluator_agent import EvaluatorAgent
from ..modules.evaluators.geom_checks import DeterministicGeomChecks

logger = logging.getLogger(__name__)

# Terminal statuses — issues in these states should not be carried forward
_RESOLVED_STATUSES = frozenset({
    IssueStatus.RESOLVED, IssueStatus.WONT_FIX, IssueStatus.DEFERRED,
})


class EvalRouter:
    """Routes evaluation to appropriate judges based on config."""

    def __init__(self, llm: LLMClient, config: ExperimentConfig):
        self.llm = llm
        self.config = config
        self.split_level = config.eval_mode.split_level
        self.use_judge_agent = config.eval_mode.use_judge_agent

        # Initialize LLM judges
        self.narrative_judge = NarrativeJudge(llm, config)
        self.visual_judge = VisualJudge(llm, config)
        self.completeness_judge = CompletenessJudge(llm, config)
        self.correctness_judge = CorrectnessJudge(llm, config)
        self.fidelity_judge = FidelityJudge(llm, config)

        # Wrap C/D/E judges with agent loop if enabled
        if self.use_judge_agent:
            self.completeness_agent = EvaluatorAgent(
                self.completeness_judge, llm, config
            )
            self.correctness_agent = EvaluatorAgent(
                self.correctness_judge, llm, config
            )
            self.fidelity_agent = EvaluatorAgent(
                self.fidelity_judge, llm, config
            )
            logger.info(
                "EvalRouter: C/D/E judges wrapped with EvaluatorAgent "
                "(use_judge_agent=True)"
            )

        # Probe planner agent (adaptive evaluation for turn > 0)
        if config.eval_mode.use_probe_planner:
            from ..modules.evaluators.probe_planner_agent import ProbePlannerAgent
            self.probe_planner = ProbePlannerAgent(self, llm, config)
            logger.info("EvalRouter: ProbePlannerAgent enabled for adaptive probe scheduling")

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        png_paths: list[str],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        modified_slides: set[int] | None = None,
        turn_index: int = 0,
        slide_codes: dict[int, str] | None = None,
        run_dir: str | None = None,
        source_store=None,
        content_modified_slides: set[int] | None = None,
    ) -> list[Issue]:
        """Run evaluation pipeline and return all issues.

        When previous_issues and modified_slides are provided (turn > 0),
        uses differential evaluation: only re-evaluates modified slides
        and carries forward issues on unmodified slides. Each judge receives
        the previous issues on its slides so it can triage them (RESOLVED /
        PERSISTED / WORSENED) alongside reporting genuinely new issues.
        """
        all_issues: list[Issue] = []

        if not self.config.eval_mode.enabled:
            return all_issues

        # === COLLECT SPATIAL SIGNALS (Playwright) ===
        # These are injected as context into VisualJudge, not as issues.
        spatial_signals: dict = {}
        if slide_codes and getattr(self.config, 'use_html_codegen', False):
            try:
                spatial_signals = self._collect_spatial_signals(
                    slide_codes, extractions, modified_slides,
                )
            except Exception as e:
                logger.warning("Spatial signal collection failed: %s", e)

        # Load repair summaries from previous turn (if available)
        repair_summaries: dict[int, dict] | None = None
        if run_dir and turn_index > 0:
            repair_summaries = self._load_repair_summaries(
                run_dir, turn_index - 1,
            )
            if repair_summaries:
                logger.info(
                    "Loaded repair summaries for %d slides from turn %d",
                    len(repair_summaries), turn_index - 1,
                )

        # Set repair summaries on all judges for triage context
        for judge in [self.narrative_judge, self.visual_judge,
                      self.completeness_judge, self.correctness_judge,
                      self.fidelity_judge]:
            judge._repair_summaries = repair_summaries
            judge._source_store = source_store
            judge._slide_codes = slide_codes

        # === DIFFERENTIAL EVALUATION (turn > 0) ===
        if previous_issues and modified_slides is not None:
            # All previous issues go to LLM judges for triage.
            # Spatial signals (GeomChecks/Playwright) are injected as
            # VisualJudge input context, not as separate issue sources.

            # For FAMILY_PLUS_SLIDE mode, deck-level judges (A, C) receive
            # ALL slides and produce fresh issues covering the entire deck.
            # Only per-slide judges (B, D, E) are scoped to modified slides,
            # so we only carry forward B/D/E issues on unmodified slides.
            # For other modes, carry all issues on unmodified slides.
            #
            # STALENESS LIMIT: Don't carry forward issues that have been
            # untouched for 3+ consecutive turns. These are likely false
            # positives that will never be on a modified slide, so they'd
            # persist forever without re-evaluation.
            MAX_CARRY_TURNS = 3
            deck_level_families = {"A", "C"}
            if self.split_level == EvalSplitLevel.FAMILY_PLUS_SLIDE:
                carried_issues = [
                    issue for issue in previous_issues
                    if (
                        not any(s in modified_slides for s in (issue.affected_slides or []))
                        and (issue.rubric_id or "")[0:1] not in deck_level_families
                        and issue.status not in _RESOLVED_STATUSES
                    )
                ]
            else:
                carried_issues = [
                    issue for issue in previous_issues
                    if (
                        not any(s in modified_slides for s in (issue.affected_slides or []))
                        and issue.status not in _RESOLVED_STATUSES
                    )
                ]

            # Apply staleness limit: drop issues carried for too many turns
            if turn_index >= MAX_CARRY_TURNS:
                before = len(carried_issues)
                carried_issues = [
                    iss for iss in carried_issues
                    if not self._is_stale_carried_issue(iss, turn_index, MAX_CARRY_TURNS)
                ]
                dropped = before - len(carried_issues)
                if dropped:
                    logger.info(
                        "Dropped %d stale carried issues (untouched for %d+ turns)",
                        dropped, MAX_CARRY_TURNS,
                    )
            logger.info(
                "Differential eval: %d modified slides, carrying %d issues from %d unmodified slides",
                len(modified_slides), len(carried_issues),
                len(set(range(1, len(extractions) + 1)) - modified_slides),
            )

            # 2. Only evaluate MODIFIED slides
            modified_extractions = [
                ext for ext in extractions
                if ext.slide_id in modified_slides
            ]
            # Build slide_id → png_path mapping for correct filtering
            # (slide_ids may not be contiguous: 1,3,5,... so index != slide_id)
            slide_id_to_png = {}
            if png_paths:
                for ext, png in zip(extractions, png_paths):
                    slide_id_to_png[ext.slide_id] = png
            modified_pngs = [
                slide_id_to_png[ext.slide_id]
                for ext in modified_extractions
                if ext.slide_id in slide_id_to_png
            ] if png_paths else []

            # 3. Filter previous issues to only those on modified slides
            prev_issues_for_modified = [
                issue for issue in previous_issues
                if any(s in modified_slides for s in (issue.affected_slides or []))
            ]

            # Run evaluation on modified slides.
            # IMPORTANT: deck-level judges (Narrative A, Completeness C) need
            # ALL slides to correctly assess deck-wide properties like slide
            # count, section coverage, and narrative flow. Only per-slide
            # judges (Visual B, Correctness D, Fidelity E) should be scoped
            # to modified slides. We achieve this by passing full extractions
            # to _eval_by_family (the judges that need scoping already handle
            # it internally via scope_slides), but tagging which slides are
            # modified so visual/correctness/fidelity judges can scope.
            if modified_extractions:
                if self.split_level == EvalSplitLevel.MONOLITHIC:
                    all_issues.extend(self._eval_monolithic(
                        modified_extractions, modified_pngs, task_brief, source_summary,
                        blueprint, evidence,
                        previous_issues=prev_issues_for_modified,
                        turn_index=turn_index,
                    ))
                elif self.split_level == EvalSplitLevel.FAMILY:
                    all_issues.extend(self._eval_by_family(
                        extractions, png_paths, task_brief, source_summary,
                        blueprint, evidence,
                        previous_issues=previous_issues,
                        turn_index=turn_index,
                        modified_slides=modified_slides,
                    ))
                elif self.split_level == EvalSplitLevel.FAMILY_PLUS_SLIDE:
                    all_issues.extend(self._eval_family_plus_slide(
                        extractions, png_paths, task_brief, source_summary,
                        blueprint, evidence,
                        previous_issues=previous_issues,
                        turn_index=turn_index,
                        modified_slides=modified_slides,
                        content_modified_slides=content_modified_slides,
                        spatial_signals=spatial_signals,
                    ))

            # Combine: carried issues + new issues on modified slides
            all_issues.extend(carried_issues)
            logger.info(
                "Differential eval result: %d new issues on modified slides + %d carried = %d total",
                len(all_issues) - len(carried_issues), len(carried_issues), len(all_issues),
            )
        else:
            # === FULL EVALUATION (turn 0) ===
            if self.split_level == EvalSplitLevel.MONOLITHIC:
                all_issues.extend(self._eval_monolithic(
                    extractions, png_paths, task_brief, source_summary,
                    blueprint, evidence,
                ))
            elif self.split_level == EvalSplitLevel.FAMILY:
                all_issues.extend(self._eval_by_family(
                    extractions, png_paths, task_brief, source_summary,
                    blueprint, evidence,
                ))
            elif self.split_level == EvalSplitLevel.FAMILY_PLUS_SLIDE:
                all_issues.extend(self._eval_family_plus_slide(
                    extractions, png_paths, task_brief, source_summary,
                    blueprint, evidence,
                    spatial_signals=spatial_signals,
                ))

        logger.info("Total issues after LLM evaluation: %d", len(all_issues))

        # === DETERMINISTIC GEOMETRY CHECKS (non-B-family only) ===
        # GeomChecks for spelling, non_slide_content, meta_content, empty_slide,
        # empty_placeholder — these are A-family deterministic checks that
        # continue to generate issues independently.
        # B-family spatial checks: deterministic detections (overlap, OOB, etc.)
        # are pixel-precise and should be included directly as issues.
        # They are ALSO injected as context into VisualJudge via spatial_signals,
        # but the VisualJudge may miss them — so we keep both sources and dedup.
        try:
            geom_checker = DeterministicGeomChecks(
                html_mode=getattr(self.config, 'use_html_codegen', False),
            )
            target_exts = extractions
            if previous_issues and modified_slides is not None:
                target_exts = [e for e in extractions if e.slide_id in modified_slides]
            geom_issues = geom_checker.check_all(target_exts)
            existing_keys = {
                (iss.issue_type, tuple(iss.affected_slides or []))
                for iss in all_issues
            }
            added = 0
            for gi in geom_issues:
                key = (gi.issue_type, tuple(gi.affected_slides or []))
                if key not in existing_keys:
                    all_issues.append(gi)
                    existing_keys.add(key)
                    added += 1
            if added:
                logger.info("GeomChecks added %d issues (including B-family spatial)", added)
        except Exception as e:
            logger.warning("GeomChecks failed: %s", e)

        # Post-process: cap B-series per slide, dedup, severity recalibrate
        all_issues = self._post_process_issues(
            all_issues, blueprint=blueprint, extractions=extractions,
        )
        logger.info("After post-processing: %d issues", len(all_issues))

        return all_issues

    # ================================================================
    # SPATIAL SIGNAL COLLECTION (for VisualJudge context)
    # ================================================================

    def _collect_spatial_signals(
        self,
        slide_codes: dict[int, str],
        extractions: list[SlideExtraction],
        modified_slides: set[int] | None,
    ) -> dict:
        """Collect spatial signals from Playwright for VisualJudge context.

        Returns dict mapping slide_id → SlideState with precise DOM
        measurements (overlap, overflow, OOB, contrast). These are
        injected into the VisualJudge prompt as objective evidence,
        NOT as independent issues.
        """
        from ..modules.redeck.html_spatial_state import extract_html_slide_state

        target_ids = set(slide_codes.keys())
        if modified_slides is not None:
            target_ids = target_ids & modified_slides

        signals = {}
        for sid in sorted(target_ids):
            code = slide_codes.get(sid)
            if not code:
                continue
            if "<!DOCTYPE" not in code and "<html" not in code:
                continue
            try:
                state = extract_html_slide_state(sid, code)
                signals[sid] = state
            except Exception as e:
                logger.warning("Playwright extraction failed for slide %d: %s", sid, e)
                continue

        logger.info(
            "Collected spatial signals for %d slides", len(signals),
        )
        return signals

    # ================================================================
    # REPAIR SUMMARY LOADING
    # ================================================================

    @staticmethod
    def _load_repair_summaries(
        run_dir: str, turn_index: int,
    ) -> dict[int, dict] | None:
        """Load repair summaries generated by repair agent.

        Returns dict mapping slide_id → summary dict, or None if no
        summaries found.
        """
        summary_dir = Path(run_dir) / f"turn_{turn_index:02d}" / "repair_summaries"
        if not summary_dir.exists():
            return None
        summaries = {}
        for path in summary_dir.glob("slide_*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                sid = data.get("slide_id")
                if sid is not None:
                    summaries[sid] = data
            except Exception:
                continue
        return summaries if summaries else None

    # ================================================================
    # POST-PROCESSING
    # ================================================================

    def _post_process_issues(
        self, issues: list[Issue],
        blueprint: DeckBlueprint | None = None,
        extractions: list[SlideExtraction] | None = None,
    ) -> list[Issue]:
        """Post-process issues: C1 dedup, cross-family dedup, structural filter.

        RESOLVED issues now go through dedup filters like everything else.
        They should not get special bypass — a false RESOLVED verdict that
        duplicates a real issue should still be caught by dedup.
        """
        if not issues:
            return issues

        initial_count = len(issues)

        # ── Step 1: C1 missing_section dedup ──
        # Keep at most 1 C1 (missing_section) issue per deck.
        result = self._dedup_missing_section(issues)

        # ── Step 2: Cross-family dedup (E2+D1, E2+D2 same root cause) ──
        result = self._dedup_cross_family(result)

        # ── Step 2b: Suppress B9 underutilized_space on word-dense slides ──
        result = self._filter_density_on_dense_slides(result, extractions)

        # ── Step 3: Exempt title/divider slides from B9 density_imbalance ──
        result = self._filter_density_on_structural_slides(result, blueprint)

        logger.info(
            "Post-processing complete: %d → %d issues",
            initial_count, len(result),
        )

        return result

    @staticmethod
    def _dedup_missing_section(issues: list[Issue]) -> list[Issue]:
        """Keep at most one C1 (missing_section) issue per deck.

        If multiple C1 issues exist, keep the highest-severity one and
        drop the rest.  On tie, keep the first encountered.
        """
        _SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}
        c1_indices: list[int] = [
            i for i, iss in enumerate(issues)
            if getattr(iss, "rubric_id", "") == "C1"
            or getattr(iss, "issue_type", "") == "missing_section"
        ]
        if len(c1_indices) <= 1:
            return issues
        # Pick the best one
        best_idx = min(
            c1_indices,
            key=lambda i: _SEV_ORDER.get(
                getattr(issues[i], "severity", "minor"), 2
            ),
        )
        drop = set(c1_indices) - {best_idx}
        return [iss for i, iss in enumerate(issues) if i not in drop]

    @staticmethod
    def _dedup_cross_family(issues: list[Issue]) -> list[Issue]:
        """Deduplicate issues where D and E judges flag the same content.

        Common pattern: E2 (fabricated) + D2 (numeric_error) + D1 (incorrect_claim)
        all targeting the same slide with the same root cause (e.g., same table
        numbers flagged as both fabricated and incorrect). Also deduplicates
        A4 (title_content_mismatch) + B4 (text_overflow) on the same slide.

        Strategy: group issues by slide, detect overlapping description content,
        keep the highest-severity one.
        """
        if len(issues) <= 1:
            return issues

        # Define cross-family dedup groups — imported from registry
        _SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}

        # Group issues by affected slides (as frozenset for hashability)
        from collections import defaultdict
        by_slides: dict[frozenset[int], list[tuple[int, Issue]]] = defaultdict(list)
        for i, iss in enumerate(issues):
            key = frozenset(iss.affected_slides or [])
            by_slides[key].append((i, iss))

        drop_indices: set[int] = set()
        for slide_key, group in by_slides.items():
            if len(group) < 2:
                continue

            # Check each pair in the group
            for a_idx in range(len(group)):
                for b_idx in range(a_idx + 1, len(group)):
                    i_a, iss_a = group[a_idx]
                    i_b, iss_b = group[b_idx]

                    if i_a in drop_indices or i_b in drop_indices:
                        continue

                    pair = frozenset({iss_a.issue_type, iss_b.issue_type})
                    if pair not in DEDUP_PAIRS:
                        continue

                    # For density+spatial pairs, always drop density
                    # (density is a symptom of the spatial issue)
                    _DENSITY_TYPE = "density_imbalance"
                    _SPATIAL_TYPES = {"overlap", "text_overflow", "out_of_bounds"}
                    if pair & {_DENSITY_TYPE} and pair & _SPATIAL_TYPES:
                        if iss_a.issue_type == _DENSITY_TYPE:
                            drop_indices.add(i_a)
                        else:
                            drop_indices.add(i_b)
                        dropped_iss = iss_a if iss_a.issue_type == _DENSITY_TYPE else iss_b
                        kept_iss = iss_b if iss_a.issue_type == _DENSITY_TYPE else iss_a
                        logger.info(
                            "Cross-family dedup: dropping %s [%s] (symptom of %s [%s]) on slides %s",
                            dropped_iss.issue_id, dropped_iss.issue_type,
                            kept_iss.issue_id, kept_iss.issue_type,
                            list(slide_key),
                        )
                        continue

                    # Keep the higher-severity one (lower _SEV_ORDER value)
                    sev_a = _SEV_ORDER.get(iss_a.severity.value if hasattr(iss_a.severity, 'value') else str(iss_a.severity), 2)
                    sev_b = _SEV_ORDER.get(iss_b.severity.value if hasattr(iss_b.severity, 'value') else str(iss_b.severity), 2)

                    if sev_a <= sev_b:
                        drop_indices.add(i_b)
                        logger.info(
                            "Cross-family dedup: dropping %s [%s] (dup of %s [%s]) on slides %s",
                            iss_b.issue_id, iss_b.issue_type,
                            iss_a.issue_id, iss_a.issue_type,
                            list(slide_key),
                        )
                    else:
                        drop_indices.add(i_a)
                        logger.info(
                            "Cross-family dedup: dropping %s [%s] (dup of %s [%s]) on slides %s",
                            iss_a.issue_id, iss_a.issue_type,
                            iss_b.issue_id, iss_b.issue_type,
                            list(slide_key),
                        )

        if drop_indices:
            logger.info("Cross-family dedup removed %d duplicate issues", len(drop_indices))
        return [iss for i, iss in enumerate(issues) if i not in drop_indices]

    @staticmethod
    def _filter_density_on_dense_slides(
        issues: list[Issue],
        extractions: list[SlideExtraction] | None = None,
    ) -> list[Issue]:
        """Suppress B9 underutilized_space on slides with high word count.

        A slide with ≥80 words cannot be "underutilized" — the LLM misjudges
        table/card padding as empty space.  This is a deterministic safety net
        for a known VLM false-positive pattern.
        """
        if not extractions:
            return issues

        MIN_WORDS_FOR_DENSE = 80
        # Build word count and image presence per slide
        words_by_slide: dict[int, int] = {}
        has_visual: dict[int, bool] = {}
        for ext in extractions:
            total = 0
            has_img = False
            for obj in ext.objects:
                if obj.text_content:
                    total += len(obj.text_content.split())
                if getattr(obj, 'has_image', False):
                    has_img = True
            words_by_slide[ext.slide_id] = total
            has_visual[ext.slide_id] = has_img

        result = []
        dropped = 0
        for iss in issues:
            if (iss.issue_type == "density_imbalance"
                    and iss.affected_slides
                    and len(iss.affected_slides) == 1):
                sid = iss.affected_slides[0]
                wc = words_by_slide.get(sid, 0)
                sub = getattr(iss, "sub_type", "") or ""
                if wc >= MIN_WORDS_FOR_DENSE and sub != "content_overflow":
                    dropped += 1
                    logger.info(
                        "Filtered B9 density_imbalance on slide %d "
                        "(word count %d ≥ %d — not underutilized)",
                        sid, wc, MIN_WORDS_FOR_DENSE,
                    )
                    continue
                # Slides with charts/images + ≥40 words are visually dense
                # even if word count is moderate (images fill visual space)
                if (wc >= 40 and has_visual.get(sid, False)
                        and sub != "content_overflow"):
                    dropped += 1
                    logger.info(
                        "Filtered B9 density_imbalance on slide %d "
                        "(has visual + %d words — visually dense)",
                        sid, wc,
                    )
                    continue
            result.append(iss)
        if dropped:
            logger.info(
                "Filtered %d B9 density_imbalance issues on word-dense slides",
                dropped,
            )
        return result

    @staticmethod
    def _filter_density_on_structural_slides(
        issues: list[Issue],
        blueprint: DeckBlueprint | None = None,
    ) -> list[Issue]:
        """Remove B9 density_imbalance (underutilized_space) on structural slides.

        Title, conclusion, section divider, and transition slides naturally
        have whitespace by design. The visual judge prompt already says this,
        but the LLM sometimes ignores it. This is a deterministic safety net.

        Uses blueprint role to identify structural slides. Falls back to
        slide_id == 1 if no blueprint available.
        """
        # Build set of slide IDs that are structural (sparse by design)
        STRUCTURAL_ROLES = {"title", "conclusion", "section_divider",
                            "transition", "closing", "divider", "thank_you"}
        exempt_slides: set[int] = set()

        if blueprint and blueprint.slides:
            for s in blueprint.slides:
                role = getattr(s, "role", "") or ""
                if role.lower() in STRUCTURAL_ROLES:
                    exempt_slides.add(s.slide_id)
            # Also exempt the last slide if it's a conclusion-like role
            last = blueprint.slides[-1]
            last_role = getattr(last, "role", "") or ""
            if last_role.lower() in ("conclusion", "closing", "summary"):
                exempt_slides.add(last.slide_id)

        # Fallback: always exempt slide 1 (title)
        exempt_slides.add(1)

        if not exempt_slides:
            return issues

        result = []
        dropped = 0
        for iss in issues:
            if (iss.issue_type == "density_imbalance"
                    and iss.affected_slides
                    and len(iss.affected_slides) == 1
                    and iss.affected_slides[0] in exempt_slides):
                # Only filter "underutilized_space" — content_overflow on
                # structural slides is still valid (rare but possible)
                sub_type = getattr(iss, "sub_type", "") or ""
                if sub_type == "content_overflow":
                    result.append(iss)
                    continue
                dropped += 1
                logger.info(
                    "Filtered B9 density_imbalance on structural slide %d (role-based): %s",
                    iss.affected_slides[0], iss.issue_id,
                )
                continue
            result.append(iss)
        if dropped:
            logger.info("Filtered %d B9 issues on structural slides (exempt: %s)",
                       dropped, sorted(exempt_slides))
        return result

    # ================================================================
    # ISSUE ROUTING HELPERS
    # ================================================================

    @staticmethod
    def _is_stale_carried_issue(
        issue: Issue, current_turn: int, max_carry: int,
    ) -> bool:
        """Check if a carried issue has been untouched for too long.

        An issue is "stale" if it has been carried forward (never on a
        modified slide) for max_carry or more turns. We detect this by
        checking the issue_id pattern — issues created at turn T have IDs
        that don't change when carried. If the issue has no resolved_at_turn
        and its planned_fix doesn't mention any recent turn activity, it's
        been sitting untouched.

        Heuristic: issues with [PERSISTED] in planned_fix have been triaged
        at least once. Issues with no planned_fix at all are from turn 0
        and have never been re-evaluated — they're the most suspect.
        """
        # RESOLVED or WONT_FIX issues are fine to carry
        if issue.status.value in ("resolved", "wont_fix", "deferred"):
            return False
        # If no planned_fix and we're past max_carry turns, it's stale
        # (never been triaged, original from T0)
        if not issue.planned_fix and current_turn >= max_carry:
            return True
        return False

    # Mapping from issue_type → family string (from centralized registry)
    _ISSUE_TYPE_TO_FAMILY = ISSUE_TYPE_TO_FAMILY

    def _split_previous_issues_by_family(
        self, previous_issues: list[Issue] | None,
    ) -> dict[str, list[Issue]]:
        """Split previous issues by rubric family for targeted routing.

        Each judge only receives the issues relevant to its own rubric
        family, so it doesn't get confused by issues outside its scope.
        """
        if not previous_issues:
            return {}

        by_family: dict[str, list[Issue]] = {}
        for iss in previous_issues:
            # Determine family from rubric_id prefix first, then issue_type
            family = None
            if iss.rubric_id:
                prefix = iss.rubric_id[0].upper()
                family_map = {"A": "A", "B": "B_visual", "C": "C", "D": "D", "E": "E"}
                family = family_map.get(prefix)

            if not family:
                family = self._ISSUE_TYPE_TO_FAMILY.get(iss.issue_type)

            if not family:
                # Unknown family — can't route to any judge for triage.
                # Carry forward as-is rather than silently dropping.
                logger.warning(
                    "Cannot determine family for issue %s (type=%s, rubric=%s), "
                    "carrying forward as PERSISTED",
                    iss.issue_id, iss.issue_type, iss.rubric_id,
                )
                by_family.setdefault("_unroutable", []).append(iss)
                continue

            by_family.setdefault(family, []).append(iss)

        for fam, issues in by_family.items():
            logger.debug(
                "Previous issues for family %s: %d issues",
                fam, len(issues),
            )

        return by_family

    # ================================================================
    # EVALUATION MODES
    # ================================================================

    def _eval_monolithic(
        self,
        extractions: list[SlideExtraction],
        png_paths: list[str],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
    ) -> list[Issue]:
        """Single judge for all rubrics (not recommended)."""
        issues = []
        # Use narrative judge as catch-all in monolithic mode
        try:
            issues.extend(self.narrative_judge.evaluate(
                extractions, task_brief,
                previous_issues=previous_issues, turn_index=turn_index,
            ))
        except Exception as e:
            logger.error("Monolithic eval failed: %s", e)
        return issues

    def _eval_by_family(
        self,
        extractions: list[SlideExtraction],
        png_paths: list[str],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
        modified_slides: set[int] | None = None,
    ) -> list[Issue]:
        """One judge per rubric family — all families run in parallel."""
        # Split previous issues by rubric family for targeted routing
        prev_by_family = self._split_previous_issues_by_family(previous_issues)

        # Select C/D/E evaluators: agent or single-pass
        if self.use_judge_agent:
            completeness_fn = lambda: self.completeness_agent.evaluate(
                extractions, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("C"),
                turn_index=turn_index,
                task_brief=task_brief,
            )
            correctness_fn = lambda: self.correctness_agent.evaluate(
                extractions, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("D"),
                turn_index=turn_index,
            )
            fidelity_fn = lambda: self.fidelity_agent.evaluate(
                extractions, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("E"),
                turn_index=turn_index,
            )
        else:
            completeness_fn = lambda: self.completeness_judge.evaluate(
                extractions, task_brief, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("C"),
                turn_index=turn_index,
            )
            correctness_fn = lambda: self.correctness_judge.evaluate(
                extractions, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("D"),
                turn_index=turn_index,
            )
            fidelity_fn = lambda: self.fidelity_judge.evaluate(
                extractions, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("E"),
                turn_index=turn_index,
            )

        tasks: list[tuple[str, callable]] = [
            ("NarrativeJudge",
             lambda: self.narrative_judge.evaluate(
                 extractions, task_brief,
                 previous_issues=prev_by_family.get("A"),
                 turn_index=turn_index,
             )),
            ("VisualJudge",
             lambda: self.visual_judge.evaluate(
                 extractions, png_paths,
                 previous_issues=prev_by_family.get("B_visual"),
                 turn_index=turn_index,
             )),
            ("CompletenessJudge", completeness_fn),
            ("CorrectnessJudge", correctness_fn),
            ("FidelityJudge", fidelity_fn),
        ]

        issues: list[Issue] = []
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {executor.submit(fn): name for name, fn in tasks}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    issues.extend(future.result())
                except Exception as e:
                    logger.error("%s failed: %s", name, e)

        # Carry forward unroutable issues (unknown family)
        issues.extend(prev_by_family.get("_unroutable", []))

        return issues

    def _eval_family_plus_slide(
        self,
        extractions: list[SlideExtraction],
        png_paths: list[str],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
        modified_slides: set[int] | None = None,
        content_modified_slides: set[int] | None = None,
        _skip_planner: bool = False,
        spatial_signals: dict | None = None,
    ) -> list[Issue]:
        """One judge per family, with slide-scoped visual evaluation.

        All judges run in parallel. Visual judge is split into per-slide
        batches (batch_size=3) that also run in parallel with the other
        families.

        When modified_slides is provided (differential eval), deck-level
        judges (A Narrative, C Completeness) receive ALL extractions so they
        can correctly assess deck-wide properties (slide count, section
        coverage, narrative flow). Per-slide judges (B Visual, D Correctness,
        E Fidelity) are scoped to only the modified slides.

        When content_modified_slides is provided, D/E judges are further
        scoped to only slides with content changes. Slides with spatial-only
        fixes don't need content accuracy re-evaluation — text hasn't changed.
        """
        # Adaptive probe planning: use ProbePlannerAgent for turn > 0
        if (
            turn_index > 0
            and not _skip_planner
            and hasattr(self, 'probe_planner')
        ):
            logger.info(
                "Using ProbePlannerAgent for adaptive evaluation (turn %d)",
                turn_index,
            )
            return self.probe_planner.evaluate(
                extractions, png_paths, task_brief, source_summary,
                blueprint, evidence, previous_issues, turn_index,
                modified_slides, content_modified_slides,
                spatial_signals=spatial_signals,
                source_store=getattr(self.correctness_judge, '_source_store', None),
            )
        # Split previous issues by rubric family
        # Filter out terminal-status issues — they don't need re-triage or re-evaluation
        active_previous = [
            iss for iss in (previous_issues or [])
            if iss.status not in _RESOLVED_STATUSES
        ] or None
        prev_by_family = self._split_previous_issues_by_family(active_previous)

        # Scope extractions for per-slide judges (D, E)
        if modified_slides is not None:
            scoped_extractions = [
                ext for ext in extractions if ext.slide_id in modified_slides
            ]
            prev_for_scoped = [
                iss for iss in (active_previous or [])
                if any(s in modified_slides for s in (iss.affected_slides or []))
            ]
            scoped_prev_by_family = self._split_previous_issues_by_family(
                prev_for_scoped
            )
        else:
            scoped_extractions = extractions
            scoped_prev_by_family = prev_by_family

        # D/E: further scope to content-modified slides only.
        # If only CSS/layout changed on a slide, its text content is identical
        # to the previous turn — re-running D/E is pure noise that blocks
        # convergence (same content → LLM may flip verdicts stochastically).
        content_scoped_extractions = scoped_extractions
        content_scoped_prev_by_family = scoped_prev_by_family
        if content_modified_slides is not None and modified_slides is not None:
            spatial_only_slides = modified_slides - content_modified_slides
            if spatial_only_slides:
                logger.info(
                    "Skipping D/E judges on %d spatial-only slides: %s",
                    len(spatial_only_slides), sorted(spatial_only_slides),
                )
                content_scoped_extractions = [
                    ext for ext in extractions
                    if ext.slide_id in content_modified_slides
                ]
                content_prev = [
                    iss for iss in (active_previous or [])
                    if any(s in content_modified_slides for s in (iss.affected_slides or []))
                ]
                content_scoped_prev_by_family = self._split_previous_issues_by_family(
                    content_prev
                )

        # A, C, D, E: deck-level evaluation tasks
        # Select C/D/E evaluators: agent or single-pass
        # NOTE: D and E use content_scoped_extractions (only slides where
        # text content actually changed). Spatial-only slides are skipped
        # to reduce LLM noise. A and C use full extractions for deck-level.
        if self.use_judge_agent:
            completeness_fn = lambda: self.completeness_agent.evaluate(
                extractions, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("C"),
                turn_index=turn_index,
                task_brief=task_brief,
            )
            correctness_fn = lambda: self.correctness_agent.evaluate(
                content_scoped_extractions, source_summary, blueprint, evidence,
                previous_issues=content_scoped_prev_by_family.get("D"),
                turn_index=turn_index,
            )
            fidelity_fn = lambda: self.fidelity_agent.evaluate(
                content_scoped_extractions, source_summary, blueprint, evidence,
                previous_issues=content_scoped_prev_by_family.get("E"),
                turn_index=turn_index,
            )
        else:
            completeness_fn = lambda: self.completeness_judge.evaluate(
                extractions, task_brief, source_summary, blueprint, evidence,
                previous_issues=prev_by_family.get("C"),
                turn_index=turn_index,
            )
            correctness_fn = lambda: self.correctness_judge.evaluate(
                content_scoped_extractions, source_summary, blueprint, evidence,
                previous_issues=content_scoped_prev_by_family.get("D"),
                turn_index=turn_index,
            )
            fidelity_fn = lambda: self.fidelity_judge.evaluate(
                content_scoped_extractions, source_summary, blueprint, evidence,
                previous_issues=content_scoped_prev_by_family.get("E"),
                turn_index=turn_index,
            )

        tasks: list[tuple[str, callable]] = [
            ("NarrativeJudge",
             lambda: self.narrative_judge.evaluate(
                 extractions, task_brief,
                 previous_issues=prev_by_family.get("A"),
                 turn_index=turn_index,
             )),
            ("CompletenessJudge", completeness_fn),
            ("CorrectnessJudge", correctness_fn),
            ("FidelityJudge", fidelity_fn),
        ]

        # B: Visual — per-slide batched evaluation
        # In differential mode, only evaluate modified slides
        visual_prev = prev_by_family.get("B_visual")
        batch_size = self.config.eval_mode.visual_batch_size
        visual_slide_ids = [
            ext.slide_id for ext in (scoped_extractions if modified_slides else extractions)
        ]
        for i in range(0, len(visual_slide_ids), batch_size):
            scope = visual_slide_ids[i:i + batch_size]
            tasks.append((
                f"VisualJudge[slides {scope}]",
                lambda s=scope: self.visual_judge.evaluate(
                    extractions, png_paths, scope_slides=s,
                    previous_issues=visual_prev,
                    turn_index=turn_index,
                    spatial_signals=spatial_signals,
                ),
            ))

        issues: list[Issue] = []
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {executor.submit(fn): name for name, fn in tasks}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    issues.extend(future.result())
                except Exception as e:
                    logger.error("%s failed: %s", name, e)

        # === FOCUSED C-PROBE SUPPLEMENTATION (T0 only) ===
        # The monolithic CompletenessJudge at T0 has attention dilution
        # across C1-C5, under-detecting C02/C03/C04 compared to the
        # focused ProbeRunner used at T1+. Supplement with focused probes
        # to eliminate measurement discontinuity across turns.
        if turn_index == 0 and hasattr(self, 'probe_planner'):
            try:
                from ..modules.evaluators.probe_runner import ProbeRunner
                probe_runner = ProbeRunner(self.llm, self.config)
                all_slide_ids = [ext.slide_id for ext in extractions]
                c_probe_issues: list[Issue] = []
                c_probe_tasks = []
                for pid in ("C02", "C03", "C04"):
                    c_probe_tasks.append((
                        f"FocusedProbe[{pid}]",
                        lambda _pid=pid: probe_runner.run_probe(
                            _pid, all_slide_ids, extractions,
                            png_paths=png_paths,
                            source_summary=source_summary,
                            task_brief=task_brief,
                            blueprint=blueprint,
                            evidence=evidence,
                            source_store=getattr(
                                self.correctness_judge, '_source_store', None
                            ),
                            turn_index=0,
                        ),
                    ))
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futs = {pool.submit(fn): n for n, fn in c_probe_tasks}
                    for fut in as_completed(futs):
                        name = futs[fut]
                        try:
                            c_probe_issues.extend(fut.result())
                        except Exception as e:
                            logger.warning("%s failed: %s", name, e)
                # Merge: only add focused probe findings not already caught
                # by the monolithic CompletenessJudge (dedup by type+slides)
                existing_c_keys = {
                    (iss.issue_type, tuple(sorted(iss.affected_slides or [])))
                    for iss in issues
                    if (iss.issue_type or "").startswith("missing_")
                }
                added_c = 0
                for ci in c_probe_issues:
                    key = (ci.issue_type, tuple(sorted(ci.affected_slides or [])))
                    if key not in existing_c_keys:
                        issues.append(ci)
                        existing_c_keys.add(key)
                        added_c += 1
                if added_c:
                    logger.info(
                        "Focused C-probes supplemented %d issues "
                        "(eliminating T0 under-detection)", added_c,
                    )
            except Exception as e:
                logger.warning("Focused C-probe supplementation failed: %s", e)

        # Carry forward unroutable issues (unknown family)
        issues.extend(prev_by_family.get("_unroutable", []))

        # Carry forward D/E issues on spatial-only slides (content unchanged,
        # so these issues are still valid — don't drop them silently).
        if content_modified_slides is not None and modified_slides is not None:
            spatial_only = modified_slides - content_modified_slides
            if spatial_only:
                existing_ids = {i.issue_id for i in issues}
                for fam_key in ("D", "E"):
                    for iss in (scoped_prev_by_family.get(fam_key) or []):
                        if any(s in spatial_only for s in (iss.affected_slides or [])):
                            if iss.issue_id not in existing_ids:
                                issues.append(iss)
                                existing_ids.add(iss.issue_id)

                # Suppress NEW soft-aesthetic B issues on spatial-only slides.
                # These are evaluator variance: the B visual judge re-evaluates
                # the PNG and may flag density/redundancy/wall issues that also
                # existed in T0 but weren't flagged. Hard spatial issues
                # (overlap, overflow, OOB) are deterministic and kept.
                _SOFT_AESTHETIC_TYPES = {
                    "density_imbalance", "form_redundancy", "text_wall",
                    "text_visual_imbalance", "alignment_inconsistency",
                    "layout_inappropriate", "low_contrast",
                    "container_contract_breach",
                    "missing_data_visualization",
                }
                prev_keys = {
                    (i.issue_type, tuple(i.affected_slides))
                    for i in (previous_issues or [])
                }
                before_count = len(issues)
                issues = [
                    iss for iss in issues
                    if not (
                        # Only filter NEW issues (not carried/re-triaged)
                        (iss.issue_type, tuple(iss.affected_slides)) not in prev_keys
                        # Only on spatial-only slides
                        and all(s in spatial_only for s in (iss.affected_slides or []))
                        # Only soft aesthetic types
                        and iss.issue_type in _SOFT_AESTHETIC_TYPES
                    )
                ]
                dropped = before_count - len(issues)
                if dropped:
                    logger.info(
                        "Suppressed %d new soft-aesthetic B issues on spatial-only slides "
                        "(evaluator variance)", dropped,
                    )

        return issues
