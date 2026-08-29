"""SourceIndexer - parses source materials into EvidenceState.

New pyramid structure:
  source_pack/
    paper_full.md        - text chunks (only source of text, no duplicates)
    figures/             - figure images (from FigureExtractor)
    tables/              - table screenshots + JSON sidecar data
    screenshots/         - page screenshots for VLM

Removed:
  - rglob("*.md") that caused duplicate indexing
  - source_summary.md indexing (file no longer generated)
  - extracted_from_pdf/marker_output/ nested duplicate scanning
"""

import csv
import json
import logging
import os
from pathlib import Path

from ..schemas.evidence import (
    EvidenceChunk,
    EvidenceState,
    FigureRef,
    FormulaRef,
    TableRef,
)
from ..utils.io_utils import read_text

logger = logging.getLogger(__name__)


class SourceIndexer:
    """Indexes source materials into structured evidence.

    Follows the pyramid Document Store architecture:
      Layer 0: Raw assets (paper_full.md, figures/, tables/, screenshots/)
      Produces: EvidenceState with chunks, figures, tables, formulas
    """

    def __init__(self, llm=None):
        """Initialize with optional LLM client for VLM annotation.

        Args:
            llm: LLMClient instance. If provided, extracted figures will be
                 annotated with VLM-generated descriptions.
        """
        self.llm = llm

    def index(self, case_dir: str | Path) -> EvidenceState:
        """Index all source materials in a case directory."""
        case_dir = Path(case_dir)
        source_dir = case_dir / "source_pack"

        chunks: list[EvidenceChunk] = []
        figures: list[FigureRef] = []
        tables: list[TableRef] = []
        formulas: list[FormulaRef] = []

        # === 1. Index text from paper_full.md (single source of truth) ===
        paper_md = source_dir / "paper_full.md"
        md_tables: list[TableRef] = []  # tables from markdown (for dedup)
        if paper_md.exists():
            marker_chunks, marker_tables, marker_formulas = self._index_marker_markdown(paper_md)
            chunks.extend(marker_chunks)
            md_tables = marker_tables  # defer adding — dedup with JSON sidecar first
            formulas.extend(marker_formulas)
            logger.info(
                "Indexed paper_full.md: %d chunks, %d tables, %d formulas",
                len(marker_chunks), len(marker_tables), len(marker_formulas),
            )
        else:
            # Fallback: index any .txt files directly in source_pack/
            for txt_path in sorted(source_dir.glob("*.txt")):
                file_chunks = self._index_text(txt_path)
                chunks.extend(file_chunks)
            logger.warning("No paper_full.md found, falling back to .txt files")

        # === 2. Index figures from source_pack/figures/ (new pyramid path) ===
        figures_dir = source_dir / "figures"
        if not figures_dir.exists():
            # Backward compat: try old path
            figures_dir = source_dir / "extracted_from_pdf" / "images"
        if figures_dir.exists():
            for img_path in sorted(figures_dir.glob("*")):
                if img_path.suffix.lower() in (
                    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
                ):
                    # Try to read metadata from JSON sidecar
                    sidecar_path = img_path.with_suffix(".json")
                    if sidecar_path.exists():
                        fig = self._index_figure_sidecar(sidecar_path, img_path, case_dir)
                        if fig:
                            figures.append(fig)
                            continue
                    # Fallback: use stem as ID (for backward compat)
                    figures.append(FigureRef(
                        figure_id=img_path.stem,
                        source_file=str(img_path.relative_to(case_dir)),
                        image_path=str(img_path),
                        caption=img_path.stem.replace("_", " "),
                    ))

        # === 3. Index tables from source_pack/tables/ (JSON sidecar files) ===
        json_tables: list[TableRef] = []
        tables_dir = source_dir / "tables"
        if tables_dir.exists():
            for json_path in sorted(tables_dir.glob("*.json")):
                tbl = self._index_table_json(json_path, case_dir)
                if tbl:
                    json_tables.append(tbl)
        # Also check legacy CSV tables
        extracted_tables_dir = source_dir / "extracted_tables"
        if extracted_tables_dir.exists():
            for csv_path in sorted(extracted_tables_dir.glob("*.csv")):
                table = self._index_csv(csv_path, case_dir)
                json_tables.append(table)

        # === 3b. Dedup: merge markdown tables with JSON sidecar tables ===
        tables.extend(self._dedup_tables(md_tables, json_tables))

        # === 4. Index screenshots from source_pack/screenshots/ ===
        screenshots_dir = source_dir / "screenshots"
        if not screenshots_dir.exists():
            # Backward compat: try old path
            screenshots_dir = source_dir / "extracted_from_pdf" / "screenshots"
        if screenshots_dir.exists():
            for ss_path in sorted(screenshots_dir.glob("*.png")):
                # Use stem directly as ID (e.g. screenshot_p1 or page_screenshot_001)
                figures.append(FigureRef(
                    figure_id=ss_path.stem,
                    source_file=str(ss_path.relative_to(case_dir)),
                    image_path=str(ss_path),
                    caption=f"Page screenshot",
                    figure_type="page_screenshot",
                ))

        # === 5. VLM annotation ===
        if self.llm and not os.environ.get("SKIP_VLM_ANNOTATION"):
            try:
                from .image_annotator import ImageAnnotator
                annotator = ImageAnnotator(self.llm)
                figures = annotator.annotate_figures(figures)
                tables = annotator.annotate_tables(tables)
            except Exception as e:
                logger.warning("VLM annotation failed, using generic descriptions: %s", e)

        # === 6. Render display formulas as PNG ===
        if formulas:
            try:
                from ..utils.formula_renderer import FormulaRenderer
                formula_dir = source_dir / "rendered_formulas"
                renderer = FormulaRenderer(formula_dir)
                formulas = renderer.render_all(formulas)
            except Exception as e:
                logger.warning("Formula rendering failed: %s", e)

        logger.info(
            "Indexed %d chunks, %d figures, %d tables, %d formulas",
            len(chunks), len(figures), len(tables), len(formulas),
        )

        return EvidenceState(
            chunks=chunks,
            figures=figures,
            tables=tables,
            formulas=formulas,
        )

    def _index_marker_markdown(
        self, path: Path
    ) -> tuple[list[EvidenceChunk], list[TableRef], list[FormulaRef]]:
        """Index a marker-produced full markdown file.

        Unlike the old _index_markdown, this method:
        - Preserves LaTeX formulas in chunk content
        - Extracts tables as TableRef objects
        - Extracts formulas as FormulaRef objects

        Returns:
            (chunks, tables, formulas)
        """
        import re as _re

        content = read_text(path)
        chunks: list[EvidenceChunk] = []
        tables: list[TableRef] = []
        formulas: list[FormulaRef] = []

        # Split by headings
        lines = content.split("\n")
        sections: list[dict] = []
        current: dict | None = None

        for line in lines:
            heading_match = _re.match(r"^(#{1,4})\s+(.+)$", line)
            if heading_match:
                if current and current["lines"]:
                    sections.append(current)
                heading_text = heading_match.group(2).strip()
                heading_text = _re.sub(r"<span[^>]*>", "", heading_text)
                heading_text = heading_text.replace("</span>", "")
                level = len(heading_match.group(1))
                current = {"heading": heading_text, "level": level, "lines": [line]}
            else:
                if current is None:
                    current = {"heading": "Preamble", "level": 0, "lines": []}
                current["lines"].append(line)

        if current and current["lines"]:
            sections.append(current)

        # Convert sections to chunks
        for i, section in enumerate(sections):
            sec_content = "\n".join(section["lines"]).strip()
            if not sec_content and section["heading"] == "Preamble":
                continue

            # Detect page references
            page_refs = _re.findall(r'id="page-(\d+)', sec_content)
            page_start = int(page_refs[0]) + 1 if page_refs else None
            page_end = int(page_refs[-1]) + 1 if page_refs else page_start

            page_ref = None
            if page_start:
                page_ref = (
                    f"p{page_start}" if page_start == page_end
                    else f"p{page_start}-{page_end}"
                )

            has_formulas = bool(
                _re.search(r"\$\$.*?\$\$", sec_content, _re.DOTALL)
                or _re.search(r"(?<!\$)\$(?!\$)[^$]+\$(?!\$)", sec_content)
            )

            chunks.append(EvidenceChunk(
                chunk_id=f"sec_{i:03d}",
                source_file=str(path.name),
                content=sec_content,
                chunk_type="text",
                page_ref=page_ref,
                metadata={
                    "heading": section["heading"],
                    "section": section["heading"],
                    "level": section["level"],
                    "page_start": page_start,
                    "page_end": page_end,
                    "has_formulas": has_formulas,
                },
            ))

        # Extract tables from the full markdown
        tbl_idx = 0
        i = 0
        md_lines = content.split("\n")
        while i < len(md_lines):
            line = md_lines[i].strip()
            if line.startswith("|") and "|" in line[1:]:
                table_lines = []
                while i < len(md_lines) and md_lines[i].strip().startswith("|"):
                    table_lines.append(md_lines[i].strip())
                    i += 1
                if len(table_lines) >= 3:
                    headers = [c.strip() for c in table_lines[0].strip("|").split("|")]
                    data_start = 1
                    if data_start < len(table_lines) and _re.match(
                        r"^\|[\s\-:|]+\|$", table_lines[data_start]
                    ):
                        data_start = 2
                    rows = []
                    for tl in table_lines[data_start:]:
                        cells = [c.strip() for c in tl.strip("|").split("|")]
                        rows.append(cells)
                    if rows:
                        content_lines = [" | ".join(headers)]
                        content_lines.append(" | ".join(["---"] * len(headers)))
                        for row in rows:
                            content_lines.append(" | ".join(row))
                        tbl_content = "\n".join(content_lines)

                        # Find caption
                        caption = ""
                        start_idx = max(0, i - len(table_lines) - 5)
                        for j in range(start_idx, i - len(table_lines)):
                            clean = _re.sub(r"<[^>]+>", "", md_lines[j])
                            cap_match = _re.match(
                                r"(?:Table)\s*\d+\s*[:.]?\s*(.*)",
                                clean.strip(), _re.IGNORECASE,
                            )
                            if cap_match:
                                caption = clean.strip()
                                break

                        tables.append(TableRef(
                            table_id=f"tbl_{tbl_idx:03d}",
                            source_file=str(path.name),
                            content=tbl_content,
                            caption=caption,
                            headers=headers,
                            row_count=len(rows),
                        ))
                        tbl_idx += 1
            else:
                i += 1

        # Extract formulas
        formula_idx = 0
        for match in _re.finditer(r"\$\$(.*?)\$\$", content, _re.DOTALL):
            latex = match.group(1).strip()
            if not latex or len(latex) < 2:
                continue
            start = max(0, match.start() - 80)
            end = min(len(content), match.end() + 80)
            context = content[start:end].replace("\n", " ").strip()
            formulas.append(FormulaRef(
                formula_id=f"formula_{formula_idx:03d}",
                latex=latex,
                display=True,
                context=context,
                source_file=str(path.name),
            ))
            formula_idx += 1

        for match in _re.finditer(r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)", content):
            latex = match.group(1).strip()
            if not latex or len(latex) < 2 or _re.match(r"^[\d\s.,]+$", latex):
                continue
            start = max(0, match.start() - 60)
            end = min(len(content), match.end() + 60)
            context = content[start:end].replace("\n", " ").strip()
            formulas.append(FormulaRef(
                formula_id=f"formula_{formula_idx:03d}",
                latex=latex,
                display=False,
                context=context,
                source_file=str(path.name),
            ))
            formula_idx += 1

        logger.info(
            "Marker markdown indexed: %d chunks, %d tables, %d formulas",
            len(chunks), len(tables), len(formulas),
        )
        return chunks, tables, formulas

    def _index_text(self, path: Path) -> list[EvidenceChunk]:
        """Index a plain text file as a single chunk."""
        content = read_text(path)
        return [EvidenceChunk(
            chunk_id=f"{path.stem}_chunk_000",
            source_file=str(path.name),
            content=content.strip(),
            chunk_type="text",
        )]

    def _index_table_json(self, json_path: Path, case_dir: Path) -> TableRef | None:
        """Index a table from its JSON sidecar file (pyramid format).

        Uses the table_id from the sidecar if present, otherwise falls
        back to the filename stem.
        """
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        rows = data.get("rows", [])
        if not rows:
            return None

        headers = [str(c).strip() if c else "" for c in rows[0]] if rows else []
        data_rows = [[str(c).strip() if c else "" for c in row] for row in rows[1:]]

        # Build pipe-delimited content
        content_lines = [" | ".join(headers)]
        content_lines.append(" | ".join(["---"] * max(len(headers), 1)))
        for row in data_rows:
            content_lines.append(" | ".join(row))
        content = "\n".join(content_lines)

        # Find corresponding PNG screenshot
        png_path = json_path.with_suffix(".png")
        image_path = str(png_path) if png_path.exists() else None

        # Use table_id from sidecar if available, else filename stem
        table_id = data.get("table_id", json_path.stem)

        return TableRef(
            table_id=table_id,
            source_file=str(json_path.relative_to(case_dir)),
            content=content,
            caption=data.get("caption", ""),
            headers=headers,
            row_count=len(data_rows),
            image_path=image_path,
            page_number=data.get("page"),
            bbox=data.get("bbox", []),
        )

    def _index_csv(self, path: Path, case_dir: Path) -> TableRef:
        """Index a CSV file as a table reference."""
        with open(path, encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        headers = rows[0] if rows else []
        content = "\n".join(",".join(row) for row in rows)

        return TableRef(
            table_id=f"table_{path.stem}",
            source_file=str(path.relative_to(case_dir)),
            content=content,
            caption=path.stem.replace("_", " "),
            headers=headers,
            row_count=len(rows) - 1,
        )

    def _index_figure_sidecar(
        self, sidecar_path: Path, img_path: Path, case_dir: Path
    ) -> FigureRef | None:
        """Index a figure from its JSON sidecar file.

        The sidecar contains caption, page, bbox, figure_type — fields that
        FigureExtractor saved during extraction.
        """
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        figure_id = data.get("figure_id", img_path.stem)
        caption = data.get("caption", "")
        page_number = data.get("page")
        figure_type = data.get("figure_type", "embedded")
        width = data.get("width")
        height = data.get("height")
        bbox = data.get("bbox", [])

        return FigureRef(
            figure_id=figure_id,
            source_file=str(img_path.relative_to(case_dir)),
            image_path=str(img_path),
            caption=caption,
            page_number=page_number,
            figure_type=figure_type,
            width=width,
            height=height,
            bbox=bbox,
        )

    def _dedup_tables(
        self, md_tables: list[TableRef], json_tables: list[TableRef]
    ) -> list[TableRef]:
        """Merge markdown tables with JSON sidecar tables, preferring JSON.

        JSON sidecar tables have image_path (screenshots), page_number,
        and caption from PDF — they are the higher-quality source.

        For each markdown table, check if a JSON sidecar table with
        similar headers exists. If so, skip the markdown version.
        """
        kept = list(json_tables)  # JSON tables always kept (have screenshots)

        deduped_count = 0
        for md_tbl in md_tables:
            is_dup = False
            for json_tbl in json_tables:
                if self._tables_similar(md_tbl, json_tbl):
                    is_dup = True
                    break
            if not is_dup:
                kept.append(md_tbl)
            else:
                deduped_count += 1

        if deduped_count:
            logger.info(
                "Table dedup: %d markdown tables matched JSON sidecars, "
                "%d unique markdown-only tables kept (total: %d)",
                deduped_count, len(md_tables) - deduped_count, len(kept),
            )
        return kept

    @staticmethod
    def _tables_similar(t1: TableRef, t2: TableRef) -> bool:
        """Check if two tables represent the same data.

        Uses two strategies:
        1. Caption matching: if both have captions containing "Table N",
           compare the table numbers.
        2. Header-word Jaccard: tokenize all headers into words and compute
           Jaccard similarity (threshold 0.35). This handles the case where
           PyMuPDF merges multi-column headers with newlines.
        """
        import re as _re

        # --- Strategy 1: Caption-based matching ---
        cap1 = (t1.caption or "").strip()
        cap2 = (t2.caption or "").strip()
        if cap1 and cap2:
            m1 = _re.search(r"Table\s+(\d+)", cap1, _re.IGNORECASE)
            m2 = _re.search(r"Table\s+(\d+)", cap2, _re.IGNORECASE)
            if m1 and m2:
                return m1.group(1) == m2.group(1)

        # --- Strategy 2: Header-word Jaccard ---
        def _header_words(headers: list[str]) -> set[str]:
            words: set[str] = set()
            for h in headers:
                for token in _re.split(r"[\s|/,;:]+", h.lower()):
                    token = token.strip("()[]{}#↑↓±")
                    if len(token) >= 2:  # skip empty / single-char noise
                        words.add(token)
            return words

        w1 = _header_words(t1.headers)
        w2 = _header_words(t2.headers)
        if not w1 or not w2:
            return False
        jaccard = len(w1 & w2) / len(w1 | w2)
        return jaccard > 0.35
