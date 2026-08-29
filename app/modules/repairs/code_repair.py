"""CodeRepairWorker - repairs slides by modifying generated python-pptx code.

Pure LLM repair: sends current slide code + all issues to the LLM
and gets back corrected code.  No rule-based filtering, priority
sorting, or issue capping — all open issues are forwarded to the
repair LLM as-is.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from ...llm_client import LLMClient
from ...schemas.issue import Issue
from ...schemas.blueprint import BlueprintSlide
from ...schemas.evidence import EvidenceState
from ...schemas.issue_types import CRITICAL_CONTENT_TYPES

logger = logging.getLogger(__name__)


class CodeRepairWorker:
    """Repairs slide code using LLM."""

    def __init__(self, llm: LLMClient, model: str = "gpt-5.4"):
        self.llm = llm
        self.model = model

    def repair_slides(
        self,
        codegen_compiler,  # CodeGenCompiler instance
        issues: list[Issue],
        blueprint_slides: list[BlueprintSlide],
        evidence: EvidenceState,
        case_dir: str,
    ) -> list[int]:
        """Repair slides that have issues.

        All open issues are sent to the LLM for repair — no rule-based
        filtering by severity, issue type, or recurrence count.

        Returns list of slide_ids that were successfully repaired.
        """
        # Group issues by slide — only filter by status == open
        slide_issues: dict[int, list[dict]] = {}
        for issue in issues:
            if issue.status.value != "open":
                continue
            for sid in issue.affected_slides:
                if sid not in slide_issues:
                    slide_issues[sid] = []
                slide_issues[sid].append({
                    "severity": issue.severity.value,
                    "rubric_id": issue.rubric_id,
                    "issue_type": issue.issue_type,
                    "description": issue.evidence.description or issue.why_this_fails or issue.issue_type,
                    "planned_fix": issue.planned_fix or "",
                })

        # Allow B* (layout/visual) + critical content issues through.
        # Previously all C/D/E issues were dropped; now fabricated/incorrect
        # content can be repaired with text-only edits.
        for sid in list(slide_issues.keys()):
            slide_issues[sid] = [
                d for d in slide_issues[sid]
                if d.get("rubric_id", "").startswith("B")
                or d.get("issue_type", "") in CRITICAL_CONTENT_TYPES
            ]
            if not slide_issues[sid]:
                logger.info("Slide %d: skipping repair (no actionable issues)", sid)
                del slide_issues[sid]
                continue
            severities = {d["severity"] for d in slide_issues[sid]}
            if severities <= {"minor", "cosmetic"}:
                logger.info(
                    "Slide %d: skipping repair (only %s issues: %s)",
                    sid, severities,
                    [d["rubric_id"] for d in slide_issues[sid]],
                )
                del slide_issues[sid]

        if not slide_issues:
            logger.info("No actionable issues for code repair")
            return []

        # Build slide lookup
        slide_map = {s.slide_id: s for s in blueprint_slides}

        repaired = []
        # Parallelize repair calls — each slide is independent
        def _repair_one(sid: int, iss_list: list[dict]) -> tuple[int, bool]:
            bp_slide = slide_map.get(sid)
            new_code = codegen_compiler.repair_slide(
                slide_id=sid,
                issues=iss_list,
                blueprint_slide=bp_slide,
                evidence=evidence,
                case_dir=case_dir,
            )
            return sid, new_code is not None

        max_workers = min(len(slide_issues), 12)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_repair_one, sid, iss_list): sid
                for sid, iss_list in slide_issues.items()
            }
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    sid, success = future.result()
                    if success:
                        repaired.append(sid)
                        logger.info("Slide %d repaired (%d issues addressed)", sid, len(slide_issues[sid]))
                    else:
                        logger.warning("Slide %d repair failed", sid)
                except Exception as e:
                    logger.error("Slide %d repair raised exception: %s", sid, e)

        return repaired
