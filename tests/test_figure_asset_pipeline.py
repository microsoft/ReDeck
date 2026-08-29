import json
from pathlib import Path

from app.modules.case_loader import CaseLoader
from app.modules.deck_planner import DeckPlanner
from app.modules.source_store import build_source_store
from app.modules.source_store.anchored_doc import AnchoredDocumentBuilder
from app.modules.source_store.models import (
    Asset,
    DocumentBlock,
    DocumentBlockPlan,
    SourceStore,
)
from app.schemas.blueprint import BlueprintSlide, DeckBlueprint
from app.schemas.evidence import EvidenceState, FigureRef


def _write_figure(
    source_pack: Path,
    stem: str,
    suffix: str,
    *,
    page: int,
    bbox: list[float],
) -> Path:
    figures_dir = source_pack / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    image_path = figures_dir / f"{stem}{suffix}"
    image_path.write_bytes(b"image-bytes")
    (figures_dir / f"{stem}.json").write_text(json.dumps({
        "figure_id": stem,
        "page": page,
        "bbox": bbox,
        "width": 640,
        "height": 480,
        "figure_type": "raster",
    }))
    return image_path


def _blueprint(*slides: BlueprintSlide) -> DeckBlueprint:
    return DeckBlueprint(
        case_id="figure-test",
        total_slides=len(slides),
        narrative_arc="test",
        slides=list(slides),
    )


def _slide(slide_id: int, **kwargs) -> BlueprintSlide:
    return BlueprintSlide(
        slide_id=slide_id,
        role="method",
        primary_proposition=f"Slide {slide_id}",
        narrative_position="body",
        **kwargs,
    )


def test_anchored_document_discovers_native_figure_formats(tmp_path):
    source_pack = tmp_path / "source_pack"
    source_pack.mkdir()
    source_pack.joinpath("paper_full.md").write_text("# Test\n\nBody")
    jpeg = _write_figure(
        source_pack, "fig_p2_photo", ".JPEG", page=2, bbox=[1, 2, 3, 4],
    )
    webp = _write_figure(
        source_pack, "fig_p3_plot", ".webp", page=3, bbox=[5, 6, 7, 8],
    )

    _, assets, _, _ = AnchoredDocumentBuilder().build(source_pack)

    figures = [asset for asset in assets if asset.type == "figure"]
    assert [Path(asset.image_path) for asset in figures] == [jpeg, webp]


def test_cached_source_store_repairs_empty_native_image_path(tmp_path):
    case_dir = tmp_path / "case"
    source_pack = case_dir / "source_pack"
    source_pack.mkdir(parents=True)
    source_pack.joinpath("paper_full.md").write_text("# Test\n\nBody")
    jpeg = _write_figure(
        source_pack, "fig_p7_img0", ".jpeg", page=7, bbox=[1, 2, 3, 4],
    )
    cached = SourceStore(assets=[Asset(
        asset_id="A001",
        type="figure",
        page=7,
        image_path="",
        bbox=[1, 2, 3, 4],
    )])
    cache_path = source_pack / "source_store.json"
    cache_path.write_text(cached.model_dump_json(indent=2))

    store = build_source_store(case_dir, llm=None)

    assert store.assets[0].asset_id == "A001"
    assert Path(store.assets[0].image_path) == jpeg
    persisted = SourceStore.model_validate_json(cache_path.read_text())
    assert Path(persisted.assets[0].image_path) == jpeg


def test_cached_source_store_survives_malformed_refresh_sidecar(tmp_path):
    case_dir = tmp_path / "case"
    source_pack = case_dir / "source_pack"
    figures_dir = source_pack / "figures"
    figures_dir.mkdir(parents=True)
    figures_dir.joinpath("broken.json").write_text("{not-json")
    cached = SourceStore(anchored_doc="cached document")
    source_pack.joinpath("source_store.json").write_text(
        cached.model_dump_json(indent=2)
    )

    store = build_source_store(case_dir, llm=None)

    assert store.anchored_doc == "cached document"


def test_planner_normalizes_extractor_ids_and_all_evidence_fields(tmp_path):
    first = tmp_path / "fig_p7_img0.jpeg"
    second = tmp_path / "fig_p10_img1.png"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    source_store = SourceStore(
        assets=[
            Asset(asset_id="A001", type="figure", image_path=str(first)),
            Asset(asset_id="A002", type="figure", image_path=str(second)),
            Asset(asset_id="A003", type="figure", image_path=""),
            Asset(asset_id="A004", type="page_screenshot", image_path=str(first)),
        ],
        doc_block_plan=DocumentBlockPlan(blocks=[DocumentBlock(
            doc_block_id="DB001",
            title="Figure section",
            linked_asset_ids=["A002", "A004"],
        )]),
    )
    evidence = EvidenceState(figures=[
        FigureRef(
            figure_id="fig_p7_img0",
            source_file="paper.pdf",
            image_path=str(first),
            figure_type="raster",
        ),
        FigureRef(
            figure_id="fig_p10_img1",
            source_file="paper.pdf",
            image_path=str(second),
            figure_type="raster",
        ),
    ])
    blueprint = _blueprint(
        _slide(
            1,
            assigned_figure_id="fig_p7_img0",
            asset_ids=["fig_p7_img0"],
        ),
        _slide(2, linked_evidence_ids=["A001", "A002"]),
        _slide(3, source_doc_block_ids=["DB001"]),
    )

    DeckPlanner._assign_figures(blueprint, evidence, source_store)

    assert blueprint.slides[0].assigned_figure_id == "A001"
    assert blueprint.slides[0].asset_ids == ["A001"]
    assert blueprint.slides[1].assigned_figure_id == "A002"
    assert blueprint.slides[1].asset_ids == ["A002"]
    assert blueprint.slides[2].assigned_figure_id == ""


def test_case_loader_supplements_empty_cached_jpeg_without_duplicates(tmp_path):
    case_dir = tmp_path / "case"
    source_pack = case_dir / "source_pack"
    source_pack.mkdir(parents=True)
    jpeg = _write_figure(
        source_pack, "fig_p7_img0", ".jpeg", page=7, bbox=[1, 2, 3, 4],
    )
    cached = SourceStore(assets=[Asset(
        asset_id="A001",
        type="figure",
        page=7,
        image_path="",
        bbox=[1, 2, 3, 4],
    )])
    source_pack.joinpath("source_store.json").write_text(
        cached.model_dump_json(indent=2)
    )

    evidence = CaseLoader(tmp_path)._load_evidence(case_dir)

    matches = [fig for fig in evidence.figures if Path(fig.image_path) == jpeg]
    assert len(matches) == 1
    assert matches[0].figure_id == "fig_p7_img0"
    assert matches[0].width == 640
    assert matches[0].height == 480
