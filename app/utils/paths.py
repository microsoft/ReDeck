"""Path management for runs and artifacts."""

from pathlib import Path

from .io_utils import ensure_dir


class RunPaths:
    """Manages all paths for a single run."""

    def __init__(self, base_dir: str | Path, run_id: str, runs_dir: str | Path | None = None):
        if runs_dir:
            self.base = Path(runs_dir) / run_id
        else:
            self.base = Path(base_dir) / "runs" / run_id
        ensure_dir(self.base)

    def turn_dir(self, turn_index: int) -> Path:
        d = self.base / f"turn_{turn_index:02d}"
        ensure_dir(d)
        return d

    def config_path(self) -> Path:
        return self.base / "experiment_config.json"

    # -- Per-turn paths --

    def blueprint_path(self, turn: int) -> Path:
        return self.turn_dir(turn) / "deck_blueprint.json"

    def compile_manifest_path(self, turn: int) -> Path:
        return self.turn_dir(turn) / "compile_manifest.json"

    def deck_pptx_path(self, turn: int) -> Path:
        return self.turn_dir(turn) / "deck.pptx"

    def render_dir(self, turn: int) -> Path:
        d = self.turn_dir(turn) / "render"
        ensure_dir(d)
        return d

    def render_pdf_dir(self, turn: int) -> Path:
        d = self.render_dir(turn) / "pdf"
        ensure_dir(d)
        return d

    def render_png_dir(self, turn: int) -> Path:
        d = self.render_dir(turn) / "slide_png"
        ensure_dir(d)
        return d

    def render_meta_path(self, turn: int) -> Path:
        return self.render_dir(turn) / "render_meta.json"

    def eval_dir(self, turn: int) -> Path:
        d = self.turn_dir(turn) / "eval"
        ensure_dir(d)
        return d

    def issues_path(self, turn: int) -> Path:
        return self.eval_dir(turn) / "issues.jsonl"

    def rubric_reports_dir(self, turn: int) -> Path:
        d = self.eval_dir(turn) / "rubric_reports"
        ensure_dir(d)
        return d

    def repair_dir(self, turn: int) -> Path:
        d = self.turn_dir(turn) / "repair"
        ensure_dir(d)
        return d

    def repair_units_dir(self, turn: int) -> Path:
        d = self.repair_dir(turn) / "repair_units"
        ensure_dir(d)
        return d

    def patch_results_dir(self, turn: int) -> Path:
        d = self.repair_dir(turn) / "patch_results"
        ensure_dir(d)
        return d

    def verify_dir(self, turn: int) -> Path:
        d = self.turn_dir(turn) / "verify"
        ensure_dir(d)
        return d

    def verify_reports_path(self, turn: int) -> Path:
        return self.verify_dir(turn) / "verify_reports.json"

    def turn_summary_path(self, turn: int) -> Path:
        return self.turn_dir(turn) / "turn_summary.json"

    def module_logs_path(self, turn: int) -> Path:
        return self.turn_dir(turn) / "module_logs.jsonl"

    def extractions_path(self, turn: int) -> Path:
        return self.turn_dir(turn) / "extractions.json"

    def input_packet_path(self, turn: int) -> Path:
        return self.turn_dir(turn) / "input_packet.json"
