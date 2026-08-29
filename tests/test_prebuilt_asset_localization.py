from pathlib import Path

from app.orchestrator.run_manager import RunManager
from app.utils.paths import RunPaths


def test_prebuilt_generated_assets_are_copied_and_made_turn_local(tmp_path):
    prebuilt_turn = tmp_path / "old_run" / "turn_01"
    src_code_dir = prebuilt_turn / "slide_code"
    asset_dir = prebuilt_turn / "generated_assets"
    src_code_dir.mkdir(parents=True)
    asset_dir.mkdir()
    asset = asset_dir / "fig4_summary.svg"
    asset.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    manager = object.__new__(RunManager)
    manager.paths = RunPaths(tmp_path, "new_run", runs_dir=tmp_path / "runs")

    code = (
        '<html><body><img src="../generated_assets/fig4_summary.svg">'
        f'<image href="{asset}"></image></body></html>'
    )

    rewritten, copied = manager._localize_prebuilt_generated_assets(
        code=code,
        prebuilt_dir=prebuilt_turn,
        src_code_dir=src_code_dir,
        turn_index=0,
    )

    assert copied == 2
    assert rewritten.count('../generated_assets/fig4_summary.svg') == 2
    assert (Path(manager.paths.turn_dir(0)) / "generated_assets" / "fig4_summary.svg").exists()


def test_prebuilt_localization_finds_sibling_turn_assets(tmp_path):
    run_root = tmp_path / "old_run"
    prebuilt_turn = run_root / "turn_01"
    src_code_dir = prebuilt_turn / "slide_code"
    sibling_assets = run_root / "turn_00" / "generated_assets"
    src_code_dir.mkdir(parents=True)
    sibling_assets.mkdir(parents=True)
    (sibling_assets / "fig4_summary.svg").write_text("<svg></svg>", encoding="utf-8")

    manager = object.__new__(RunManager)
    manager.paths = RunPaths(tmp_path, "new_run", runs_dir=tmp_path / "runs")

    rewritten, copied = manager._localize_prebuilt_generated_assets(
        code='<img src="../generated_assets/fig4_summary.svg">',
        prebuilt_dir=prebuilt_turn,
        src_code_dir=src_code_dir,
        turn_index=0,
    )

    assert copied == 1
    assert rewritten == '<img src="../generated_assets/fig4_summary.svg">'
    assert (manager.paths.turn_dir(0) / "generated_assets" / "fig4_summary.svg").exists()


def test_generated_assets_are_carried_forward_between_turns(tmp_path):
    manager = object.__new__(RunManager)
    manager.paths = RunPaths(tmp_path, "new_run", runs_dir=tmp_path / "runs")
    src_dir = manager.paths.turn_dir(0) / "generated_assets"
    src_dir.mkdir(parents=True)
    (src_dir / "fig4_summary.svg").write_text("<svg></svg>", encoding="utf-8")

    copied = manager._carry_forward_generated_assets(1)

    assert copied == 1
    assert (manager.paths.turn_dir(1) / "generated_assets" / "fig4_summary.svg").exists()
