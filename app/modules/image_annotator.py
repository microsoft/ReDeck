"""ImageAnnotator - uses VLM to generate content descriptions for extracted figures and tables."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..llm_client import LLMClient
from ..schemas.evidence import FigureRef, TableRef
from ..utils.image_ops import image_to_base64

logger = logging.getLogger(__name__)

_FIGURE_ANNOTATION_PROMPT = """You are an expert at describing academic paper figures.
Given an image extracted from a research paper, provide a concise, factual description.

Your description should cover:
1. What TYPE of figure this is (architecture diagram, bar chart, line plot, table screenshot, photo, scatter plot, heatmap, flowchart, etc.)
2. What it SHOWS (the main content, axes, data series, components)
3. Key NUMBERS or labels visible in the figure
4. What TOPIC it relates to (training, evaluation, model architecture, data processing, etc.)

Return ONLY the description, 2-4 sentences. Be specific and factual. Do not speculate."""

_TABLE_ANNOTATION_PROMPT = """You are an expert at describing academic paper tables.
Given a screenshot of a table from a research paper, provide a concise, factual description.

Your description should cover:
1. What the table COMPARES (models, methods, datasets, hyperparameters, etc.)
2. What METRICS or columns are shown
3. Key FINDINGS: which method/model performs best, notable trends
4. How many rows/columns and what the structure is (nested headers, multi-column, etc.)

Return ONLY the description, 2-4 sentences. Be specific about numbers and rankings. Do not speculate."""


class ImageAnnotator:
    """Annotates extracted figures with VLM-generated content descriptions."""

    def __init__(self, llm: LLMClient, model: str | None = None):
        self.llm = llm
        self.model = model or llm.default_model

    def annotate_figures(
        self, figures: list[FigureRef], max_figures: int = 30
    ) -> list[FigureRef]:
        """Annotate each figure with a VLM-generated description.

        Modifies FigureRef.description in place and returns the list.
        Only annotates embedded figures (skips page screenshots).
        Limits to max_figures to control API costs.
        Uses parallel VLM calls for speed.
        """
        # Annotate all content figures — skip page screenshots and table screenshots
        _SKIP_TYPES = {"page_screenshot", "table_screenshot"}
        content_figs = [f for f in figures if f.figure_type not in _SKIP_TYPES]
        to_annotate = [
            f for f in content_figs[:max_figures]
            if f.image_path and Path(f.image_path).exists()
        ]

        if not to_annotate:
            return figures

        max_workers = min(len(to_annotate), 2)
        logger.info(
            "Annotating %d figures with VLM (parallel, %d workers)...",
            len(to_annotate), max_workers,
        )

        annotated_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._annotate_one_figure, fig): fig
                for fig in to_annotate
            }
            for future in as_completed(future_map):
                fig = future_map[future]
                try:
                    description = future.result()
                    if description:
                        fig.description = description
                        annotated_count += 1
                except Exception as e:
                    logger.warning(
                        "Failed to annotate %s: %s", fig.figure_id, str(e)[:100]
                    )

        logger.info(
            "VLM figure annotation complete: %d/%d figures annotated",
            annotated_count, len(to_annotate),
        )
        return figures

    def annotate_tables(
        self, tables: list[TableRef], max_tables: int = 15
    ) -> list[TableRef]:
        """Annotate each table with a VLM-generated description.

        Only annotates tables that have an image_path (PNG screenshot).
        Modifies TableRef.description in place and returns the list.
        Uses parallel VLM calls for speed.
        """
        to_annotate = [
            t for t in tables
            if t.image_path and Path(t.image_path).exists()
        ][:max_tables]

        if not to_annotate:
            return tables

        max_workers = min(len(to_annotate), 2)
        logger.info(
            "Annotating %d tables with VLM (parallel, %d workers)...",
            len(to_annotate), max_workers,
        )

        annotated_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._annotate_one_table, tbl): tbl
                for tbl in to_annotate
            }
            for future in as_completed(future_map):
                tbl = future_map[future]
                try:
                    description = future.result()
                    if description:
                        tbl.description = description
                        annotated_count += 1
                except Exception as e:
                    logger.warning(
                        "Failed to annotate %s: %s", tbl.table_id, str(e)[:100]
                    )

        logger.info(
            "VLM table annotation complete: %d/%d tables annotated",
            annotated_count, len(to_annotate),
        )
        return tables

    def _annotate_one_figure(self, fig: FigureRef) -> str | None:
        """Generate a VLM description for a single figure."""
        b64_url = image_to_base64(fig.image_path, max_size=768)

        context = f"This image is from a research paper."
        if fig.caption:
            context += f" Original caption: \"{fig.caption}\""
        if fig.page_number:
            context += f" (page {fig.page_number})"

        response = self.llm.call_vision(
            system_prompt=_FIGURE_ANNOTATION_PROMPT,
            text_content=context,
            image_urls=[b64_url],
            model=self.model,
            module_name="image_annotator",
            prompt_version="annotate_figure.v2",
            max_tokens=300,
            temperature=0.1,
        )
        return response.strip() if response else None

    def _annotate_one_table(self, tbl: TableRef) -> str | None:
        """Generate a VLM description for a single table screenshot."""
        b64_url = image_to_base64(tbl.image_path, max_size=1024)

        context = f"This is a table from a research paper."
        if tbl.caption:
            context += f" Caption: \"{tbl.caption}\""
        if tbl.page_number:
            context += f" (page {tbl.page_number})"
        if tbl.headers:
            context += f" Columns: {', '.join(tbl.headers[:8])}"

        response = self.llm.call_vision(
            system_prompt=_TABLE_ANNOTATION_PROMPT,
            text_content=context,
            image_urls=[b64_url],
            model=self.model,
            module_name="image_annotator",
            prompt_version="annotate_table.v1",
            max_tokens=400,
            temperature=0.1,
        )
        return response.strip() if response else None
