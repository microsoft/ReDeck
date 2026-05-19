"""CaseLoader - loads a case directory into CaseState."""

import json
import logging
from pathlib import Path

from ..schemas.case_state import CaseState
from ..schemas.evidence import EvidenceState, EvidenceChunk, FigureRef, TableRef
from ..schemas.intent import IntentState
from ..utils.io_utils import read_json, read_text

logger = logging.getLogger(__name__)


class CaseLoader:
    """Loads a case from disk into structured state."""

    def __init__(self, cases_dir: str | Path = "cases"):
        self.cases_dir = Path(cases_dir)

    def load(self, case_id: str) -> CaseState:
        """Load a case by ID."""
        case_dir = self.cases_dir / case_id
        if not case_dir.exists():
            raise FileNotFoundError(f"Case directory not found: {case_dir}")

        # Load task brief
        brief_path = case_dir / "task_brief.md"
        task_brief = read_text(brief_path) if brief_path.exists() else ""

        # Load constraints
        constraints_path = case_dir / "constraints.json"
        constraints = read_json(constraints_path) if constraints_path.exists() else {}

        # Build IntentState from constraints
        intent = IntentState(
            case_id=case_id,
            deck_type=constraints.get("deck_type", "presentation"),
            audience=constraints.get("audience", "general"),
            page_budget=constraints.get("page_budget", [15, 20]),
            must_cover=self._extract_must_cover(task_brief),
            must_avoid=self._extract_must_avoid(task_brief),
            editable_required=constraints.get("editable_required", True),
            additional_constraints=constraints,
        )

        # Load revision cards if present
        revision_cards = []
        rev_dir = case_dir / "revision_cards"
        if rev_dir.exists():
            for f in sorted(rev_dir.glob("*.json")):
                revision_cards.append(read_json(f))

        logger.info("Loaded case %s from %s", case_id, case_dir)

        # Build evidence from source_pack if available
        evidence = self._load_evidence(case_dir)

        return CaseState(
            case_id=case_id,
            case_dir=str(case_dir),
            intent=intent,
            evidence=evidence,
            task_brief=task_brief,
            constraints=constraints,
            revision_cards=revision_cards,
        )

    def _load_evidence(self, case_dir: Path) -> EvidenceState:
        """Build EvidenceState from source_pack data.

        Populates chunks from atomic_blocks and tables from table_data
        in source_store.json, falling back to paper_full.md and tables/*.json.
        """
        chunks: list[EvidenceChunk] = []
        tables: list[TableRef] = []

        source_pack = case_dir / "source_pack"
        if not source_pack.exists():
            return EvidenceState()

        # Try source_store.json first (richest data)
        store_path = source_pack / "source_store.json"
        if store_path.exists():
            try:
                store = json.loads(store_path.read_text(errors="replace"))

                # Build chunks from atomic_blocks
                for block in store.get("atomic_blocks", []):
                    text = block.get("text", "")
                    if not text or len(text.strip()) < 10:
                        continue
                    chunks.append(EvidenceChunk(
                        chunk_id=block.get("block_id", f"blk_{len(chunks)}"),
                        source_file="source_store.json",
                        content=text,
                        chunk_type=block.get("type", "text"),
                        page_ref=str(block.get("page", "")),
                        metadata={
                            k: v for k, v in block.items()
                            if k not in ("text", "block_id", "type", "page")
                            and v is not None
                        },
                    ))

                # Build tables from table_data
                for tbl in store.get("table_data", []):
                    content = tbl.get("rows_or_markdown", "")
                    caption = tbl.get("caption", "")
                    if not content and not caption:
                        continue
                    # Extract headers from markdown table
                    headers = []
                    if content and "|" in content:
                        first_row = content.strip().split("\n")[0]
                        headers = [
                            h.strip()
                            for h in first_row.split("|")
                            if h.strip() and not set(h.strip()) <= {"-", "|", " "}
                        ]
                    tables.append(TableRef(
                        table_id=tbl.get("table_id", f"tbl_{len(tables)}"),
                        source_file="source_store.json",
                        content=content,
                        caption=caption,
                        description=tbl.get("summary", "") or "",
                        headers=headers,
                        row_count=content.count("\n") if content else 0,
                        page_number=tbl.get("page"),
                    ))

                logger.info(
                    "Loaded evidence from source_store.json: "
                    "%d chunks, %d tables",
                    len(chunks), len(tables),
                )
            except Exception as e:
                logger.warning("Failed to parse source_store.json: %s", e)

        # Fallback: build chunks from paper_full.md if no chunks yet
        if not chunks:
            paper_path = source_pack / "paper_full.md"
            if paper_path.exists():
                try:
                    paper_text = paper_path.read_text(errors="replace")
                    # Split into ~500-char chunks by paragraphs
                    paragraphs = paper_text.split("\n\n")
                    current_chunk = ""
                    for para in paragraphs:
                        if len(current_chunk) + len(para) > 500 and current_chunk:
                            chunks.append(EvidenceChunk(
                                chunk_id=f"paper_chunk_{len(chunks)}",
                                source_file="paper_full.md",
                                content=current_chunk.strip(),
                                chunk_type="text",
                                metadata={},
                            ))
                            current_chunk = para
                        else:
                            current_chunk += "\n\n" + para if current_chunk else para
                    if current_chunk.strip():
                        chunks.append(EvidenceChunk(
                            chunk_id=f"paper_chunk_{len(chunks)}",
                            source_file="paper_full.md",
                            content=current_chunk.strip(),
                            chunk_type="text",
                            metadata={},
                        ))
                    logger.info(
                        "Loaded %d chunks from paper_full.md (fallback)",
                        len(chunks),
                    )
                except Exception as e:
                    logger.warning("Failed to read paper_full.md: %s", e)

        # Fallback: build tables from tables/*.json if no tables yet
        if not tables:
            tables_dir = source_pack / "tables"
            if tables_dir.exists():
                for tbl_path in sorted(tables_dir.glob("*.json")):
                    try:
                        tbl_data = json.loads(tbl_path.read_text())
                        content = ""
                        rows = tbl_data.get("rows", [])
                        if rows:
                            content = "\n".join(
                                " | ".join(str(c) for c in row)
                                for row in rows
                            )
                        tables.append(TableRef(
                            table_id=tbl_data.get("table_id", tbl_path.stem),
                            source_file=tbl_path.name,
                            content=content,
                            caption=tbl_data.get("caption", ""),
                            description="",
                            headers=rows[0] if rows else [],
                            row_count=len(rows),
                            page_number=tbl_data.get("page"),
                        ))
                    except Exception as e:
                        logger.warning("Failed to parse %s: %s", tbl_path, e)
                if tables:
                    logger.info(
                        "Loaded %d tables from tables/*.json (fallback)",
                        len(tables),
                    )

        # Load figures from source_store.json assets or figures/screenshots dirs
        figures: list[FigureRef] = []
        if store_path.exists():
            try:
                store = json.loads(store_path.read_text(errors="replace"))
                for asset in store.get("assets", []):
                    img_path = asset.get("image_path", "")
                    if img_path and Path(img_path).exists():
                        figures.append(FigureRef(
                            figure_id=asset.get("asset_id", asset.get("figure_id", f"fig_{len(figures)}")),
                            source_file=asset.get("source_file", ""),
                            image_path=img_path,
                            caption=asset.get("caption", ""),
                            description=asset.get("description", ""),
                            page_number=asset.get("page_number"),
                            width=asset.get("width"),
                            height=asset.get("height"),
                            figure_type=asset.get("figure_type", "figure"),
                        ))
                if figures:
                    logger.info("Loaded %d figures from source_store assets", len(figures))
            except Exception as e:
                logger.warning("Failed to load assets from source_store: %s", e)

        # Fallback: scan figures/ and screenshots/ directories
        if not figures:
            for subdir, fig_type in [("figures", "figure"), ("screenshots", "page_screenshot")]:
                fig_dir = source_pack / subdir
                if fig_dir.exists():
                    for img in sorted(fig_dir.glob("*.png")):
                        figures.append(FigureRef(
                            figure_id=img.stem,
                            source_file="paper.pdf",
                            image_path=str(img),
                            caption=img.stem.replace("_", " "),
                            description=f"Extracted {fig_type} from paper",
                            figure_type=fig_type,
                        ))
            if figures:
                logger.info("Loaded %d figures from dirs (fallback)", len(figures))

        return EvidenceState(chunks=chunks, tables=tables, figures=figures)

    def _extract_must_cover(self, brief: str) -> list[str]:
        """Extract must-cover points from task brief."""
        points = []
        in_must_cover = False
        for line in brief.split("\n"):
            line = line.strip()
            if "must-cover" in line.lower() or "required sections" in line.lower():
                in_must_cover = True
                continue
            if in_must_cover:
                if line.startswith("-") or line.startswith("*"):
                    points.append(line.lstrip("-* ").strip())
                elif line.startswith("#") or (line and not line[0] in "-*0123456789"):
                    if points:
                        in_must_cover = False
                elif line and line[0].isdigit():
                    # Numbered list
                    parts = line.split(".", 1)
                    if len(parts) > 1:
                        points.append(parts[1].strip())
        return points

    def _extract_must_avoid(self, brief: str) -> list[str]:
        """Extract must-avoid points from task brief."""
        points = []
        in_must_avoid = False
        for line in brief.split("\n"):
            line = line.strip()
            if "must-avoid" in line.lower():
                in_must_avoid = True
                continue
            if in_must_avoid:
                if line.startswith("-") or line.startswith("*"):
                    points.append(line.lstrip("-* ").strip())
                elif line.startswith("#") or (not line.startswith("-") and not line.startswith("*") and line and not line[0].isdigit()):
                    if points:
                        in_must_avoid = False
        return points
