"""MarkerProcessor - high-quality PDF → Markdown extraction using marker-pdf.

Replaces PyMuPDF-based text/table extraction with marker-pdf for:
- Clean section headings via Markdown ## syntax
- Proper LaTeX formulas ($$...$$ and $...$)
- Accurate Markdown tables (| col | col |)
- Extracted figure images (_page_N_Figure_M.jpeg)

Falls back to PdfProcessor (PyMuPDF) if marker is not available.
"""

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from ..schemas.evidence import EvidenceChunk, FigureRef, FormulaRef, TableRef


# PdfExtractionResult: kept here (was in pdf_processor.py) as marker still
# returns this bundle from .process().
from dataclasses import dataclass, field


@dataclass
class PdfExtractionResult:
    """Bundle of all outputs from PDF/Marker processing."""

    chunks: list[EvidenceChunk] = field(default_factory=list)
    figures: list[FigureRef] = field(default_factory=list)
    tables: list[TableRef] = field(default_factory=list)
    screenshots: list[FigureRef] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    total_pages: int = 0

logger = logging.getLogger(__name__)


class MarkerProcessor:
    """PDF → Markdown using marker-pdf, with structured parsing.

    Produces the same PdfExtractionResult as PdfProcessor so it can
    be used as a drop-in replacement. Additionally extracts LaTeX
    formulas and preserves them in chunk content and as FormulaRef.
    """

    def __init__(self, output_dir: str | Path):
        """Initialize processor.

        Args:
            output_dir: Directory to save marker output and extracted images.
        """
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / "images"
        self.screenshots_dir = self.output_dir / "screenshots"

    def process(self, pdf_path: str | Path) -> PdfExtractionResult:
        """Full extraction pipeline using marker-pdf.

        1. Run marker_single on the PDF
        2. Parse the output Markdown into sections, tables, formulas
        3. Collect extracted images
        4. Extract metadata from Markdown + meta.json

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            PdfExtractionResult with all extracted data.
            metadata dict includes:
              - "full_markdown": complete markdown text
              - "formulas": list of FormulaRef
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        source_file = pdf_path.name
        logger.info("Processing PDF with marker-pdf: %s", source_file)

        # Create output directories
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Run marker
        md_path, meta_path, image_paths = self._run_marker(pdf_path)

        # Read markdown
        md_text = md_path.read_text(encoding="utf-8")

        # Read metadata
        meta_json = {}
        if meta_path and meta_path.exists():
            try:
                meta_json = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        # Parse components
        metadata = self._extract_metadata(md_text, meta_json, source_file)
        metadata["full_markdown"] = md_text

        chunks = self._parse_markdown_sections(md_text, source_file)
        tables = self._parse_markdown_tables(md_text, source_file)
        formulas = self._parse_formulas(md_text, source_file)
        figures = self._parse_figures(
            md_path.parent, source_file, md_text, image_paths
        )

        # Store formulas in metadata for downstream access
        metadata["formulas"] = formulas

        # Estimate total pages from meta.json
        page_stats = meta_json.get("page_stats", [])
        total_pages = len(page_stats) if page_stats else self._estimate_pages(md_text)

        # Also render page screenshots using PyMuPDF (marker doesn't do this)
        screenshots = self._render_screenshots(pdf_path, source_file, total_pages)

        result = PdfExtractionResult(
            chunks=chunks,
            figures=figures,
            tables=tables,
            screenshots=screenshots,
            metadata=metadata,
            total_pages=total_pages,
        )

        logger.info(
            "Marker extraction complete: %d chunks, %d figures, %d tables, "
            "%d formulas, %d screenshots from %d pages",
            len(chunks), len(figures), len(tables),
            len(formulas), len(screenshots), total_pages,
        )
        return result

    # ------------------------------------------------------------------
    # Marker execution
    # ------------------------------------------------------------------

    def _run_marker(self, pdf_path: Path) -> tuple[Path, Path | None, list[Path]]:
        """Execute marker_single on the PDF.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            (md_path, meta_path, image_paths) — paths to marker output files.

        Raises:
            RuntimeError: If marker_single is not found or fails.
        """
        # marker writes to output_dir/{pdf_stem}/
        marker_out_base = self.output_dir / "marker_output"
        marker_out_base.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                ["marker_single", str(pdf_path), "--output_dir", str(marker_out_base)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "marker_single command not found. Install marker-pdf: pip install marker-pdf"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("marker_single timed out after 120 seconds")

        if result.returncode != 0:
            logger.error("marker_single stderr: %s", result.stderr[:500])
            raise RuntimeError(f"marker_single failed with code {result.returncode}")

        # Find the output directory (marker creates a subdirectory named after the PDF)
        stem = pdf_path.stem
        marker_dir = marker_out_base / stem

        if not marker_dir.exists():
            # marker may use slightly different naming — search for the output
            candidates = list(marker_out_base.glob("*"))
            dirs = [c for c in candidates if c.is_dir()]
            if dirs:
                marker_dir = dirs[0]
            else:
                raise RuntimeError(
                    f"marker output directory not found in {marker_out_base}"
                )

        # Find markdown file
        md_files = list(marker_dir.glob("*.md"))
        if not md_files:
            raise RuntimeError(f"No .md file found in marker output: {marker_dir}")
        md_path = md_files[0]

        # Find meta.json
        meta_files = list(marker_dir.glob("*_meta.json"))
        meta_path = meta_files[0] if meta_files else None

        # Find extracted images
        image_paths = sorted(
            p for p in marker_dir.iterdir()
            if p.suffix.lower() in (".jpeg", ".jpg", ".png", ".gif", ".bmp")
        )

        # Copy images to our images_dir for downstream use
        for img in image_paths:
            dest = self.images_dir / img.name
            if not dest.exists():
                shutil.copy2(img, dest)

        logger.info(
            "marker output: %s (%d images, meta=%s)",
            md_path.name, len(image_paths), "yes" if meta_path else "no",
        )

        return md_path, meta_path, image_paths

    # ------------------------------------------------------------------
    # Markdown parsing
    # ------------------------------------------------------------------

    def _parse_markdown_sections(
        self, md_text: str, source_file: str
    ) -> list[EvidenceChunk]:
        """Split markdown by headings into EvidenceChunk list.

        Preserves LaTeX formulas ($$...$$ and $...$) in chunk content.
        Each section becomes one EvidenceChunk.
        """
        # Split by heading lines (# to ####)
        # We keep the heading as part of the section
        lines = md_text.split("\n")
        sections: list[dict] = []
        current: dict | None = None

        for line in lines:
            # Detect heading: starts with # (1-4 levels)
            heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
            if heading_match:
                if current and current["lines"]:
                    sections.append(current)
                heading_text = heading_match.group(2).strip()
                # Clean HTML spans from heading
                heading_text = re.sub(r"<span[^>]*>", "", heading_text)
                heading_text = heading_text.replace("</span>", "")
                level = len(heading_match.group(1))
                current = {
                    "heading": heading_text,
                    "level": level,
                    "lines": [line],
                }
            else:
                if current is None:
                    current = {
                        "heading": "Preamble",
                        "level": 0,
                        "lines": [],
                    }
                current["lines"].append(line)

        if current and current["lines"]:
            sections.append(current)

        # Convert to EvidenceChunks
        chunks = []
        for i, section in enumerate(sections):
            content = "\n".join(section["lines"]).strip()
            if not content and section["heading"] == "Preamble":
                continue

            # Detect page references from <span id="page-N-..."> markers
            page_refs = re.findall(r'id="page-(\d+)', content)
            page_start = int(page_refs[0]) + 1 if page_refs else None
            page_end = int(page_refs[-1]) + 1 if page_refs else page_start

            page_ref = None
            if page_start:
                page_ref = (
                    f"p{page_start}" if page_start == page_end
                    else f"p{page_start}-{page_end}"
                )

            # Check if section contains formulas
            has_formulas = bool(
                re.search(r"\$\$.*?\$\$", content, re.DOTALL)
                or re.search(r"\$[^$]+\$", content)
            )

            chunks.append(EvidenceChunk(
                chunk_id=f"sec_{i:03d}",
                source_file=source_file,
                content=content,
                chunk_type="text",
                page_ref=page_ref,
                metadata={
                    "heading": section["heading"],
                    "level": section["level"],
                    "page_start": page_start,
                    "page_end": page_end,
                    "has_formulas": has_formulas,
                },
            ))

        logger.info("Parsed %d sections from marker markdown", len(chunks))
        return chunks

    def _parse_markdown_tables(
        self, md_text: str, source_file: str
    ) -> list[TableRef]:
        """Extract markdown tables from the text.

        Detects blocks of consecutive lines starting with | and
        converts them to pipe-delimited TableRef content.
        """
        tables: list[TableRef] = []
        lines = md_text.split("\n")
        i = 0
        tbl_idx = 0

        while i < len(lines):
            line = lines[i].strip()

            # Detect table start: line starts with |
            if line.startswith("|") and "|" in line[1:]:
                table_lines = []

                # Collect all consecutive | lines
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i].strip())
                    i += 1

                if len(table_lines) < 3:
                    # Need header + separator + at least 1 data row
                    continue

                # Parse header (first line)
                header_line = table_lines[0]
                headers = [
                    c.strip() for c in header_line.strip("|").split("|")
                ]

                # Skip separator line (second line with ---)
                data_start = 1
                if data_start < len(table_lines) and re.match(
                    r"^\|[\s\-:|]+\|$", table_lines[data_start]
                ):
                    data_start = 2

                # Parse data rows
                rows = []
                for tl in table_lines[data_start:]:
                    cells = [c.strip() for c in tl.strip("|").split("|")]
                    rows.append(cells)

                if not rows:
                    continue

                # Build pipe-delimited content (same as PdfProcessor format)
                content_lines = [" | ".join(headers)]
                content_lines.append(" | ".join(["---"] * len(headers)))
                for row in rows:
                    content_lines.append(" | ".join(row))
                content = "\n".join(content_lines)

                # Try to find table caption (look back a few lines)
                caption = self._find_table_caption_in_md(
                    md_text, lines, table_lines[0], tbl_idx
                )

                tables.append(TableRef(
                    table_id=f"tbl_{tbl_idx:03d}",
                    source_file=source_file,
                    content=content,
                    caption=caption,
                    headers=headers,
                    row_count=len(rows),
                ))
                tbl_idx += 1
            else:
                i += 1

        logger.info("Parsed %d tables from marker markdown", len(tables))
        return tables

    def _find_table_caption_in_md(
        self, md_text: str, lines: list[str], first_table_line: str, tbl_idx: int
    ) -> str:
        """Find a table caption near a table in the markdown."""
        # Look for "Table N:" before the table
        try:
            table_line_idx = lines.index(first_table_line)
        except ValueError:
            # The line might appear multiple times; search backwards
            table_line_idx = -1
            for j, l in enumerate(lines):
                if l.strip() == first_table_line:
                    table_line_idx = j

        if table_line_idx < 0:
            return ""

        # Search backwards up to 5 lines for "Table N:" pattern
        for j in range(max(0, table_line_idx - 5), table_line_idx):
            line = lines[j].strip()
            # Match "Table 1: ..." or "<span ...>Table 1: ..."
            clean = re.sub(r"<[^>]+>", "", line)
            match = re.match(r"(?:Table)\s*\d+\s*[:.]?\s*(.*)", clean, re.IGNORECASE)
            if match:
                return clean.strip()

        return ""

    def _parse_formulas(
        self, md_text: str, source_file: str
    ) -> list[FormulaRef]:
        """Extract LaTeX formulas from markdown.

        Detects:
        - Display formulas: $$ ... $$
        - Inline formulas: $ ... $ (non-greedy, excluding $$)
        """
        formulas: list[FormulaRef] = []
        formula_idx = 0

        # Extract display formulas ($$...$$)
        for match in re.finditer(r"\$\$(.*?)\$\$", md_text, re.DOTALL):
            latex = match.group(1).strip()
            if not latex or len(latex) < 2:
                continue

            # Get surrounding context (50 chars before and after)
            start = max(0, match.start() - 80)
            end = min(len(md_text), match.end() + 80)
            context = md_text[start:end].replace("\n", " ").strip()

            formulas.append(FormulaRef(
                formula_id=f"formula_{formula_idx:03d}",
                latex=latex,
                display=True,
                context=context,
                source_file=source_file,
            ))
            formula_idx += 1

        # Extract inline formulas ($...$), excluding display math ($$)
        # Use negative lookbehind/lookahead for $$
        for match in re.finditer(r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)", md_text):
            latex = match.group(1).strip()
            if not latex or len(latex) < 2:
                continue
            # Skip if it's just numbers or plain text
            if re.match(r"^[\d\s.,]+$", latex):
                continue

            start = max(0, match.start() - 60)
            end = min(len(md_text), match.end() + 60)
            context = md_text[start:end].replace("\n", " ").strip()

            formulas.append(FormulaRef(
                formula_id=f"formula_{formula_idx:03d}",
                latex=latex,
                display=False,
                context=context,
                source_file=source_file,
            ))
            formula_idx += 1

        logger.info(
            "Parsed %d formulas (%d display, %d inline)",
            len(formulas),
            sum(1 for f in formulas if f.display),
            sum(1 for f in formulas if not f.display),
        )
        return formulas

    def _parse_figures(
        self,
        marker_dir: Path,
        source_file: str,
        md_text: str,
        image_paths: list[Path],
    ) -> list[FigureRef]:
        """Parse marker's extracted images into FigureRef list.

        marker outputs images as _page_N_Figure_M.jpeg.
        We match them with captions in the markdown.
        """
        figures: list[FigureRef] = []

        # Build caption map from markdown: "Figure N: description"
        caption_map: dict[str, str] = {}
        for match in re.finditer(
            r"(?:Figure|Fig\.?)\s*(\d+)\s*[:.]?\s*(.*?)(?:\n|$)",
            md_text,
            re.IGNORECASE,
        ):
            fig_num = match.group(1)
            caption = match.group(0).strip()
            caption_map[fig_num] = caption

        for img_path in image_paths:
            # Parse page number from filename: _page_N_Figure_M.jpeg
            page_match = re.search(r"_page_(\d+)_", img_path.name)
            page_num = int(page_match.group(1)) if page_match else None

            # Try to match with a figure caption
            caption = ""
            for fig_num, cap in caption_map.items():
                # Heuristic: if this image reference appears near the caption in md
                if img_path.name in md_text:
                    # Find the image reference and look for nearby caption
                    img_ref_idx = md_text.index(img_path.name)
                    cap_idx = md_text.find(f"Figure {fig_num}")
                    if cap_idx >= 0 and abs(img_ref_idx - cap_idx) < 500:
                        caption = cap
                        break

            if not caption:
                # Fallback: use filename-based description
                caption = f"Figure from page {page_num}" if page_num else ""

            # Get image dimensions
            width, height = 0, 0
            try:
                import struct
                fname = str(img_path).lower()
                if fname.endswith(".png"):
                    with open(str(img_path), "rb") as f:
                        f.read(16)
                        d = f.read(8)
                        width = struct.unpack(">I", d[0:4])[0]
                        height = struct.unpack(">I", d[4:8])[0]
                elif fname.endswith((".jpg", ".jpeg")):
                    with open(str(img_path), "rb") as f:
                        f.read(2)
                        while True:
                            marker = f.read(2)
                            if not marker or marker[0] != 0xFF:
                                break
                            if marker[1] in (0xC0, 0xC2):
                                f.read(3)
                                height = struct.unpack(">H", f.read(2))[0]
                                width = struct.unpack(">H", f.read(2))[0]
                                break
                            else:
                                seg_len = struct.unpack(">H", f.read(2))[0]
                                f.read(seg_len - 2)
            except Exception:
                pass

            dest_path = self.images_dir / img_path.name
            figures.append(FigureRef(
                figure_id=f"fig_{len(figures):03d}",
                source_file=source_file,
                image_path=str(dest_path),
                caption=caption,
                description=caption or f"Figure from page {page_num}",
                page_number=page_num,
                width=width,
                height=height,
                figure_type="embedded",
            ))

        logger.info("Parsed %d figures from marker output", len(figures))
        return figures

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    def _extract_metadata(
        self, md_text: str, meta_json: dict, source_file: str
    ) -> dict:
        """Extract metadata from markdown and meta.json.

        Uses:
        - First # heading as title
        - Text under ### Abstract as abstract
        - meta.json table_of_contents for section listing
        """
        metadata: dict = {"source_file": source_file}

        # Title: first top-level heading
        title_match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
            # Clean HTML spans
            title = re.sub(r"<[^>]+>", "", title).strip()
            metadata["title"] = title
        else:
            metadata["title"] = "Untitled"

        # Abstract: text under "Abstract" heading
        abstract_match = re.search(
            r"#{1,3}\s+Abstract\s*\n(.*?)(?=\n#{1,3}\s|\Z)",
            md_text,
            re.IGNORECASE | re.DOTALL,
        )
        if abstract_match:
            abstract = abstract_match.group(1).strip()
            # Clean up footnote markers and HTML
            abstract = re.sub(r"<[^>]+>", "", abstract)
            abstract = re.sub(r"\s+", " ", abstract).strip()
            metadata["abstract"] = abstract

        # Authors: try to extract from text between title and abstract
        if title_match and abstract_match:
            between = md_text[title_match.end():abstract_match.start()].strip()
            # Clean up — author names are usually separated by newlines
            author_lines = [
                l.strip() for l in between.split("\n")
                if l.strip() and not l.strip().startswith("#")
                and not l.strip().startswith("<")
                and len(l.strip()) > 2
            ]
            if author_lines:
                metadata["author"] = "; ".join(author_lines[:5])

        # TOC from meta.json
        toc = meta_json.get("table_of_contents", [])
        if toc:
            metadata["toc"] = [
                {"title": entry.get("title", ""), "page": entry.get("page_id", 0)}
                for entry in toc
            ]

        return metadata

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_pages(md_text: str) -> int:
        """Estimate total pages from page markers in markdown."""
        pages = re.findall(r'id="page-(\d+)', md_text)
        if pages:
            return max(int(p) for p in pages) + 1
        # Rough estimate: ~3000 chars per page
        return max(1, len(md_text) // 3000)

    def _render_screenshots(
        self, pdf_path: Path, source_file: str, total_pages: int
    ) -> list[FigureRef]:
        """Render page screenshots using PyMuPDF.

        marker doesn't produce page screenshots, so we use fitz for this.
        """
        try:
            import fitz
        except ImportError:
            logger.warning("PyMuPDF not available, skipping page screenshots")
            return []

        screenshots: list[FigureRef] = []
        doc = fitz.open(str(pdf_path))

        # Render key pages: first, last, and pages with figures/tables
        key_pages = {0}  # always include first page
        if len(doc) > 1:
            key_pages.add(len(doc) - 1)
        # Add pages with figures/tables (check first 15 pages)
        for page_num in range(min(len(doc), 15)):
            page = doc[page_num]
            text = page.get_text()
            if re.search(r"(?:Figure|Fig\.?|Table)\s+\d+", text, re.IGNORECASE):
                key_pages.add(page_num)

        for page_num in sorted(key_pages):
            if page_num >= len(doc):
                continue
            try:
                page = doc[page_num]
                filename = f"page_screenshot_{page_num + 1:03d}.png"
                out_path = self.screenshots_dir / filename
                pix = page.get_pixmap(dpi=200)
                pix.save(str(out_path))

                screenshots.append(FigureRef(
                    figure_id=f"screenshot_page{page_num + 1}",
                    source_file=source_file,
                    image_path=str(out_path),
                    caption=f"Page {page_num + 1} screenshot",
                    description=f"Full page screenshot of page {page_num + 1}",
                    page_number=page_num + 1,
                    width=pix.width,
                    height=pix.height,
                    figure_type="page_screenshot",
                ))
            except Exception as e:
                logger.warning("Screenshot failed for page %d: %s", page_num + 1, e)

        doc.close()
        logger.info("Rendered %d page screenshots", len(screenshots))
        return screenshots


def is_marker_available() -> bool:
    """Check if marker_single command is available."""
    return shutil.which("marker_single") is not None
