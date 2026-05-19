"""DocumentBlockValidator — mechanical validation of LLM block plan."""

from dataclasses import dataclass, field

from .models import AtomicBlock, Asset, TableData, DocumentBlock, DocumentBlockPlan


@dataclass
class ValidationResult:
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage_pct: float = 0.0
    uncovered_blocks: list[str] = field(default_factory=list)
    duplicate_blocks: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Validation: {'PASS' if self.passed else 'FAIL'}"]
        lines.append(f"Coverage: {self.coverage_pct:.1f}%")
        if self.uncovered_blocks:
            lines.append(f"Uncovered blocks ({len(self.uncovered_blocks)}): {self.uncovered_blocks[:10]}")
        if self.duplicate_blocks:
            lines.append(f"Duplicates in unrelated blocks: {self.duplicate_blocks[:10]}")
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN: {w}")
        return "\n".join(lines)


class DocumentBlockValidator:
    """Validate a DocumentBlockPlan against source data."""

    def validate(
        self,
        plan: DocumentBlockPlan,
        blocks: list[AtomicBlock],
        assets: list[Asset],
        tables: list[TableData],
    ) -> ValidationResult:
        result = ValidationResult()

        block_ids = {b.block_id for b in blocks}
        asset_ids = {a.asset_id for a in assets}
        table_ids = {t.table_id for t in tables}

        all_referenced: set[str] = set()

        for db in plan.blocks:
            # Check atomic block refs
            for bid in db.included_atomic_block_ids:
                if bid not in block_ids:
                    result.errors.append(f"{db.doc_block_id}: references unknown block {bid}")
                    result.passed = False
                all_referenced.add(bid)

            # Check asset refs
            for aid in db.linked_asset_ids:
                if aid not in asset_ids:
                    result.errors.append(f"{db.doc_block_id}: references unknown asset {aid}")
                    result.passed = False

            # Check table refs
            for tid in db.linked_table_ids:
                if tid not in table_ids:
                    result.errors.append(f"{db.doc_block_id}: references unknown table {tid}")
                    result.passed = False

            # Check page_range consistency
            if db.included_atomic_block_ids and db.page_range:
                ref_pages = {
                    b.page for b in blocks
                    if b.block_id in set(db.included_atomic_block_ids) and b.page is not None
                }
                if ref_pages:
                    min_p, max_p = min(ref_pages), max(ref_pages)
                    if db.page_range and (db.page_range[0] > min_p or db.page_range[-1] < max_p):
                        result.warnings.append(
                            f"{db.doc_block_id}: page_range {db.page_range} doesn't cover actual pages [{min_p}, {max_p}]"
                        )

        # Coverage check
        # Only count non-trivial blocks (skip very short noise)
        substantive_ids = {b.block_id for b in blocks if len(b.text.strip()) > 10}
        uncovered = substantive_ids - all_referenced
        result.uncovered_blocks = sorted(uncovered)
        result.coverage_pct = (
            (len(substantive_ids) - len(uncovered)) / len(substantive_ids) * 100
            if substantive_ids else 100.0
        )

        if result.coverage_pct < 80:
            result.errors.append(f"Low coverage: {result.coverage_pct:.1f}% (need >80%)")
            result.passed = False
        elif result.coverage_pct < 95:
            result.warnings.append(f"Moderate coverage: {result.coverage_pct:.1f}%")

        # Check unused assets
        all_linked_assets = set()
        for db in plan.blocks:
            all_linked_assets.update(db.linked_asset_ids)
        figure_assets = {a.asset_id for a in assets if a.type == "figure"}
        unused_figures = figure_assets - all_linked_assets
        if unused_figures:
            result.warnings.append(f"Unused figure assets: {sorted(unused_figures)}")

        return result
