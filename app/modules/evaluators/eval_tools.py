"""Evaluation tools for agent-based judges.

Provides search_source and lookup_table tools that allow D/E judges
to verify claims against source materials before reporting issues.

Uses BM25 ranking (via rank_bm25) for relevance scoring instead of
naive keyword overlap.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rank_bm25 import BM25Plus

from ...schemas.evidence import EvidenceChunk, EvidenceState, TableRef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BM25-backed evidence index
# ---------------------------------------------------------------------------

class EvidenceIndex:
    """BM25 index over evidence chunks and tables.

    Built once per case via ``EvidenceState.get_index()`` and reused across
    all search_source / lookup_table calls for both judge and repair agents.
    """

    def __init__(self, evidence: EvidenceState) -> None:
        # ── Chunk index ──
        self._chunks: list[EvidenceChunk] = list(evidence.chunks or [])
        chunk_texts = [
            f"{c.metadata.get('section', '')} {c.content}"
            for c in self._chunks
        ]
        self._chunk_corpus = [self._tokenize(t) for t in chunk_texts]
        self._chunk_bm25: BM25Plus | None = (
            BM25Plus(self._chunk_corpus) if self._chunk_corpus else None
        )

        # ── Table index ──
        self._tables: list[TableRef] = list(evidence.tables or [])
        table_texts = [
            f"{t.caption or ''} {' '.join(t.headers)} {t.content or ''}"
            for t in self._tables
        ]
        self._table_corpus = [self._tokenize(t) for t in table_texts]
        self._table_bm25: BM25Plus | None = (
            BM25Plus(self._table_corpus) if self._table_corpus else None
        )

        logger.debug(
            "EvidenceIndex built: %d chunks, %d tables",
            len(self._chunks), len(self._tables),
        )

    # ── helpers ──

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lower-case alphanumeric tokenisation."""
        return re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower()).split()

    # ── search methods ──

    def search_chunks(
        self, query: str, top_k: int = 5,
    ) -> list[tuple[float, EvidenceChunk]]:
        if not self._chunk_bm25:
            return []
        tokens = self._tokenize(query)
        if not tokens:
            return []
        scores = self._chunk_bm25.get_scores(tokens)
        top_idx = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True,
        )[:top_k]
        return [
            (float(scores[i]), self._chunks[i])
            for i in top_idx
            if scores[i] > 0
        ]

    def search_tables(
        self, query: str, top_k: int = 3,
    ) -> list[tuple[float, TableRef]]:
        if not self._table_bm25:
            return []
        tokens = self._tokenize(query)
        if not tokens:
            return []
        scores = self._table_bm25.get_scores(tokens)
        top_idx = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True,
        )[:top_k]
        return [
            (float(scores[i]), self._tables[i])
            for i in top_idx
            if scores[i] > 0
        ]


# ---------------------------------------------------------------------------
# Public search functions (backward-compatible signatures)
# ---------------------------------------------------------------------------

def search_source(
    query: str,
    evidence: EvidenceState | None,
    top_k: int = 5,
) -> str:
    """Search source evidence chunks by BM25 relevance.

    Args:
        query: Search query (keywords or phrases)
        evidence: EvidenceState containing source chunks
        top_k: Maximum number of results to return

    Returns:
        Formatted search results as a string
    """
    if not evidence or not evidence.chunks:
        return "No source materials available."

    if not query or not query.strip():
        return "Query too short or contains no meaningful keywords."

    index = evidence.get_index()
    results = index.search_chunks(query, top_k=top_k)

    if not results:
        return f"No results found for query: '{query}'"

    parts = [f"Search results for: '{query}' ({len(results)} results)\n"]
    for i, (score, chunk) in enumerate(results, 1):
        section = chunk.metadata.get("section", "unknown")
        page_ref = chunk.page_ref or "?"
        content_preview = chunk.content[:2000].strip()
        parts.append(
            f"--- Result {i} [{chunk.chunk_id}] "
            f"(section: {section}, page: {page_ref}, score: {score:.1f}) ---\n"
            f"{content_preview}\n"
        )

    return "\n".join(parts)


def lookup_table(
    query: str,
    evidence: EvidenceState | None,
    max_tables: int = 3,
) -> str:
    """Look up tables in source materials by BM25 relevance.

    Args:
        query: Search query
        evidence: EvidenceState containing tables
        max_tables: Maximum number of tables to return

    Returns:
        Formatted table results as a string
    """
    if not evidence or not evidence.tables:
        return "No tables available in source materials."

    if not query or not query.strip():
        return "Query too short."

    index = evidence.get_index()
    results = index.search_tables(query, top_k=max_tables)

    if not results:
        return f"No tables found matching: '{query}'"

    parts = [f"Table lookup for: '{query}' ({len(results)} results)\n"]
    for i, (score, tbl) in enumerate(results, 1):
        caption = tbl.caption or "(no caption)"
        parts.append(
            f"--- Table {i} [{tbl.table_id}] (score: {score:.1f}) ---\n"
            f"Caption: {caption}\n"
            f"Headers: {' | '.join(tbl.headers)}\n"
            f"Content:\n{tbl.content[:3000]}\n"
        )

    return "\n".join(parts)


def format_tool_results(
    tool_name: str, args: dict, evidence: EvidenceState | None,
) -> str:
    """Dispatch and format tool call results.

    Args:
        tool_name: Name of the tool to call
        args: Tool arguments
        evidence: EvidenceState for evidence-based tools

    Returns:
        Formatted tool output string
    """
    if tool_name == "search_source":
        query = args.get("query", "")
        top_k = args.get("top_k", 5)
        return search_source(query, evidence, top_k=top_k)
    elif tool_name == "lookup_table":
        query = args.get("query", "")
        return lookup_table(query, evidence)
    else:
        return f"Unknown tool: {tool_name}"
