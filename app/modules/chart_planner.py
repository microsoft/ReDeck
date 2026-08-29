"""ChartPlanner — LLM-driven chart planning for blueprint slides.

Sits between DeckPlanner and HtmlCodeGenCompiler. Analyzes blueprint slides +
table evidence to decide which slides benefit from a pre-generated matplotlib
chart, then fills viz_data on those slides so the compiler's Phase 0 hook
picks them up automatically.
"""

import json
import logging
from pathlib import Path
from typing import Any

from ..llm_client import LLMClient
from ..schemas.blueprint import DeckBlueprint
from ..schemas.evidence import EvidenceState

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "planner" / "chart_planner.system.md"


class ChartPlanner:
    """Analyze blueprint slides + evidence to plan data visualizations."""

    def __init__(self, llm: LLMClient, model: str | None = None):
        self.llm = llm
        self.model = model
        self.system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def plan_charts(
        self,
        blueprint: DeckBlueprint,
        evidence: EvidenceState,
        source_store: Any = None,
    ) -> int:
        """Decide which slides need charts and fill viz_data in-place.

        Returns the number of slides that received chart specs.
        """
        # Collect table data available in evidence
        table_summaries = self._collect_tables(evidence, source_store)
        if not table_summaries:
            logger.info("ChartPlanner: no tables in evidence, skipping")
            return 0

        # Build user prompt with slide overview + table data
        user_content = self._build_user_prompt(blueprint, table_summaries)

        try:
            raw = self.llm.call_text(
                system_prompt=self.system_prompt,
                user_content=user_content,
                model=self.model,
                module_name="chart_planner",
                prompt_version="chart_planner.v1",
                max_tokens=4096,
                temperature=0.2,
            )
            chart_specs = self._parse_response(raw)
        except Exception as e:
            logger.warning("ChartPlanner LLM call failed: %s — skipping charts", e)
            return 0

        # Apply chart specs to blueprint
        count = 0
        slide_map = {s.slide_id: s for s in blueprint.slides}
        for spec in chart_specs:
            sid = spec.get("slide_id")
            viz = spec.get("viz_data", {})
            if sid in slide_map and viz and viz.get("chart_type"):
                slide_map[sid].viz_data = viz
                count += 1
                logger.info(
                    "ChartPlanner: slide %d → %s chart (%s)",
                    sid, viz["chart_type"], viz.get("title", ""),
                )

        logger.info("ChartPlanner: planned %d charts for %d slides", count, len(blueprint.slides))
        return count

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _collect_tables(
        self, evidence: EvidenceState, source_store: Any,
    ) -> list[dict]:
        """Gather table data from evidence and/or source_store."""
        tables = []

        # Primary: from evidence.tables
        for tbl in evidence.tables:
            entry = {
                "table_id": tbl.table_id,
                "caption": tbl.caption or "",
                "content": (tbl.content or "")[:3000],  # cap size
                "headers": tbl.headers or [],
            }
            tables.append(entry)

        # Supplement from source_store if available
        if source_store and hasattr(source_store, "table_data"):
            for td in source_store.table_data:
                tid = getattr(td, "table_id", "") or getattr(td, "asset_id", "")
                if tid and not any(t["table_id"] == tid for t in tables):
                    content = getattr(td, "markdown", "") or getattr(td, "content", "")
                    tables.append({
                        "table_id": tid,
                        "caption": getattr(td, "caption", "") or "",
                        "content": content[:3000],
                        "headers": getattr(td, "headers", []) or [],
                    })

        return tables

    def _build_user_prompt(
        self, blueprint: DeckBlueprint, tables: list[dict],
    ) -> str:
        """Build the user prompt combining slide overview and table data."""
        parts = []

        parts.append("## Slide Overview\n")
        for s in blueprint.slides:
            fig_note = f" [has paper figure: {s.assigned_figure_id}]" if s.assigned_figure_id else ""
            parts.append(
                f"- Slide {s.slide_id}: role={s.role}, "
                f"goal=\"{s.primary_proposition}\"{fig_note}"
            )

        parts.append("\n## Available Table Data\n")
        for tbl in tables:
            parts.append(f"### {tbl['table_id']}")
            if tbl["caption"]:
                parts.append(f"Caption: {tbl['caption']}")
            if tbl["content"]:
                # Limit to first 2000 chars of table content
                content = tbl["content"][:2000]
                parts.append(f"```\n{content}\n```")
            parts.append("")

        parts.append(
            "\nAnalyze the slides and tables above. "
            "Return a JSON array of chart specifications for slides "
            "that would benefit from a generated chart. "
            "Use exact numbers from the tables."
        )

        return "\n".join(parts)

    @staticmethod
    def _parse_response(raw: str) -> list[dict]:
        """Extract JSON array from LLM response."""
        # Try to find JSON array in the response
        text = raw.strip()

        # Strip markdown code fences
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        # Find the outermost JSON array
        bracket_start = text.find("[")
        bracket_end = text.rfind("]")
        if bracket_start >= 0 and bracket_end > bracket_start:
            text = text[bracket_start:bracket_end + 1]

        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
            return []
        except json.JSONDecodeError:
            logger.warning("ChartPlanner: failed to parse JSON from response")
            return []
