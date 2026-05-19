"""AnchoredDocumentBuilder — parse paper_full.md into AtomicBlocks + Assets."""

import json
import re
from pathlib import Path

from .models import AtomicBlock, Asset, TableData


class AnchoredDocumentBuilder:
    """Build anchored document from paper_full.md and figure sidecars."""

    def build(
        self, source_dir: str | Path
    ) -> tuple[list[AtomicBlock], list[Asset], list[TableData], str]:
        """Parse source_pack and return (blocks, assets, tables, anchored_doc).

        Returns:
            blocks: list of AtomicBlock
            assets: list of Asset (figures + screenshots)
            tables: list of TableData (extracted from markdown)
            anchored_doc: full document with ID anchors
        """
        source_dir = Path(source_dir)
        paper_path = source_dir / "paper_full.md"
        content = paper_path.read_text(encoding="utf-8")

        blocks = self._parse_blocks(content)
        assets = self._load_assets(source_dir)
        tables = self._extract_tables(blocks, source_dir)
        anchored = self._render_anchored(blocks, assets, tables)

        return blocks, assets, tables, anchored

    def _parse_blocks(self, content: str) -> list[AtomicBlock]:
        """Split markdown into AtomicBlocks by paragraph."""
        blocks: list[AtomicBlock] = []
        counter = 1

        # Track current page from page markers
        current_page = 1
        page_pattern = re.compile(r'id="page-(\d+)"')

        # Split into paragraphs (double newline or heading boundary)
        lines = content.split("\n")
        current_lines: list[str] = []
        current_type = "paragraph"

        def flush():
            nonlocal counter, current_lines, current_type
            text = "\n".join(current_lines).strip()
            if not text:
                current_lines = []
                return
            # Skip very short noise
            if len(text) < 3 and not re.match(r"^#{1,4}\s", text):
                current_lines = []
                return
            bid = f"B{counter:03d}"
            blocks.append(AtomicBlock(
                block_id=bid,
                type=current_type,
                page=current_page,
                text=text,
            ))
            counter += 1
            current_lines = []
            current_type = "paragraph"

        for line in lines:
            # Track page
            pm = page_pattern.search(line)
            if pm:
                current_page = int(pm.group(1))

            # Heading starts a new block
            heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
            if heading_match:
                flush()
                current_type = "heading"
                current_lines = [line]
                flush()
                continue

            # Empty line = paragraph boundary
            if not line.strip():
                if current_lines:
                    flush()
                continue

            # Figure/image reference
            if line.strip().startswith("!["):
                flush()
                current_type = "caption"
                current_lines = [line]
                flush()
                continue

            # Detect list items
            if re.match(r"^\s*[-*+]\s", line) or re.match(r"^\s*\d+\.\s", line):
                current_type = "list_item"

            current_lines.append(line)

        flush()
        return blocks

    def _load_assets(self, source_dir: Path) -> list[Asset]:
        """Load figure/table assets from sidecar JSON files."""
        assets: list[Asset] = []
        counter = 1

        # Figures
        figures_dir = source_dir / "figures"
        if figures_dir.exists():
            for json_path in sorted(figures_dir.glob("*.json")):
                data = json.loads(json_path.read_text())
                png_path = json_path.with_suffix(".png")
                aid = f"A{counter:03d}"
                assets.append(Asset(
                    asset_id=aid,
                    type="figure",
                    page=data.get("page"),
                    image_path=str(png_path) if png_path.exists() else "",
                    caption=data.get("caption", ""),
                    bbox=data.get("bbox", []),
                ))
                counter += 1

        # Screenshots
        screenshots_dir = source_dir / "screenshots"
        if screenshots_dir.exists():
            for png_path in sorted(screenshots_dir.glob("*.png")):
                page_match = re.search(r"p(\d+)", png_path.stem)
                page = int(page_match.group(1)) if page_match else None
                aid = f"A{counter:03d}"
                assets.append(Asset(
                    asset_id=aid,
                    type="page_screenshot",
                    page=page,
                    image_path=str(png_path),
                ))
                counter += 1

        return assets

    def _extract_tables(
        self, blocks: list[AtomicBlock], source_dir: Path | None = None,
    ) -> list[TableData]:
        """Extract markdown tables from blocks.

        Also cross-references raw table JSON files in source_pack/tables/
        to fill in captions that can't be found from the markdown block alone.
        """
        # --- Pre-load raw table JSON captions (from PDF extraction) ---
        # These have accurate captions like "Table 4: Performance analysis..."
        # Index by table number for matching against markdown content.
        raw_captions_by_num: dict[int, str] = {}  # table_number → caption
        if source_dir is not None:
            tables_dir = source_dir / "tables"
            if tables_dir.exists():
                for jp in sorted(tables_dir.glob("*.json")):
                    try:
                        raw = json.loads(jp.read_text())
                        cap = raw.get("caption", "")
                        if cap:
                            # Extract table number from caption: "Table 4: ..." → 4
                            tn_match = re.match(r"Table\s+(\d+)", cap, re.IGNORECASE)
                            if tn_match:
                                raw_captions_by_num[int(tn_match.group(1))] = cap
                    except Exception:
                        pass

        # --- Also check preceding blocks for "Table N:" patterns ---
        block_texts_by_idx = {i: b for i, b in enumerate(blocks)}
        table_caption_pat = re.compile(
            r"^(Table\s+\d+[.:]\s*.+)", re.IGNORECASE
        )

        tables: list[TableData] = []
        counter = 1
        used_raw_nums: set[int] = set()
        used_captions: set[str] = set()  # prevent same caption on two tables

        for idx, block in enumerate(blocks):
            # Simple heuristic: block contains | and has table-like rows
            lines = block.text.split("\n")
            table_lines = [l for l in lines if "|" in l and l.strip().startswith("|")]
            if len(table_lines) >= 2:
                tid = f"T{counter:03d}"

                # Strategy 1: caption from non-table lines in same block
                caption = ""
                non_table_lines = [l for l in lines if "|" not in l and l.strip()]
                if non_table_lines:
                    caption = non_table_lines[0][:200]

                # Strategy 2: check surrounding blocks (after THEN before)
                # LaTeX default places captions AFTER the table, so check
                # following blocks first. Use a dedup set to prevent the
                # same caption being assigned to multiple tables.
                if not caption:
                    check_texts = []
                    # Following blocks first (more likely for LaTeX papers)
                    for lookahead in range(1, min(3, len(blocks) - idx)):
                        check_texts.append(blocks[idx + lookahead].text.strip())
                    # Then preceding blocks
                    for lookback in range(1, min(4, idx + 1)):
                        check_texts.append(blocks[idx - lookback].text.strip())
                    for cb_text in check_texts:
                        m = table_caption_pat.match(cb_text)
                        if m:
                            cap_candidate = m.group(1)[:200]
                            if cap_candidate not in used_captions:
                                caption = cap_candidate
                                used_captions.add(cap_candidate)
                                break

                # Strategy 3: find "Table N" reference closest to this table
                # Look in the table's own content and preceding blocks for the
                # actual table number this data belongs to, then use the raw
                # JSON caption for that number.
                if not caption:
                    # Search the table header row + nearby text for table refs
                    search_text = "\n".join(table_lines[:2])
                    # Also check up to 5 preceding blocks
                    for lookback in range(1, min(6, idx + 1)):
                        search_text += "\n" + blocks[idx - lookback].text
                    # Find all "Table N" references, take the last one closest
                    # to this table (most likely to be its own caption/reference)
                    table_refs_found = re.findall(r"Table\s+(\d+)", search_text)
                    # Try each found number (prefer those that haven't been used)
                    for tn_str in reversed(table_refs_found):
                        tn = int(tn_str)
                        if tn in raw_captions_by_num and tn not in used_raw_nums:
                            caption = raw_captions_by_num[tn][:200]
                            used_raw_nums.add(tn)
                            break

                tables.append(TableData(
                    table_id=tid,
                    caption=caption,
                    page=block.page,
                    rows_or_markdown="\n".join(table_lines),
                    linked_block_ids=[block.block_id],
                ))
                counter += 1

        return tables

    def _render_anchored(
        self,
        blocks: list[AtomicBlock],
        assets: list[Asset],
        tables: list[TableData],
    ) -> str:
        """Render the full document with ID anchors."""
        parts: list[str] = []

        for block in blocks:
            page_str = f"p{block.page}" if block.page else "p?"
            # Truncate very long blocks for anchor display
            text_preview = block.text
            parts.append(f"[{block.block_id} | {page_str} | {block.type}] {text_preview}")

        # Append asset index
        parts.append("\n--- ASSETS ---")
        for asset in assets:
            page_str = f"p{asset.page}" if asset.page else "p?"
            cap = asset.caption[:150] if asset.caption else ""
            parts.append(
                f"[{asset.asset_id} | {asset.type} | {page_str} | path={asset.image_path} | caption={cap}]"
            )

        # Append table index
        if tables:
            parts.append("\n--- TABLES ---")
            for tbl in tables:
                page_str = f"p{tbl.page}" if tbl.page else "p?"
                cap = tbl.caption[:150] if tbl.caption else ""
                parts.append(f"[{tbl.table_id} | table | {page_str} | caption={cap}]")

        return "\n".join(parts)
