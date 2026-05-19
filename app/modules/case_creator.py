"""CaseCreator - auto-create case directory from a single PDF file.

New pyramid directory structure:
  cases/{case_id}/
    task_brief.md          - auto-generated from PDF metadata
    constraints.json       - from arguments
    source_pack/
      {original_pdf}       - copy of the input PDF
      paper_full.md        - full markdown from marker-pdf (text source of truth)
      figures/             - extracted figure images (Method C: 3-layer PyMuPDF)
      tables/              - table screenshots + JSON sidecar data
      screenshots/         - page screenshots for VLM

Removed:
  - source_summary.md     (replaced by direct paper_full.md consumption)
  - extracted_from_pdf/   (flattened into figures/, tables/, screenshots/)
"""

import json
import logging
import re
import shutil
from pathlib import Path

from .figure_extractor import FigureExtractor

logger = logging.getLogger(__name__)


class CaseCreator:
    """Create a case directory from a PDF paper."""

    def create_from_pdf(
        self,
        pdf_path: str | Path,
        case_id: str | None = None,
        cases_dir: str | Path = "cases",
        deck_type: str = "conference_talk",
        audience: str = "researchers",
        page_budget: list[int] | None = None,
        max_bullets_per_slide: int = 5,
        preferred_visual_forms: list[str] | None = None,
    ) -> str:
        """Create a complete case directory from a PDF paper.

        Args:
            pdf_path: Path to the PDF paper.
            case_id: Case identifier. Auto-generated from filename if None.
            cases_dir: Base directory for all cases.
            deck_type: Type of presentation.
            audience: Target audience description.
            page_budget: [min_slides, max_slides]. Default [8, 12].
            max_bullets_per_slide: Maximum bullet points per slide.
            preferred_visual_forms: Preferred visual forms.

        Returns:
            The case_id string.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        cases_dir = Path(cases_dir)
        page_budget = page_budget or [10, 13]
        preferred_visual_forms = preferred_visual_forms or [
            "chart", "table", "image", "metric_grid"
        ]

        # Generate case_id from filename if not provided
        if not case_id:
            case_id = self._generate_case_id(pdf_path)

        case_dir = cases_dir / case_id
        source_dir = case_dir / "source_pack"

        # Create directory structure
        source_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Creating case '%s' from %s", case_id, pdf_path.name)

        # Copy PDF to source_pack
        pdf_dest = source_dir / pdf_path.name
        if not pdf_dest.exists():
            shutil.copy2(pdf_path, pdf_dest)
            logger.info("Copied PDF to %s", pdf_dest)

        # === Step 1: Text extraction via marker-pdf ===
        paper_md_path = source_dir / "paper_full.md"
        metadata = {}
        marker_used = False

        try:
            from .marker_processor import MarkerProcessor, is_marker_available
            if is_marker_available():
                # Use marker for text/markdown extraction only
                # We create a temp dir for marker output, then take only what we need
                marker_temp_dir = source_dir / "_marker_temp"
                processor = MarkerProcessor(marker_temp_dir)
                result = processor.process(pdf_path)
                marker_used = True

                # Save the full markdown
                full_md = result.metadata.get("full_markdown", "")
                if full_md and len(full_md.strip()) > 100:
                    paper_md_path.write_text(full_md, encoding="utf-8")
                    logger.info("Saved full marker markdown to %s", paper_md_path)
                else:
                    # Marker extracted no/minimal text — PDF likely has rasterized text.
                    # Fallback: OCR via PyMuPDF + Tesseract
                    logger.warning(
                        "Marker extracted little text (%d chars), "
                        "trying OCR fallback via PyMuPDF+Tesseract",
                        len(full_md.strip()) if full_md else 0,
                    )
                    try:
                        import fitz as _fitz
                        _doc = _fitz.open(str(pdf_path))
                        ocr_pages = []
                        for _pn, _pg in enumerate(_doc):
                            try:
                                _tp = _pg.get_textpage_ocr(
                                    language="eng", dpi=150, full=True,
                                )
                                _txt = _pg.get_text(textpage=_tp).strip()
                            except Exception:
                                _txt = ""
                            if _txt:
                                ocr_pages.append(f"## Page {_pn + 1}\n\n{_txt}")
                        _doc.close()
                        if ocr_pages:
                            paper_md_path.write_text(
                                "\n\n".join(ocr_pages), encoding="utf-8",
                            )
                            logger.info(
                                "OCR fallback: extracted %d pages to %s",
                                len(ocr_pages), paper_md_path,
                            )
                    except Exception as _e:
                        logger.warning("OCR fallback failed: %s", _e)

                metadata = result.metadata
                metadata.pop("full_markdown", None)  # don't keep in memory
                metadata["total_pages"] = result.total_pages

                # Clean up marker temp directory (we only need paper_full.md)
                if marker_temp_dir.exists():
                    shutil.rmtree(marker_temp_dir, ignore_errors=True)

                logger.info("Used marker-pdf for text extraction")
            else:
                logger.info("marker_single not found, extracting metadata via PyMuPDF")
                metadata = self._extract_basic_metadata(pdf_path)
                # Fallback: extract full text via PyMuPDF so SourceStore can build
                if not paper_md_path.exists():
                    try:
                        import fitz
                        doc = fitz.open(str(pdf_path))
                        pages_text = []
                        for page_num, page in enumerate(doc):
                            text = page.get_text()
                            if text.strip():
                                pages_text.append(f"## Page {page_num + 1}\n\n{text}")
                        doc.close()
                        if pages_text:
                            paper_md_path.write_text(
                                "\n\n".join(pages_text), encoding="utf-8"
                            )
                            logger.info(
                                "PyMuPDF fallback: extracted %d pages to %s",
                                len(pages_text), paper_md_path,
                            )
                    except Exception as e2:
                        logger.warning("PyMuPDF text extraction failed: %s", e2)
        except Exception as e:
            logger.warning("marker-pdf failed (%s), using fallback extraction", e)
            metadata = self._extract_basic_metadata(pdf_path)
            # Fallback: extract full text via PyMuPDF (plain text first, then OCR)
            if not paper_md_path.exists():
                try:
                    import fitz
                    doc = fitz.open(str(pdf_path))
                    pages_text = []
                    for page_num, page in enumerate(doc):
                        text = page.get_text()
                        if text.strip():
                            pages_text.append(f"## Page {page_num + 1}\n\n{text}")
                    doc.close()
                    if pages_text:
                        paper_md_path.write_text(
                            "\n\n".join(pages_text), encoding="utf-8"
                        )
                        logger.info(
                            "PyMuPDF fallback: extracted %d pages to %s",
                            len(pages_text), paper_md_path,
                        )
                    else:
                        # No text extracted — try OCR
                        logger.info("PyMuPDF found no text, trying OCR...")
                        doc = fitz.open(str(pdf_path))
                        ocr_pages = []
                        for pn, pg in enumerate(doc):
                            try:
                                tp = pg.get_textpage_ocr(
                                    language="eng", dpi=150, full=True,
                                )
                                txt = pg.get_text(textpage=tp).strip()
                            except Exception:
                                txt = ""
                            if txt:
                                ocr_pages.append(f"## Page {pn + 1}\n\n{txt}")
                        doc.close()
                        if ocr_pages:
                            paper_md_path.write_text(
                                "\n\n".join(ocr_pages), encoding="utf-8",
                            )
                            logger.info(
                                "OCR fallback: extracted %d pages to %s",
                                len(ocr_pages), paper_md_path,
                            )
                except Exception as e2:
                    logger.warning("Fallback text extraction failed: %s", e2)

        # === Step 2: Figure/Table/Screenshot extraction via FigureExtractor (Method C) ===
        extractor = FigureExtractor(source_dir)
        figures, tables, screenshots = extractor.extract(pdf_path)
        logger.info(
            "FigureExtractor: %d figures, %d tables, %d screenshots",
            len(figures), len(tables), len(screenshots),
        )

        # === Step 3: Generate task_brief.md ===
        task_brief = self._generate_task_brief(
            metadata, figures, tables,
            deck_type, audience, page_budget,
        )
        task_brief_path = case_dir / "task_brief.md"
        task_brief_path.write_text(task_brief, encoding="utf-8")
        logger.info("Generated task brief: %s", task_brief_path)

        # === Step 4: Generate constraints.json ===
        constraints = self._generate_constraints(
            case_id, deck_type, audience, page_budget,
            max_bullets_per_slide, preferred_visual_forms,
        )
        constraints_path = case_dir / "constraints.json"
        constraints_path.write_text(
            json.dumps(constraints, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Generated constraints: %s", constraints_path)

        logger.info(
            "Case '%s' created: %d figures, %d tables, %d screenshots",
            case_id, len(figures), len(tables), len(screenshots),
        )

        return case_id

    def _generate_case_id(self, pdf_path: Path) -> str:
        """Generate a case ID from PDF filename."""
        stem = pdf_path.stem
        clean = re.sub(r"\s*\(\d+\)\s*", "", stem)
        clean = re.sub(r"[^\w.-]", "_", clean)
        clean = re.sub(r"_+", "_", clean).strip("_")
        return f"pdf_{clean}"

    def _extract_basic_metadata(self, pdf_path: Path) -> dict:
        """Extract basic metadata from PDF using PyMuPDF (no marker needed)."""
        import fitz

        doc = fitz.open(str(pdf_path))
        meta = doc.metadata or {}

        result = {
            "title": meta.get("title", ""),
            "author": meta.get("author", ""),
            "source_file": pdf_path.name,
            "total_pages": len(doc),
        }

        # Extract title from largest font on first page
        if len(doc) > 0:
            page = doc[0]
            blocks = page.get_text("dict", flags=11)["blocks"]
            max_font_size = 0
            title_text = ""
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        if span["size"] > max_font_size:
                            max_font_size = span["size"]
                            title_text = span["text"].strip()
                        elif span["size"] == max_font_size and title_text:
                            title_text += " " + span["text"].strip()
            if title_text and len(title_text) > len(result["title"]):
                result["title"] = title_text.strip()

        # Extract abstract
        full_text = ""
        for i in range(min(2, len(doc))):
            full_text += doc[i].get_text() + "\n"
        abstract_pattern = re.compile(
            r"(?:^|\n)\s*Abstract\s*\n(.*?)(?:\n\s*(?:1\.?\s+Introduction|Keywords|Index Terms)|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        match = abstract_pattern.search(full_text)
        if match:
            abstract = re.sub(r"\s+", " ", match.group(1).strip())
            result["abstract"] = abstract

        doc.close()
        return result

    def _generate_task_brief(
        self,
        metadata: dict,
        figures: list,
        tables: list,
        deck_type: str,
        audience: str,
        page_budget: list[int],
    ) -> str:
        """Generate task_brief.md from metadata and extracted assets."""
        title = metadata.get("title", "Untitled Paper")
        abstract = metadata.get("abstract", "")
        author = metadata.get("author", "")
        total_pages = metadata.get("total_pages", 0)

        # Figure/table info for task brief
        figures_info = ""
        if figures:
            content_figures = [f for f in figures if getattr(f, 'figure_type', '') != 'page_screenshot']
            if content_figures:
                figures_info = (
                    f"\n## Available Figures\n"
                    f"{len(content_figures)} figures extracted from the paper. "
                    f"Use these when visual content is needed for slides.\n"
                )
                for fig in content_figures[:10]:
                    caption_text = f" - {fig.caption}" if fig.caption else ""
                    page_text = f" (page {fig.page_number})" if fig.page_number else ""
                    figures_info += f"- {fig.figure_id}{page_text}{caption_text}\n"
                if len(content_figures) > 10:
                    figures_info += f"- ... and {len(content_figures) - 10} more\n"

        tables_info = ""
        if tables:
            tables_info = (
                f"\n## Available Tables\n"
                f"{len(tables)} tables extracted from the paper.\n"
            )
            for tbl in tables[:10]:
                caption_text = f" - {tbl.caption}" if tbl.caption else ""
                tables_info += f"- {tbl.table_id} ({tbl.row_count} rows){caption_text}\n"

        brief = f"""# Task Brief: {title}

