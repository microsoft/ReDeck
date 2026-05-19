"""ResourceSummaryIndexBuilder — generate summary indices."""

from .models import AtomicBlock, Asset, TableData, DocumentBlock, DocumentBlockPlan


class ResourceSummaryIndexBuilder:
    """Build block/asset/table summary indices from a DocumentBlockPlan."""

    def build(
        self,
        plan: DocumentBlockPlan,
        assets: list[Asset],
        tables: list[TableData],
    ) -> dict:
        """Return dict with block_index, asset_index, table_index."""

        # Block summary index
        block_index = []
        for db in plan.blocks:
            block_index.append({
                "doc_block_id": db.doc_block_id,
                "title": db.title,
                "role": db.role,
                "summary": db.summary,
                "keywords": db.keywords,
                "page_range": db.page_range,
                "linked_asset_ids": db.linked_asset_ids,
                "linked_table_ids": db.linked_table_ids,
                "importance": db.importance,
            })

        # Asset summary index
        # Link assets back to doc blocks
        asset_to_dbs: dict[str, list[str]] = {}
        for db in plan.blocks:
            for aid in db.linked_asset_ids:
                asset_to_dbs.setdefault(aid, []).append(db.doc_block_id)

        asset_index = []
        for a in assets:
            asset_index.append({
                "asset_id": a.asset_id,
                "type": a.type,
                "page": a.page,
                "caption": a.caption,
                "summary": a.summary,
                "linked_doc_block_ids": asset_to_dbs.get(a.asset_id, []),
                "image_path": a.image_path,
            })

        # Table summary index
        table_to_dbs: dict[str, list[str]] = {}
        for db in plan.blocks:
            for tid in db.linked_table_ids:
                table_to_dbs.setdefault(tid, []).append(db.doc_block_id)

        table_index = []
        for t in tables:
            # Extract headers from markdown
            headers = []
            for line in t.rows_or_markdown.split("\n"):
                if "|" in line and "---" not in line:
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    if cells and not headers:
                        headers = cells
                    break

            row_count = sum(
                1 for line in t.rows_or_markdown.split("\n")
                if "|" in line and "---" not in line
            )

            table_index.append({
                "table_id": t.table_id,
                "caption": t.caption,
                "summary": t.summary,
                "headers": headers,
                "row_count": max(0, row_count - 1),  # exclude header
                "linked_doc_block_ids": table_to_dbs.get(t.table_id, []),
            })

        return {
            "block_index": block_index,
            "asset_index": asset_index,
            "table_index": table_index,
        }
