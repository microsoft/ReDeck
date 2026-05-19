"""Tests for SourceIndexer module.

Updated for pyramid Document Store architecture:
  - Only paper_full.md is indexed for text (no rglob("*.md"))
  - Figures from source_pack/figures/ (fallback: extracted_from_pdf/images/)
  - Tables from source_pack/tables/*.json + extracted_tables/*.csv
  - Screenshots from source_pack/screenshots/
"""

import pytest
from pathlib import Path

from app.modules.source_indexer import SourceIndexer
from app.schemas.evidence import EvidenceState


class TestSourceIndexer:
    """Test SourceIndexer with real case_01 data and synthetic data."""

    def test_index_case_01(self, case_01_dir):
        """case_01 is a manual test case with no paper_full.md.
        It should still index tables from extracted_tables/ CSV files.
        """
        indexer = SourceIndexer()
        evidence = indexer.index(case_01_dir)
        assert isinstance(evidence, EvidenceState)
        # case_01 has no paper_full.md or .txt files, so 0 text chunks
        # but it has extracted_tables/benchmark_results.csv
        assert len(evidence.tables) > 0

    def test_table_extraction(self, case_01_dir):
        indexer = SourceIndexer()
        evidence = indexer.index(case_01_dir)
        # case_01 has extracted_tables/benchmark_results.csv
        assert len(evidence.tables) > 0
        table = evidence.tables[0]
        assert table.table_id.startswith("table_")
        assert len(table.headers) > 0
        assert table.row_count > 0

    def test_numeric_fact_field_defaults_empty(self, case_01_dir):
        """Numeric facts default to an empty list."""
        indexer = SourceIndexer()
        evidence = indexer.index(case_01_dir)
        assert evidence.numeric_facts == []

    def test_entity_registry_defaults_empty(self, case_01_dir):
        """Entity registry defaults to an empty list."""
        indexer = SourceIndexer()
        evidence = indexer.index(case_01_dir)
        assert evidence.entity_registry == []

    def test_empty_directory_handling(self, tmp_path):
        """An empty source_pack directory should return empty evidence."""
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        indexer = SourceIndexer()
        evidence = indexer.index(tmp_path)
        assert evidence.chunks == []
        assert evidence.numeric_facts == []
        assert evidence.entity_registry == []

    def test_index_marker_markdown(self, tmp_path):
        """Test _index_marker_markdown on a synthetic paper_full.md file."""
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        md_file = source_dir / "paper_full.md"
        md_file.write_text(
            "# Section One\n"
            "Content of section one\n"
            "\n"
            "# Section Two\n"
            "Content of section two\n"
            "More content\n"
        )
        indexer = SourceIndexer()
        chunks, tables, formulas = indexer._index_marker_markdown(md_file)
        assert len(chunks) == 2
        assert "section one" in chunks[0].content.lower() or "Section One" in chunks[0].content
        assert chunks[0].chunk_id.startswith("sec_")

    def test_index_marker_markdown_with_tables(self, tmp_path):
        """Test that _index_marker_markdown extracts tables from markdown."""
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        md_file = source_dir / "paper_full.md"
        md_file.write_text(
            "# Results\n"
            "Our method outperforms baselines:\n\n"
            "| Model | Accuracy | F1 |\n"
            "| --- | --- | --- |\n"
            "| Ours | 95.2 | 94.1 |\n"
            "| Baseline | 89.3 | 88.7 |\n"
        )
        indexer = SourceIndexer()
        chunks, tables, formulas = indexer._index_marker_markdown(md_file)
        assert len(chunks) >= 1
        assert len(tables) >= 1
        assert tables[0].row_count >= 2
        assert "Accuracy" in tables[0].headers

    def test_index_marker_markdown_with_formulas(self, tmp_path):
        """Test that _index_marker_markdown extracts LaTeX formulas."""
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        md_file = source_dir / "paper_full.md"
        md_file.write_text(
            "# Method\n"
            "The loss function is defined as:\n"
            "$$L = -\\sum_{i=1}^{N} y_i \\log(p_i)$$\n"
        )
        indexer = SourceIndexer()
        chunks, tables, formulas = indexer._index_marker_markdown(md_file)
        assert len(formulas) >= 1
        assert "sum" in formulas[0].latex
        assert formulas[0].display is True

    def test_index_text_private(self, tmp_path):
        """Test _index_text on a plain text file."""
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        txt_file = source_dir / "notes.txt"
        txt_file.write_text("This is plain text content.")
        indexer = SourceIndexer()
        chunks = indexer._index_text(txt_file)
        assert len(chunks) == 1
        assert chunks[0].content == "This is plain text content."

    def test_extract_numeric_facts_is_not_public_api(self):
        """Numeric fact extraction is not part of the public indexer API."""
        indexer = SourceIndexer()
        assert not hasattr(indexer, '_extract_numeric_facts')

    def test_extract_entities_is_not_public_api(self):
        """Entity extraction is not part of the public indexer API."""
        indexer = SourceIndexer()
        assert not hasattr(indexer, '_extract_entities')

    def test_csv_indexing(self, tmp_path):
        """Test CSV table indexing."""
        source_dir = tmp_path / "source_pack" / "extracted_tables"
        source_dir.mkdir(parents=True)
        csv_file = source_dir / "metrics.csv"
        csv_file.write_text(
            "Model,Accuracy,Latency\n"
            "A,78.3,420\n"
            "B,74.1,180\n"
        )
        indexer = SourceIndexer()
        table = indexer._index_csv(csv_file, tmp_path)
        assert table.table_id == "table_metrics"
        assert table.headers == ["Model", "Accuracy", "Latency"]
        assert table.row_count == 2

    def test_full_index_synthetic(self, tmp_path):
        """Full index of a synthetic case directory with paper_full.md."""
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        # paper_full.md is the single source of truth for text
        (source_dir / "paper_full.md").write_text(
            "# Overview\n"
            "**AlphaModel** achieves 95.2% on the benchmark.\n"
            "\n"
            "# Results\n"
            "We compare against baselines.\n"
        )
        indexer = SourceIndexer()
        evidence = indexer.index(tmp_path)
        assert len(evidence.chunks) >= 2
        # numeric_facts and entity_registry extraction removed — verify empty
        assert evidence.numeric_facts == []
        assert evidence.entity_registry == []

    def test_figure_indexing_pyramid(self, tmp_path):
        """Test figure indexing from new pyramid figures/ directory."""
        source_dir = tmp_path / "source_pack"
        figures_dir = source_dir / "figures"
        figures_dir.mkdir(parents=True)
        # Create a dummy PNG file
        dummy_png = figures_dir / "fig_001.png"
        dummy_png.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)
        indexer = SourceIndexer()
        evidence = indexer.index(tmp_path)
        assert len(evidence.figures) >= 1
        fig = evidence.figures[0]
        assert fig.figure_id.startswith("fig_")
        assert fig.image_path is not None

    def test_screenshot_indexing_pyramid(self, tmp_path):
        """Test screenshot indexing from new pyramid screenshots/ directory."""
        source_dir = tmp_path / "source_pack"
        ss_dir = source_dir / "screenshots"
        ss_dir.mkdir(parents=True)
        # Create a dummy PNG file
        dummy_png = ss_dir / "page_01.png"
        dummy_png.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)
        indexer = SourceIndexer()
        evidence = indexer.index(tmp_path)
        screenshots = [f for f in evidence.figures if f.figure_type == "page_screenshot"]
        assert len(screenshots) >= 1
        # ID is now the stem directly (not prefixed with screenshot_)
        assert screenshots[0].figure_id == "page_01"

    def test_table_json_indexing(self, tmp_path):
        """Test table indexing from JSON sidecar files (new pyramid format)."""
        import json
        source_dir = tmp_path / "source_pack"
        tables_dir = source_dir / "tables"
        tables_dir.mkdir(parents=True)
        # Create a JSON sidecar file
        table_data = {
            "rows": [
                ["Model", "Accuracy", "F1"],
                ["Ours", "95.2", "94.1"],
                ["Baseline", "89.3", "88.7"],
            ],
            "caption": "Main results comparison",
            "page": 5,
        }
        json_file = tables_dir / "tbl_001.json"
        json_file.write_text(json.dumps(table_data))
        indexer = SourceIndexer()
        evidence = indexer.index(tmp_path)
        assert len(evidence.tables) >= 1
        tbl = evidence.tables[0]
        assert tbl.table_id == "tbl_001"
        assert tbl.row_count == 2
        assert "Model" in tbl.headers
        assert "Main results" in tbl.caption

    def test_only_paper_full_md_indexed(self, tmp_path):
        """Verify that only paper_full.md is indexed for text, not other .md files."""
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        # paper_full.md should be indexed
        (source_dir / "paper_full.md").write_text("# Main\nPrimary content.\n")
        # Other .md files should NOT be indexed
        (source_dir / "notes.md").write_text("# Notes\nSide notes.\n")
        (source_dir / "source_summary.md").write_text("# Summary\nOld summary.\n")
        indexer = SourceIndexer()
        evidence = indexer.index(tmp_path)
        # Only paper_full.md chunks
        assert all(c.source_file == "paper_full.md" for c in evidence.chunks)
        assert len(evidence.chunks) >= 1