## Objective
Create a {deck_type.replace('_', ' ')} presentation summarizing the paper "{title}" for a {audience} audience.

## Paper Information
- **Title**: {title}
- **Authors**: {author if author else 'See paper'}
- **Total Pages**: {total_pages}

## Abstract
{abstract if abstract else 'See source paper for abstract.'}

## Audience
{audience}

## Required Coverage Areas
The deck should substantively cover these thematic areas (not necessarily one slide per area):
- Problem context and motivation (Introduction, Background)
- Technical approach and methodology (core method sections)
- Key experimental results with quantitative evidence
- Comparison with baselines or prior work
- Limitations, conclusions, and future directions

Note: The deck has a limited slide budget. Sections may be merged or covered
within broader thematic slides. Evaluate substantive coverage of each area,
not 1:1 section-to-slide mapping.

## Must-Cover Points
- Paper's main contribution and key results
- Methodology overview with key design choices
- Key experimental findings with quantitative results
- Comparison with prior work / baselines
- Limitations acknowledged by the authors
- Conclusions and implications

## Must-Avoid
- Unsupported claims not in the original paper
- Marketing language
- Omitting negative results or limitations
- Plagiarizing text verbatim without paraphrasing

## Page Budget
{page_budget[0]}-{page_budget[1]} slides
{figures_info}{tables_info}
## Constraints
- Editable PPTX output required
- Use figures from the paper where appropriate
- No more than 5 bullet points per slide
- Include slide numbers
"""
        return brief.strip() + "\n"

    def _generate_constraints(
        self,
        case_id: str,
        deck_type: str,
        audience: str,
        page_budget: list[int],
        max_bullets_per_slide: int,
        preferred_visual_forms: list[str],
    ) -> dict:
        """Generate constraints.json."""
        return {
            "case_id": case_id,
            "deck_type": deck_type,
            "audience": audience,
            "page_budget": page_budget,
            "editable_required": True,
            "max_bullets_per_slide": max_bullets_per_slide,
            "preferred_visual_forms": preferred_visual_forms,
            "font_constraints": {
                "min_body_pt": 18,
                "min_label_pt": 14,
            },
        }
