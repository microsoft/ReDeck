"""SlideSourceBundleBuilder — assemble per-slide evidence bundles."""

import re

from .models import (
    AtomicBlock, Asset, TableData, DocumentBlock, DocumentBlockPlan, SlideSourceBundle
)

_PAGE_HEADING_RE = re.compile(r'^\s*#{1,6}\s*Page\s+(\d+)\b', re.IGNORECASE)


def _page_from_heading(text: str) -> int | None:
    match = _PAGE_HEADING_RE.match(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


class SlideSourceBundleBuilder:
    """Build SlideSourceBundle for each slide from a deck plan."""

    def build(
        self,
        deck_plan: list[dict],
        doc_plan: DocumentBlockPlan,
        blocks: list[AtomicBlock],
        assets: list[Asset],
        tables: list[TableData],
        max_source_chars: int = 12000,
    ) -> list[SlideSourceBundle]:
        """Build bundles from deck plan.

        deck_plan: list of dicts with keys:
            slide_id, slide_title, source_doc_block_ids, asset_ids, table_ids
        """
        block_map = {b.block_id: b for b in blocks}
        db_map = {db.doc_block_id: db for db in doc_plan.blocks}
        asset_map = {a.asset_id: a for a in assets}
        table_map = {t.table_id: t for t in tables}

        bundles = []
        for slide in deck_plan:
            # Collect all atomic block IDs from referenced doc blocks
            atomic_ids: list[str] = []
            for dbid in slide.get("source_doc_block_ids", []):
                db = db_map.get(dbid)
                if db:
                    atomic_ids.extend(db.included_atomic_block_ids)

            # Deduplicate while preserving order
            seen = set()
            unique_atomic: list[str] = []
            for aid in atomic_ids:
                if aid not in seen:
                    seen.add(aid)
                    unique_atomic.append(aid)

            # Build source text — include page numbers so codegen can cite correctly
            source_parts: list[str] = []
            total_chars = 0
            current_context_page: int | None = None
            emitted_page: int | None = None
            for bid in unique_atomic:
                b = block_map.get(bid)
                if b:
                    text = b.text
                    heading_page = _page_from_heading(text)
                    if heading_page is not None:
                        current_context_page = heading_page
                        if heading_page != emitted_page:
                            emitted_page = heading_page
                            source_parts.append(f"\n## Page {heading_page}")
                        continue
                    logical_page = current_context_page or b.page
                    if total_chars + len(text) > max_source_chars:
                        source_parts.append(f"[{bid}] [TRUNCATED]")
                        break
                    # Insert page header when page changes
                    if logical_page is not None and logical_page != emitted_page:
                        emitted_page = logical_page
                        source_parts.append(f"\n## Page {logical_page}")
                    source_parts.append(f"[{bid}] {text}")
                    total_chars += len(text)

            # Asset summaries
            a_summaries = []
            for aid in slide.get("asset_ids", []):
                a = asset_map.get(aid)
                if a:
                    a_summaries.append(f"[{aid}] {a.caption or a.summary or 'No caption'}")

            # Table summaries
            t_summaries = []
            for tid in slide.get("table_ids", []):
                t = table_map.get(tid)
                if t:
                    t_summaries.append(f"[{tid}] {t.caption or t.summary or 'No caption'}")

            bundles.append(SlideSourceBundle(
                slide_id=slide["slide_id"],
                slide_title=slide.get("slide_title", ""),
                source_doc_block_ids=slide.get("source_doc_block_ids", []),
                source_atomic_block_ids=unique_atomic,
                asset_ids=slide.get("asset_ids", []),
                table_ids=slide.get("table_ids", []),
                source_text="\n".join(source_parts),
                asset_summaries=a_summaries,
                table_summaries=t_summaries,
            ))

        return bundles
