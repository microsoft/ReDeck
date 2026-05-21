"""Run configuration schema for deck generation and repair."""

from pydantic import BaseModel, ConfigDict, Field

from .common import (
    EvalSplitLevel,
    RenderBackendType,
)


class ModelConfig(BaseModel):
    """Per-module model configuration.

    Each field overrides the default model for that specific module.
    Set to None (or omit) to use the default model.
    """

    model_config = ConfigDict(extra="ignore")

    default: str = "gpt-4o"
    deck_planner: str | None = None
    slide_codegen: str | None = None
    narrative_judge: str | None = None
    visual_judge: str | None = None
    completeness_judge: str | None = None
    correctness_judge: str | None = None
    fidelity_judge: str | None = None
    probe_planner: str | None = None
    probe_runner: str | None = None

    def get_model(self, module_name: str) -> str:
        """Get model for a specific module, falling back to default."""
        return getattr(self, module_name, None) or self.default


class EvalMode(BaseModel):
    """Evaluation pipeline configuration."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    split_level: EvalSplitLevel = EvalSplitLevel.FAMILY_PLUS_SLIDE
    use_judge_agent: bool = Field(
        default=True,
        description=(
            "When True, C/D/E judges use a multi-turn agent loop with "
            "search_source and lookup_table tools to verify claims before "
            "reporting issues. Reduces false positives but increases LLM calls."
        ),
    )
    use_probe_planner: bool = Field(
        default=True,
        description=(
            "When True, evaluation uses a ProbePlannerAgent that "
            "sees rendered slide PNGs and selectively schedules probe "
            "checks from a two-layer catalog (~237 atomic checks). "
            "Implements the adaptive planner π(b) from the MGIR paper."
        ),
    )
    visual_batch_size: int = Field(
        default=3,
        description="Number of slides per visual judge batch.",
    )
    source_budget_chars: int = Field(
        default=48000,
        description="Total character budget for source evidence bundling.",
    )
    chunk_max_chars: int = Field(
        default=4000,
        description="Max chars per evidence chunk in source bundle.",
    )


class RenderMode(BaseModel):
    """Render backend configuration."""

    fast_backend: RenderBackendType = RenderBackendType.LINUX_LO_PDF
    reference_backend: RenderBackendType = RenderBackendType.LINUX_LO_PDF


class ExperimentConfig(BaseModel):
    """Complete configuration for a run.

    Active fields:
    - run_id: unique identifier for this run
    - ablation_tags: optional metadata tags for run grouping
    - models: per-module model overrides
    - eval_mode: evaluation pipeline switches
    - render_mode: rendering backend selection
    - max_turns: total turns (turn 0 = generate, turns 1+ = evaluate+repair)
    - use_html_codegen: HTML/CSS codegen path
    - repair_strategy: "redeck" (agentic) or "baseline" (naive)
    - layout_strategy: "template" | "constraint" | "freeform" | "none"
    - prebuilt_turn0_dir: skip generation, reuse existing T0 artifacts
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str
    ablation_tags: list[str] = Field(default_factory=list)
    models: ModelConfig = Field(default_factory=ModelConfig)
    eval_mode: EvalMode = Field(default_factory=EvalMode)
    render_mode: RenderMode = Field(default_factory=RenderMode)
    max_turns: int = Field(default=10, description="Maximum turns (T0=gen, T1+=repair)")
    early_stop_turn: int = Field(
        default=6,
        description="Earliest turn to check plateau-based early stopping.",
    )
    plateau_window: int = Field(
        default=4,
        description="Number of past turns to compare for plateau detection.",
    )
    auto_keep_turn: int = Field(
        default=2,
        description="Turn at which persistent subjective issues get auto-KEEP.",
    )
    use_html_codegen: bool = Field(
        default=True,
        description=(
            "When True, use HTML/CSS code generation with Playwright rendering. "
            "The legacy python-pptx generator is not included in this release."
        ),
    )
    repair_strategy: str = Field(
        default="redeck",
        description=(
            "Repair strategy: 'redeck' (agentic local patching with regression "
            "protection) or 'baseline' (naive full-rewrite)."
        ),
    )
    layout_strategy: str = Field(
        default="template",
        description=(
            "Layout strategy: 'template' (fixed skeletons A-M), 'constraint' "
            "(solver-based), 'freeform' (LLM direct), 'none' (skip layout design)."
        ),
    )
    codegen_prompt: str | None = Field(
        default=None,
        description="Custom codegen system prompt name (without .system.md extension).",
    )
    show_source_citations: bool = Field(
        default=True,
        description=(
            "When True, data-heavy slides include a visible 'Source: Page X' footer "
            "citing the original document. Recommended for presentations where "
            "presentations where traceability matters."
        ),
    )
    prebuilt_turn0_dir: str | None = Field(
        default=None,
        description="Reuse T0 artifacts from this directory instead of generating.",
    )
