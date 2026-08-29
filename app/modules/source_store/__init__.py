"""SourceStore — structured document store replacing EvidenceState.

Provides:
- AtomicBlock: smallest text units from PDF extraction
- DocumentBlock: LLM-produced semantic sub-document blocks
- SlideSourceBundle: per-slide evidence packages
- SourceStore: central container holding all artifacts
"""

import json
import logging
from pathlib import Path

from .models import (
    AtomicBlock,
    Asset,
    TableData,
    DocumentBlock,
    DocumentBlockPlan,
    SlideSourceBundle,
    SourceStore,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AtomicBlock",
    "Asset",
    "TableData",
    "DocumentBlock",
    "DocumentBlockPlan",
    "SlideSourceBundle",
    "SourceStore",
    "build_source_store",
]


def build_source_store(
    case_dir: str | Path,
    llm,
    *,
    cache: bool = True,
    model: str | None = None,
    source_kind: str = "paper",
) -> SourceStore:
    """One-shot build: parse PDF → LLM block planning → validate → index.

    Args:
        case_dir: Path to the case directory (contains ``source_pack/``).
        llm: ``LLMClient`` instance for document block planning.
        cache: If True (default), persist to / load from
            ``source_pack/source_store.json``.
        model: Optional model override for the block planner LLM call.
        source_kind: Semantic source class. ``document`` avoids academic-paper
            assumptions for reports, filings, and existing presentations.

    Returns:
        Fully constructed ``SourceStore`` (without bundles — those are
        built after the deck planner assigns source links).
    """
    from .anchored_doc import AnchoredDocumentBuilder
    from .block_planner import LLMDocumentBlockPlanner
    from .validator import DocumentBlockValidator
    from .summary_index import ResourceSummaryIndexBuilder

    case_dir = Path(case_dir)
    source_dir = case_dir / "source_pack"
    cache_path = source_dir / "source_store.json"

    # ── Try cache ──
    if cache and cache_path.exists():
        try:
            store = SourceStore.model_validate_json(cache_path.read_text("utf-8"))
            try:
                builder = AnchoredDocumentBuilder()
                discovered_assets = builder._load_assets(source_dir)
                refreshed = _refresh_cached_asset_paths(
                    store.assets, discovered_assets,
                )
                if refreshed:
                    store.summary_index = ResourceSummaryIndexBuilder().build(
                        store.doc_block_plan, store.assets, store.table_data,
                    )
                    try:
                        cache_path.write_text(
                            store.model_dump_json(indent=2), "utf-8",
                        )
                    except OSError as e:
                        logger.warning(
                            "Could not persist refreshed asset paths: %s", e,
                        )
                    logger.info(
                        "Refreshed %d cached SourceStore asset path(s)",
                        refreshed,
                    )
            except Exception as e:
                logger.warning(
                    "Could not refresh cached SourceStore asset paths: %s", e,
                )
            logger.info(
                "Loaded cached SourceStore (%d blocks, %d doc_blocks)",
                len(store.atomic_blocks),
                len(store.doc_block_plan.blocks),
            )
            return store
        except Exception as e:
            logger.warning("Failed to load cached SourceStore: %s — rebuilding", e)

    # ── Step 1: Parse into AtomicBlocks + Assets + Tables ──
    builder = AnchoredDocumentBuilder()
    blocks, assets, tables, anchored_doc = builder.build(source_dir)
    logger.info(
        "AnchoredDocumentBuilder: %d blocks, %d assets, %d tables, %d chars",
        len(blocks), len(assets), len(tables), len(anchored_doc),
    )

    # ── Step 2: LLM Document Block Planning ──
    planner = LLMDocumentBlockPlanner(llm)
    plan = planner.plan(
        anchored_doc, blocks, assets, tables,
        model=model, source_kind=source_kind,
    )
    logger.info(
        "LLMDocumentBlockPlanner: %d doc blocks, profile=%s",
        len(plan.blocks), plan.document_profile,
    )

    # ── Step 3: Validate ──
    validator = DocumentBlockValidator()
    vresult = validator.validate(plan, blocks, assets, tables)
    if not vresult.passed:
        logger.warning("DocumentBlock validation FAILED:\n%s", vresult.summary())
    else:
        logger.info(
            "DocumentBlock validation PASSED (coverage %.1f%%)",
            vresult.coverage_pct,
        )

    # ── Step 4: Build summary index ──
    idx_builder = ResourceSummaryIndexBuilder()
    summary_index = idx_builder.build(plan, assets, tables)

    # ── Assemble SourceStore ──
    store = SourceStore(
        atomic_blocks=blocks,
        assets=assets,
        table_data=tables,
        doc_block_plan=plan,
        summary_index=summary_index,
        anchored_doc=anchored_doc,
    )

    # ── Cache ──
    if cache:
        try:
            cache_path.write_text(store.model_dump_json(indent=2), "utf-8")
            logger.info("Cached SourceStore to %s", cache_path)
        except Exception as e:
            logger.warning("Failed to cache SourceStore: %s", e)

    return store


def _refresh_cached_asset_paths(
    cached_assets: list[Asset],
    discovered_assets: list[Asset],
) -> int:
    """Repair stale or empty paths without changing cached asset IDs.

    Existing document-block plans refer to canonical A### IDs, so cached IDs
    must remain stable. Figure metadata provides a stronger match than ordinal
    position; the ID is used only as a final compatibility fallback.
    """
    available = [
        asset for asset in discovered_assets
        if asset.image_path and Path(asset.image_path).is_file()
    ]
    refreshed = 0

    for cached in cached_assets:
        if cached.image_path and Path(cached.image_path).is_file():
            continue

        matches = [
            asset for asset in available
            if asset.type == cached.type
            and asset.page == cached.page
            and asset.bbox == cached.bbox
        ]
        if len(matches) != 1:
            matches = [
                asset for asset in available
                if asset.type == cached.type
                and asset.asset_id == cached.asset_id
            ]
        if len(matches) == 1:
            cached.image_path = matches[0].image_path
            refreshed += 1

    return refreshed
