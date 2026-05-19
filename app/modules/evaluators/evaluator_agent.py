"""EvaluatorAgent - wraps D/E judges with an investigation loop.

Instead of single-pass evaluation, the agent:
1. Turn 1: Receives slide claims + source summary. Can call search_source
   and lookup_table tools to verify suspicious claims.
2. Turn 2: With tool results in context, produces final issue judgments.

This addresses comment B1 (low-quality issues), B3 (judge not loading
complete materials), and reduces fabricated-issue noise by requiring
evidence grounding.
"""

import json
import logging
import re
from typing import Any

from ...llm_client import LLMClient
from ...schemas.blueprint import DeckBlueprint
from ...schemas.evidence import EvidenceState
from ...schemas.experiment_config import ExperimentConfig
from ...schemas.extraction import SlideExtraction
from ...schemas.issue import Issue
from ...schemas.common import Confidence, Severity
from .base_judge import BaseJudge
from .eval_tools import format_tool_results, search_source

logger = logging.getLogger(__name__)

# Maximum tool calls per evaluation — dynamically computed per evaluate() call
# based on number of slides. Minimum 20, scaling by 3 per slide.
DEFAULT_MAX_EVAL_TOOL_CALLS = 20

# Tool definitions for the judge agent system prompt
TOOL_INSTRUCTIONS = """
## Available Tools

You may call tools to verify claims before reporting issues. Use JSON format:

### search_source
Search the source paper for specific content. Use this to verify whether
a claim on a slide is supported by the source before reporting it as
fabricated or incorrect.

```json
{
  "tool": "search_source",
  "query": "your search keywords",
  "top_k": 5
}
```

### lookup_table
Look up a specific table in the source materials. Use this to verify
numeric values, comparisons, or data references.

```json
{
  "tool": "lookup_table",
  "query": "table topic or caption keywords"
}
```

### submit_issues
When you have finished investigating, submit your final issues.
You MUST use this tool to submit your final judgment.

```json
{
  "tool": "submit_issues",
  "result": {
    "rubric_family": "D",
    "issues": [...]
  }
}
```

## Workflow

1. First, review the slide claims and source materials provided.
2. For EVERY numeric value and specific claim on each slide, use search_source or lookup_table
   to verify it exists in the source materials.
3. Report an issue if:
   a. You find CONTRADICTING evidence via tool calls, OR
   b. The claim contains specific numbers/percentages that do NOT appear in any tool result, OR
   c. A chart displays data values that don't match source tables
4. Submit your final issues using submit_issues.

## Evidence Requirement

For EVERY issue you report, you MUST include which tool call result
supports your finding. If you did not verify a claim with a tool call,
set confidence to "low" (these will be filtered out).
Issues with tool-verified evidence should have confidence "high" or "medium".

## IMPORTANT: Be Thorough
You MUST check ALL slides with numeric data (charts, tables, metrics).
A common failure mode is fabricated chart data — the codegen LLM invents
plausible-looking numbers. Verify EVERY number in charts against the source.
"""


class EvaluatorAgent:
    """Agent-based evaluator that wraps D/E judges with tool use.

    Converts single-pass judges into a 2-turn loop:
    1. Review claims + optional tool calls for investigation
    2. Submit verified issues

    This significantly reduces false positives by requiring evidence
    grounding before reporting issues.
    """

    def __init__(self, judge: BaseJudge, llm: LLMClient, config: ExperimentConfig):
        """Initialize with an existing judge instance.

        Args:
            judge: A BaseJudge subclass (CorrectnessJudge or FidelityJudge)
            llm: LLM client for multi-turn calls
            config: Experiment config for model selection
        """
        self.judge = judge
        self.llm = llm
        self.config = config
        self.system_prompt = judge.system_prompt + TOOL_INSTRUCTIONS

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        source_summary: str = "",
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
        task_brief: str = "",
    ) -> list[Issue]:
        """Run agent-based evaluation with tool use.

        Uses the two-call pattern:
        1. Triage previous issues via dedicated verdict-only LLM call
        2. Fresh judge via agent tool loop (no previous issues context)
        3. Dedup and combine
        """
        # Build the initial user message (same as the original judge)
        user_content = self._build_user_content(extractions, source_summary,
                                                 blueprint, evidence,
                                                 task_brief=task_brief)

        model = self.config.models.get_model(self.judge.module_name)
        all_slides = [ext.slide_id for ext in extractions]

        # Store task_brief for potential fallback to CompletenessJudge
        self._last_task_brief = task_brief

        # --- STEP 1: Triage previous issues (dedicated verdict-only call) ---
        triaged_issues: list[Issue] = []
        if previous_issues:
            triaged_issues = self.judge._triage_previous_issues(
                previous_issues, all_slides, user_content, model, turn_index,
            )

        # --- STEP 2: Fresh judge via agent loop (NO previous issues) ---
        # Dynamic tool call limit based on slide count
        max_tool_calls = max(DEFAULT_MAX_EVAL_TOOL_CALLS, len(extractions) * 3)

        # Resolve evidence for in-loop source challenge
        _evidence = evidence
        if not _evidence:
            _src = getattr(self.judge, "_source_store", None)
            if _src and hasattr(_src, "to_evidence_state"):
                _evidence = _src.to_evidence_state()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        tool_calls = 0
        challenged = False  # True after we've already challenged once
        while tool_calls < max_tool_calls:
            try:
                response = self.llm.call_multiturn(
                    messages=messages,
                    model=model,
                    module_name=f"{self.judge.module_name}_agent",
                    prompt_version=f"{self.judge.module_name}_agent.v1",
                    max_tokens=4096,
                    temperature=0.2,
                )
            except Exception as e:
                logger.warning(
                    "EvaluatorAgent %s LLM error at turn %d: %s",
                    self.judge.module_name, tool_calls, str(e)[:200],
                )
                # Fall back to single-pass evaluation
                return self._fallback_evaluate(
                    extractions, source_summary, blueprint, evidence,
                    previous_issues, turn_index,
                )

            messages.append({"role": "assistant", "content": response})

            # Parse action from response
            action = self._parse_action(response)

            if action is None:
                # If we can't parse, ask for retry
                messages.append({"role": "user", "content":
                    "Error: could not parse your response. "
                    "Please return a JSON object with a 'tool' field. "
                    "Use 'submit_issues' when ready to submit your final judgment."
                })
                tool_calls += 1
                continue

            tool_name = action.get("tool", "")

            # Handle submit_issues
            if tool_name == "submit_issues":
                result_data = action.get("result", {})
                if isinstance(result_data, str):
                    try:
                        result_data = json.loads(result_data)
                    except json.JSONDecodeError:
                        result_data = {}

                # Parse issues from the submitted result
                raw_json = json.dumps(result_data, ensure_ascii=False)
                new_issues = self.judge._parse_issues(
                    raw_json, all_slides, previous_issues=None, turn_index=turn_index,
                )

                # --- In-loop source challenge ---
                # Before accepting, check if any content issues can be
                # challenged with source evidence. If so, inject BM25
                # results back into the conversation and ask the judge to
                # reconsider. This is more principled than post-hoc
                # dropping because the judge sees the evidence and decides.
                if not challenged and _evidence and getattr(_evidence, "chunks", None):
                    challenge_msg = self._build_source_challenge(new_issues, _evidence)
                    if challenge_msg:
                        challenged = True
                        messages.append({"role": "user", "content": challenge_msg})
                        tool_calls += 1
                        logger.info(
                            "EvaluatorAgent %s: challenging %s with source evidence",
                            self.judge.module_name,
                            [i.issue_id for i in new_issues
                             if i.issue_type in self._VERIFY_TYPES],
                        )
                        continue  # let judge reconsider and resubmit

                # Accept final submission (either post-challenge or no challenge needed)

                # Dedup new issues against triaged previous issues
                if triaged_issues:
                    new_issues = self.judge._dedup_new_against_triaged(
                        new_issues, triaged_issues,
                    )

                issues = triaged_issues + new_issues
                logger.info(
                    "EvaluatorAgent %s: submitted %d new + %d triaged issues after %d tool calls (challenged=%s)",
                    self.judge.module_name, len(new_issues), len(triaged_issues), tool_calls, challenged,
                )
                return issues

            # Handle search/lookup tools
            if tool_name in ("search_source", "lookup_table"):
                tool_result = format_tool_results(tool_name, action, evidence)
                messages.append({"role": "user", "content":
                    f"Tool result ({tool_name}):\n\n{tool_result}\n\n"
                    f"Continue investigating or use submit_issues to submit your final judgment."
                })
                tool_calls += 1
                continue

            # Unknown tool
            messages.append({"role": "user", "content":
                f"Unknown tool: '{tool_name}'. Available tools: "
                f"search_source, lookup_table, submit_issues."
            })
            tool_calls += 1

        # If we exhausted tool calls, try to extract issues from the last response
        logger.warning(
            "EvaluatorAgent %s: exhausted %d tool calls without submit",
            self.judge.module_name, max_tool_calls,
        )
        fallback_issues = self._fallback_evaluate(
            extractions, source_summary, blueprint, evidence,
            previous_issues=None, turn_index=turn_index,
        )
        # Second-pass source verification
        fallback_issues = self._verify_content_issues(fallback_issues, evidence)
        # Combine with already-triaged previous issues
        if triaged_issues:
            fallback_issues = self.judge._dedup_new_against_triaged(
                fallback_issues, triaged_issues,
            )
        return triaged_issues + fallback_issues

    def _build_user_content(
        self,
        extractions: list[SlideExtraction],
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        task_brief: str = "",
    ) -> str:
        """Build user content message, matching the original judge format."""
        if self.judge.rubric_family == "C":
            return self._build_completeness_content(
                extractions, task_brief, source_summary, blueprint, evidence
            )
        elif self.judge.rubric_family == "D":
            return self._build_correctness_content(
                extractions, source_summary, blueprint, evidence
            )
        elif self.judge.rubric_family == "E":
            return self._build_fidelity_content(
                extractions, source_summary, blueprint, evidence
            )
        else:
            # Generic fallback
            claims = []
            for ext in extractions:
                texts = [obj.text_content for obj in ext.objects if obj.text_content.strip()]
                # HTML fallback for HTML→PNG mode
                if not texts:
                    slide_codes = getattr(self.judge, '_slide_codes', None) or {}
                    html = slide_codes.get(ext.slide_id, '')
                    if html:
                        from .completeness_judge import _extract_text_from_html
                        texts = [_extract_text_from_html(html)]
                claims.append({
                    "slide_id": ext.slide_id,
                    "title": ext.title,
                    "content": "\n".join(texts)[:1500],
                })
            return json.dumps({
                "deck_content": claims,
                "source_materials": source_summary[:40000],
            }, indent=2, ensure_ascii=False)

    def _build_completeness_content(
        self,
        extractions: list[SlideExtraction],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
    ) -> str:
        """Build content for completeness judge (same as CompletenessJudge.evaluate)."""
        content_summary = []
        for ext in extractions:
            texts = [obj.text_content for obj in ext.objects if obj.text_content.strip()]
            # HTML fallback for HTML→PNG mode
            if not texts:
                slide_codes = getattr(self.judge, '_slide_codes', None) or {}
                html = slide_codes.get(ext.slide_id, '')
                if html:
                    from .completeness_judge import _extract_text_from_html
                    texts = [_extract_text_from_html(html)]
            entry = {
                "slide_id": ext.slide_id,
                "title": ext.title,
                "content": "\n".join(texts)[:1500],
            }
            slide_ev = self.judge._build_slide_evidence(
                ext.slide_id, blueprint, evidence,
                source_store=getattr(self.judge, '_source_store', None),
                slide_text="\n".join(texts),
            )
            if slide_ev:
                entry["source_evidence"] = slide_ev
            content_summary.append(entry)

        return json.dumps({
            "deck_content": content_summary,
            "task_brief": task_brief,
            "source_summary": source_summary,
            "total_slides": len(extractions),
        }, indent=2, ensure_ascii=False)

    def _build_correctness_content(
        self,
        extractions: list[SlideExtraction],
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
    ) -> str:
        """Build content for correctness judge (same as CorrectnessJudge.evaluate)."""
        claims = []
        for ext in extractions:
            slide_claims = []
            for obj in ext.objects:
                if obj.text_content.strip():
                    slide_claims.append(obj.text_content.strip())

            entry = {
                "slide_id": ext.slide_id,
                "title": ext.title,
                "claims": slide_claims,
            }
            slide_ev = self.judge._build_slide_evidence(
                ext.slide_id, blueprint, evidence,
                source_store=getattr(self.judge, '_source_store', None),
                slide_text=" ".join(slide_claims),
            )
            if slide_ev:
                entry["source_evidence"] = slide_ev
            claims.append(entry)

        return json.dumps({
            "deck_claims": claims,
            "source_materials": source_summary,  # full source, no truncation
        }, indent=2, ensure_ascii=False)

    def _build_fidelity_content(
        self,
        extractions: list[SlideExtraction],
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
    ) -> str:
        """Build content for fidelity judge (same as FidelityJudge.evaluate)."""
        deck_content = []
        for ext in extractions:
            texts = [obj.text_content for obj in ext.objects if obj.text_content.strip()]
            entry = {
                "slide_id": ext.slide_id,
                "title": ext.title,
                "content": "\n".join(texts)[:1500],
            }
            slide_ev = self.judge._build_slide_evidence(
                ext.slide_id, blueprint, evidence,
                source_store=getattr(self.judge, '_source_store', None),
                slide_text="\n".join(texts),
            )
            if slide_ev:
                entry["source_evidence"] = slide_ev
            deck_content.append(entry)

        return json.dumps({
            "deck_content": deck_content,
            "source_materials": source_summary,  # full source, no truncation
        }, indent=2, ensure_ascii=False)

    def _parse_action(self, response: str) -> dict | None:
        """Parse a tool call from the LLM response.

        Tries to find a JSON object with a "tool" field in the response.
        """
        # Try to find JSON block in the response
        # Strategy 1: find ```json ... ``` block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if "tool" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # Strategy 2: find any JSON object with "tool" field
        for match in re.finditer(r'\{[^{}]*"tool"[^{}]*\}', response, re.DOTALL):
            try:
                data = json.loads(match.group())
                return data
            except json.JSONDecodeError:
                continue

        # Strategy 3: try to parse the entire response as JSON
        try:
            data = json.loads(response.strip())
            if isinstance(data, dict):
                if "tool" in data:
                    return data
                # If it looks like a final submission (has "issues" key), wrap it
                if "issues" in data:
                    return {"tool": "submit_issues", "result": data}
        except json.JSONDecodeError:
            pass

        # Strategy 4: if response contains issue JSON without tool wrapper,
        # treat as implicit submit
        if '"rubric_family"' in response and '"issues"' in response:
            try:
                # Find the JSON with issues
                json_match = re.search(r'\{[^{]*"rubric_family".*?"issues"\s*:\s*\[.*?\]\s*\}',
                                       response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    return {"tool": "submit_issues", "result": data}
            except json.JSONDecodeError:
                pass

        return None

    def _fallback_evaluate(
        self,
        extractions: list[SlideExtraction],
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
    ) -> list[Issue]:
        """Fall back to single-pass evaluation if agent loop fails."""
        logger.info(
            "EvaluatorAgent %s: falling back to single-pass evaluation",
            self.judge.module_name,
        )
        if self.judge.rubric_family == "D":
            from .correctness_judge import CorrectnessJudge
            if isinstance(self.judge, CorrectnessJudge):
                return self.judge.evaluate(
                    extractions, source_summary, blueprint, evidence,
                    previous_issues, turn_index,
                )
        elif self.judge.rubric_family == "E":
            from .fidelity_judge import FidelityJudge
            if isinstance(self.judge, FidelityJudge):
                return self.judge.evaluate(
                    extractions, source_summary, blueprint, evidence,
                    previous_issues, turn_index,
                )
        elif self.judge.rubric_family == "C":
            from .completeness_judge import CompletenessJudge
            if isinstance(self.judge, CompletenessJudge):
                return self.judge.evaluate(
                    extractions, self._last_task_brief or "",
                    source_summary, blueprint, evidence,
                    previous_issues, turn_index,
                )
        # Generic fallback
        return []

    # ------------------------------------------------------------------
    # In-loop source challenge (replaces post-hoc filtering)
    # ------------------------------------------------------------------

    _VERIFY_TYPES = frozenset({
        "fabricated", "incorrect_claim", "untraceable", "unfaithful_compression",
    })

    def _build_source_challenge(
        self,
        issues: list[Issue],
        evidence: EvidenceState,
    ) -> str | None:
        """Build a challenge message for content issues with source evidence.

        For each fabricated/incorrect/untraceable issue, searches the source
        via BM25. If a strong match is found, includes the source passage
        and asks the judge to reconsider.

        Returns a challenge prompt string, or None if no issues are challengeable.
        """
        challenges: list[str] = []

        for issue in issues:
            if issue.issue_type not in self._VERIFY_TYPES:
                continue

            claim = self._extract_claim_text(issue)
            if not claim or len(claim) < 15:
                continue

            # BM25 search
            result_text = search_source(claim, evidence, top_k=3)
            score = self._word_overlap_score(claim, result_text)

            if score < 0.5:
                continue  # low overlap — no strong source match to challenge with

            # Build per-issue challenge
            challenges.append(
                f"### Issue `{issue.issue_id}` [{issue.issue_type}] — Source Evidence Found\n"
                f"Claim: \"{claim[:200]}\"\n"
                f"Word overlap with source: {score:.0%}\n"
                f"Source passages:\n{result_text[:800]}\n"
            )

        if not challenges:
            return None

        return (
            "## Source Challenge — Please Reconsider\n\n"
            "I found source passages that appear to SUPPORT some of your reported issues. "
            "The source material below was retrieved via keyword search. "
            "Please review each challenged issue and decide:\n"
            "- If the source SUPPORTS the slide claim → **withdraw** the issue\n"
            "- If the source CONTRADICTS or the match is superficial → **keep** the issue\n"
            "- If the claim is a reasonable simplification → downgrade to `unfaithful_compression` with severity `minor`\n\n"
            + "\n".join(challenges)
            + "\n\nPlease resubmit your final issues using `submit_issues`, "
            "removing or adjusting any issues where the source evidence "
            "supports the slide content."
        )

    def _verify_content_issues(
        self,
        issues: list[Issue],
        evidence: EvidenceState | None,
    ) -> list[Issue]:
        """Re-verify fabricated/incorrect claims against source via BM25.

        For each non-HIGH-confidence content issue, search the source for
        the claimed text. If a strong match is found, the issue is likely a
        false positive (judge missed the source passage) and is dropped or
        downgraded.

        Uses BM25 text search — no LLM call, fast and deterministic.
        """
        if not evidence:
            # Try to get evidence from source_store
            source_store = getattr(self.judge, "_source_store", None)
            if source_store and hasattr(source_store, "to_evidence_state"):
                evidence = source_store.to_evidence_state()
        if not evidence or not getattr(evidence, "chunks", None):
            return issues

        verified: list[Issue] = []
        for issue in issues:
            if issue.issue_type not in self._VERIFY_TYPES:
                verified.append(issue)
                continue
            # For HIGH confidence: use stricter threshold (0.8)
            # For MEDIUM/LOW: use standard threshold (0.6)
            is_high_conf = issue.confidence == Confidence.HIGH
            drop_threshold = 0.8 if is_high_conf else 0.6
            downgrade_threshold = 0.85 if is_high_conf else 0.7

            claim = self._extract_claim_text(issue)
            if not claim or len(claim) < 15:
                verified.append(issue)
                continue

            # BM25 search
            result_text = search_source(claim, evidence, top_k=3)
            score = self._word_overlap_score(claim, result_text)

            if score > drop_threshold:
                if issue.issue_type in ("fabricated", "untraceable"):
                    logger.info(
                        "Second-pass: dropping %s issue %s (source match %.2f, threshold %.2f)",
                        issue.issue_type, issue.issue_id, score, drop_threshold,
                    )
                    continue  # drop — source supports the claim
                elif issue.issue_type == "incorrect_claim" and score > downgrade_threshold:
                    issue.issue_type = "unfaithful_compression"
                    issue.severity = Severity.MINOR
                    issue.rubric_id = "E3"
                    logger.info(
                        "Second-pass: downgraded incorrect_claim %s → minor unfaithful_compression (%.2f)",
                        issue.issue_id, score,
                    )
                elif issue.issue_type == "unfaithful_compression" and score > downgrade_threshold:
                    issue.severity = Severity.MINOR
                    logger.info(
                        "Second-pass: downgraded unfaithful_compression %s → minor (%.2f)",
                        issue.issue_id, score,
                    )

            verified.append(issue)

        dropped = len(issues) - len(verified)
        if dropped:
            logger.info(
                "Second-pass verification: dropped %d/%d content issues",
                dropped, len(issues),
            )
        return verified

    @staticmethod
    def _extract_claim_text(issue: Issue) -> str:
        """Extract the key claim from an issue's evidence for source search."""
        desc = ""
        if issue.evidence and issue.evidence.description:
            desc = issue.evidence.description
        if not desc:
            desc = issue.why_this_fails or ""
        # Prefer quoted text (the actual slide claim)
        quotes = re.findall(r'"([^"]{10,})"', desc)
        if quotes:
            return quotes[0]
        return desc[:120]

    @staticmethod
    def _word_overlap_score(claim: str, search_result: str) -> float:
        """Word-overlap between claim and BM25 search results."""
        if not search_result or "No results found" in search_result:
            return 0.0
        _STOP = {
            "the", "a", "an", "is", "are", "was", "were", "in", "on", "of",
            "and", "or", "to", "for", "with", "that", "this", "it", "by",
            "as", "at", "be", "but", "not", "from", "have", "has", "had",
        }
        claim_words = set(re.sub(r"[^a-zA-Z0-9\s]", "", claim.lower()).split()) - _STOP
        if not claim_words:
            return 0.0
        result_words = set(re.sub(r"[^a-zA-Z0-9\s]", "", search_result.lower()).split())
        return len(claim_words & result_words) / len(claim_words)
