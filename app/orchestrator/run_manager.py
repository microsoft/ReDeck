"""RunManager - main orchestrator for the slide generation pipeline."""

import logging
import shutil
import time
from pathlib import Path

from ..llm_client import LLMClient
from ..schemas.common import Status
from ..schemas.blueprint import DeckBlueprint
from ..schemas.experiment_config import ExperimentConfig
from ..schemas.issue import Issue
from ..schemas.turn_summary import TurnSummary
from ..utils.io_utils import read_json, write_json, write_jsonl
from ..utils.paths import RunPaths

from ..modules.case_loader import CaseLoader
from ..modules.source_indexer import SourceIndexer
from ..modules.deck_planner import DeckPlanner
from ..modules.extractor import StructuralExtractor
from ..modules.issue_normalizer import IssueNormalizer
from ..backends.html_codegen.html_codegen_compiler import HtmlCodeGenCompiler
from ..modules.repairs.code_repair import CodeRepairWorker

from .render_manager import RenderManager
from .eval_router import EvalRouter
from .turn_settler import TurnSettler

logger = logging.getLogger(__name__)


class RunManager:
    """Orchestrates the complete slide generation pipeline."""

    def __init__(
        self,
        config: ExperimentConfig,
        cases_dir: str = "cases",
        base_dir: str = ".",
    ):
        self.config = config
        self.cases_dir = cases_dir
        self.paths = RunPaths(base_dir, config.run_id)

        # Initialize LLM client
        self.llm = LLMClient(
            default_model=config.models.default,
            log_path=self.paths.base / "llm_calls.jsonl",
        )

        # Initialize modules
        self.case_loader = CaseLoader(cases_dir)
        self.source_indexer = SourceIndexer(llm=self.llm)
        self.extractor = StructuralExtractor()
        self.issue_normalizer = IssueNormalizer()
        self.turn_settler = TurnSettler(
            early_stop_turn=self.config.early_stop_turn,
            plateau_window=self.config.plateau_window,
        )

        # Planning
        self.deck_planner = DeckPlanner(self.llm, config)

        # Render
        self.render_manager = RenderManager(config)

        # Eval
        self.eval_router = EvalRouter(self.llm, config)

        # CodeGen compiler
        model = config.models.get_model("slide_codegen") if hasattr(config.models, 'get_model') else config.models.default
        self.use_html_codegen = config.use_html_codegen
        self.codegen_compiler = HtmlCodeGenCompiler(self.llm, model=model, codegen_prompt=config.codegen_prompt, show_source_citations=config.show_source_citations)
        logger.info("Using HTML codegen compiler (Playwright rendering)")
        self.code_repair_worker = CodeRepairWorker(self.llm, model=model)

    def run(self, case_id: str) -> list[TurnSummary]:
        """Run the complete pipeline for a case."""
        logger.info("Starting run %s for case %s", self.config.run_id, case_id)

        # Save experiment config
        write_json(self.config, self.paths.config_path())

        # Load case
        case_state = self.case_loader.load(case_id)

        # Index sources
        case_state.evidence = self.source_indexer.index(case_state.case_dir)

        # Build SourceStore (new structured pipeline)
        try:
            from ..modules.source_store import build_source_store
            case_state.source_store = build_source_store(
                case_state.case_dir, self.llm,
            )
            logger.info(
                "SourceStore built: %d atomic blocks, %d doc blocks, %d assets",
                len(case_state.source_store.atomic_blocks),
                len(case_state.source_store.doc_block_plan.blocks),
                len(case_state.source_store.assets),
            )
        except Exception as e:
            logger.warning("SourceStore build failed, using legacy path: %s", e)
            case_state.source_store = None

        # Load paper_full.md for direct consumption by planner
        paper_md_path = Path(case_state.case_dir) / "source_pack" / "paper_full.md"
        self._paper_full_md = None
        if paper_md_path.exists():
            self._paper_full_md = paper_md_path.read_text(encoding="utf-8")
            logger.info("Loaded paper_full.md: %d chars", len(self._paper_full_md))

        # Get source summary for evaluators
        source_summary = self._build_source_summary(case_state)

        summaries = []
        previous_issues: list[Issue] = []
        self._cached_blueprint = None
        issue_count_history: list[int] = []  # track issue counts for stagnation detection
        best_turn: int = 0  # track globally best turn (fewest open issues)
        best_open: int = float("inf")  # issue count at best turn

        for turn in range(self.config.max_turns):
            logger.info("=== Turn %d ===", turn)
            turn_start = time.time()

            summary = self._run_turn(
                turn, case_state, source_summary, previous_issues,
                issue_count_history,
            )
            summary.timing_sec = time.time() - turn_start
            summaries.append(summary)

            # Save turn summary
            write_json(summary, self.paths.turn_summary_path(turn))

            # If turn errored, stop immediately — don't record as 0 issues
            if summary.status == Status.ERROR:
                logger.error(
                    "Turn %d errored: %s — stopping pipeline",
                    turn, summary.reason,
                )
                break

            # Track open issue counts for stagnation detection.
            # All severities are included so minor issues also drive repair.
            loaded_issues = self._load_issues(turn)
            open_count = sum(
                1 for i in loaded_issues
                if i.status.value == "open"
            )
            issue_count_history.append(open_count)

            # Track globally best turn
            if open_count <= best_open:
                best_open = open_count
                best_turn = turn

            if not summary.should_continue:
                logger.info("Stopping after turn %d: %s", turn, summary.reason)

                # Best-turn rollback: use the turn with fewest issues as
                # final output, not just the previous turn.
                if best_turn != turn:
                    self._rollback_to_turn(best_turn, turn, best_open, issue_count_history[-1])

                break

            # Carry issues forward
            previous_issues = self._load_issues(turn)

        # Best-turn rollback at loop end
        final_turn = len(summaries) - 1
        if final_turn > 0 and best_turn != final_turn and issue_count_history:
            self._rollback_to_turn(best_turn, final_turn, best_open, issue_count_history[-1])

        logger.info("Run completed: %d turns", len(summaries))
        return summaries

    def _rollback_to_turn(self, src_turn: int, dst_turn: int, src_issues: int, dst_issues: int):
        """Copy artifacts from a better turn to the final turn."""
        src_dir = self.paths.turn_dir(src_turn)
        dst_dir = self.paths.turn_dir(dst_turn)
        for artifact in ["slide_code", "html_renders", "slides.pdf", "deck.pptx"]:
            src = src_dir / artifact
            dst = dst_dir / artifact
            if src.exists():
                if src.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
        logger.info(
            "Best-turn rollback: T%d→T%d (%d vs %d issues)",
            src_turn, dst_turn, src_issues, dst_issues,
        )

    def _run_turn(
        self,
        turn_index: int,
        case_state,
        source_summary: str,
        previous_issues: list[Issue],
        issue_count_history: list[int] | None = None,
    ) -> TurnSummary:
        """Execute a turn using LLM code-generation compiler."""
        artifact_paths = {}
        repair_units = []  # codegen mode doesn't use repair_units
        repaired_slides = []  # track which slides were modified (for differential eval)

        try:
            # === SAVE INPUT PACKET ===
            input_packet = {
                "case_id": case_state.case_id,
                "turn_index": turn_index,
                "intent": case_state.intent.model_dump(),
                "evidence_summary": {
                    "num_chunks": len(case_state.evidence.chunks),
                    "num_figures": len(case_state.evidence.figures),
                    "num_tables": len(case_state.evidence.tables),
                    "num_numeric_facts": len(case_state.evidence.numeric_facts),
                    "num_entities": len(case_state.evidence.entity_registry),
                    **(
                        {
                            "num_atomic_blocks": len(case_state.source_store.atomic_blocks),
                            "num_doc_blocks": len(case_state.source_store.doc_block_plan.blocks),
                            "num_assets": len(case_state.source_store.assets),
                        }
                        if case_state.source_store
                        else {}
                    ),
                },
                "task_brief_length": len(case_state.task_brief),
                "previous_issues_count": len(previous_issues),
            }
            write_json(input_packet, self.paths.input_packet_path(turn_index))

            code_dir = self.paths.turn_dir(turn_index) / "slide_code"
            code_dir.mkdir(parents=True, exist_ok=True)

            if turn_index == 0 and self.config.prebuilt_turn0_dir:
                # === PREBUILT TURN 0: Load from shared directory ===
                return self._load_prebuilt_turn0(
                    case_state, source_summary, code_dir, artifact_paths,
                    issue_count_history,
                )

            if turn_index == 0:
                # === TURN 0: PLAN + (OPTIONAL) LAYOUT DESIGN + GENERATE ===
                # Only plan once — blueprint drives all subsequent turns
                blueprint = self.deck_planner.plan(
                    case_state.intent, case_state.evidence, case_state.task_brief,
                    paper_full_md=self._paper_full_md,
                    source_store=case_state.source_store,
                )
                self._cached_blueprint = blueprint
                write_json(blueprint, self.paths.blueprint_path(turn_index))

                # === BUILD SOURCE BUNDLES (if SourceStore available) ===
                if case_state.source_store is not None:
                    try:
                        from ..modules.source_store.bundle_builder import SlideSourceBundleBuilder
                        deck_plan = [
                            {
                                "slide_id": s.slide_id,
                                "slide_title": s.primary_proposition,
                                "source_doc_block_ids": s.source_doc_block_ids or [
                                    eid for eid in s.linked_evidence_ids
                                    if eid.startswith("DB")
                                ],
                                "asset_ids": s.asset_ids or [
                                    eid for eid in s.linked_evidence_ids
                                    if eid.startswith("A")
                                ],
                                "table_ids": s.table_ids or [
                                    eid for eid in s.linked_evidence_ids
                                    if eid.startswith("T")
                                ],
                            }
                            for s in blueprint.slides
                        ]
                        bundle_builder = SlideSourceBundleBuilder()
                        bundles = bundle_builder.build(
                            deck_plan,
                            case_state.source_store.doc_block_plan,
                            case_state.source_store.atomic_blocks,
                            case_state.source_store.assets,
                            case_state.source_store.table_data,
                        )
                        case_state.source_store.bundles = {
                            b.slide_id: b for b in bundles
                        }
                        logger.info("Built %d source bundles", len(bundles))
                    except Exception as e:
                        logger.warning("Bundle build failed: %s", e)

                # Generate code for all slides
                pptx_path = str(self.paths.deck_pptx_path(turn_index))
                manifest = self.codegen_compiler.compile_deck(
                    blueprint=blueprint,
                    evidence=case_state.evidence,
                    case_dir=str(case_state.case_dir),
                    output_path=pptx_path,
                    code_dir=str(code_dir),
                    source_store=case_state.source_store,
                    task_brief=case_state.task_brief,
                )
                write_json(manifest, self.paths.compile_manifest_path(turn_index))
                artifact_paths["pptx"] = pptx_path

            else:
                # === TURN 1+: REPAIR CODE ===
                blueprint = self._cached_blueprint
                # Fallback: reload from disk if in-memory cache was lost
                if blueprint is None:
                    bp_path = self.paths.blueprint_path(0)
                    if bp_path.exists():
                        blueprint = DeckBlueprint.model_validate(read_json(bp_path))
                        self._cached_blueprint = blueprint
                        logger.info("Reloaded blueprint from disk: %s", bp_path)
                    else:
                        raise RuntimeError(
                            f"Blueprint not found in cache or on disk at {bp_path}"
                        )

                # Repair slides with issues
                if self.config.repair_strategy == "redeck":
                    from ..modules.redeck.repair_worker import ReDeckRepairWorker
                    _model = self.config.models.get_model("slide_codegen")
                    redeck_worker = ReDeckRepairWorker(self.llm, model=_model)
                    repaired_slides = redeck_worker.repair_slides(
                        codegen_compiler=self.codegen_compiler,
                        issues=previous_issues,
                        blueprint_slides=blueprint.slides,
                        evidence=case_state.evidence,
                        case_dir=str(case_state.case_dir),
                        run_dir=str(self.paths.base),
                        turn_index=turn_index,
                        source_store=case_state.source_store,
                    )
                    content_modified_slides = redeck_worker.content_modified_slides
                    logger.info(
                        "Repaired %d slides via ReDeck (%d with content changes)",
                        len(repaired_slides), len(content_modified_slides),
                    )
                else:
                    repaired_slides = self.code_repair_worker.repair_slides(
                        codegen_compiler=self.codegen_compiler,
                        issues=previous_issues,
                        blueprint_slides=blueprint.slides,
                        evidence=case_state.evidence,
                        case_dir=str(case_state.case_dir),
                    )
                    # Baseline repair: assume all repaired slides have content changes
                    content_modified_slides = set(repaired_slides)
                    logger.info("Repaired %d slides via baseline code repair", len(repaired_slides))

                # Recompile the whole deck with updated code
                pptx_path = str(self.paths.deck_pptx_path(turn_index))
                manifest = self.codegen_compiler.recompile_deck(
                    blueprint=blueprint,
                    case_dir=str(case_state.case_dir),
                    output_path=pptx_path,
                    code_dir=str(code_dir),
                    evidence=case_state.evidence,
                    source_store=case_state.source_store,
                )
                write_json(manifest, self.paths.compile_manifest_path(turn_index))
                artifact_paths["pptx"] = pptx_path

                # Create pseudo repair units for the settler
                from ..schemas.repair_unit import RepairUnit
                for sid in repaired_slides:
                    repair_units.append(RepairUnit(
                        repair_unit_id=f"code_repair_slide_{sid}",
                        issue_cluster=[],
                        repair_type="code_repair",
                        affected_slides=[sid],
                        verify_targets=[],
                        status="applied",
                    ))

            # === RENDER ===
            render_dir = str(self.paths.render_dir(turn_index))
            if self.use_html_codegen:
                # HTML mode: PNGs already rendered by HtmlCodeGenCompiler.
                # Just copy them to render_dir and assemble PDF.
                render_result = self._html_render(
                    code_dir, render_dir, turn_index,
                )
            else:
                render_result = self.render_manager.render_fast(pptx_path, render_dir)
            if render_result.render_meta:
                write_json(render_result.render_meta,
                          self.paths.render_meta_path(turn_index))
            artifact_paths["render_dir"] = render_dir

            # === EXTRACT ===
            if self.use_html_codegen:
                # HTML mode: extract from HTML code + DOM rather than PPTX
                extractions = self._extract_from_html(turn_index)
            else:
                extractions = self.extractor.extract(pptx_path)
            write_json([e.model_dump() for e in extractions],
                      self.paths.extractions_path(turn_index))

            # === EVALUATE ===
            png_paths = render_result.png_paths or []
            # Use differential evaluation for repair turns
            modified_slide_ids = set(repaired_slides) if turn_index > 0 else None
            # content_modified_slides: slides where text content changed
            # (not just CSS/layout). C/D/E judges only need to re-evaluate
            # these — spatial-only fixes don't affect content accuracy.
            content_modified_ids = (
                content_modified_slides if turn_index > 0 else None
            )
            issues = self.eval_router.evaluate(
                extractions, png_paths,
                case_state.task_brief, source_summary,
                blueprint=self._cached_blueprint,
                evidence=case_state.evidence,
                previous_issues=previous_issues if turn_index > 0 else None,
                modified_slides=modified_slide_ids,
                turn_index=turn_index,
                slide_codes=dict(self.codegen_compiler.slide_codes) if self.use_html_codegen else None,
                run_dir=str(self.paths.base),
                source_store=case_state.source_store,
                content_modified_slides=content_modified_ids,
            )
            # Build slide→evidence mapping for D/E issue actionability filter
            slide_evidence_map: dict[int, set[str]] = {}
            if blueprint:
                for bp_slide in blueprint.slides:
                    slide_evidence_map[bp_slide.slide_id] = set(
                        bp_slide.linked_evidence_ids or []
                    )
            issues = self.issue_normalizer.normalize(
                issues, slide_evidence_map=slide_evidence_map,
            )

            # === ISSUE MATCHING (turn 1+): track recurring vs resolved issues ===
            if turn_index > 0 and previous_issues:
                issues = self._match_and_merge_issues(issues, previous_issues)

            # Auto-KEEP persistent subjective issues (A3, A5) that have
            # persisted 2+ consecutive turns — these are beyond repair scope.
            if turn_index >= self.config.auto_keep_turn:
                issues = self._auto_keep_persistent_issues(issues, turn_index)

            write_jsonl(issues, self.paths.issues_path(turn_index))
            artifact_paths["issues"] = str(self.paths.issues_path(turn_index))

            # === SETTLE ===
            verify_report = None
            summary = self.turn_settler.settle(
                turn_index, issues, previous_issues,
                repair_units, verify_report, artifact_paths,
                previous_issue_counts=issue_count_history,
            )
            return summary

        except Exception as e:
            logger.error("Turn %d failed: %s", turn_index, e, exc_info=True)
            return TurnSummary(
                turn_index=turn_index,
                status=Status.ERROR,
                reason=f"Turn failed: {e}",
                should_continue=False,
                artifact_paths=artifact_paths,
            )

    def _load_prebuilt_turn0(
        self,
        case_state,
        source_summary: str,
        code_dir: Path,
        artifact_paths: dict,
        issue_count_history: list[int] | None = None,
    ) -> TurnSummary:
        """Load Turn 0 artifacts from a pre-built directory.

        Used for A/B comparison experiments: both baseline and ReDeck
        start from the exact same T0 code, so the only difference is
        the repair strategy.

        Copies: blueprint, layout designs, slide code, PPTX, issues.
        Re-runs: render and evaluation (to match current run's paths).
        """
        import shutil

        prebuilt_dir = Path(self.config.prebuilt_turn0_dir)
        logger.info("Loading prebuilt Turn 0 from %s", prebuilt_dir)

        # 1. Load blueprint
        bp_path = prebuilt_dir / "blueprint.json"
        if not bp_path.exists():
            bp_path = prebuilt_dir / "deck_blueprint.json"
        if not bp_path.exists():
            bp_path = prebuilt_dir / "turn_00" / "deck_blueprint.json"
        blueprint = DeckBlueprint.model_validate(read_json(bp_path))

        self._cached_blueprint = blueprint
        write_json(blueprint, self.paths.blueprint_path(0))

        # 1b. Backfill source_doc_block_ids & build bundles (prebuilt compat)
        if case_state.source_store is not None:
            needs_backfill = any(
                not s.source_doc_block_ids for s in blueprint.slides
            )
            if needs_backfill:
                self._backfill_source_doc_block_ids(
                    blueprint, case_state.source_store,
                    prebuilt_dir / "slide_code",
                )
                logger.info("Backfilled source_doc_block_ids for prebuilt blueprint")
            try:
                from ..modules.source_store.bundle_builder import SlideSourceBundleBuilder
                deck_plan = [
                    {
                        "slide_id": s.slide_id,
                        "slide_title": s.primary_proposition,
                        "source_doc_block_ids": s.source_doc_block_ids or [
                            eid for eid in s.linked_evidence_ids
                            if eid.startswith("DB")
                        ],
                        "asset_ids": s.asset_ids or [
                            eid for eid in s.linked_evidence_ids
                            if eid.startswith("A")
                        ],
                        "table_ids": s.table_ids or [
                            eid for eid in s.linked_evidence_ids
                            if eid.startswith("T")
                        ],
                    }
                    for s in blueprint.slides
                ]
                bundle_builder = SlideSourceBundleBuilder()
                bundles = bundle_builder.build(
                    deck_plan,
                    case_state.source_store.doc_block_plan,
                    case_state.source_store.atomic_blocks,
                    case_state.source_store.assets,
                    case_state.source_store.table_data,
                )
                case_state.source_store.bundles = {
                    b.slide_id: b for b in bundles
                }
                logger.info("Built %d source bundles for prebuilt T0", len(bundles))
            except Exception as e:
                logger.warning("Bundle build failed for prebuilt: %s", e)

        # 2. Copy slide code files and load into codegen compiler
        src_code_dir = prebuilt_dir / "slide_code"
        if not src_code_dir.exists():
            src_code_dir = prebuilt_dir / "turn_00" / "slide_code"

        code_ext = "html" if self.use_html_codegen else "py"
        for src_file in sorted(src_code_dir.glob(f"slide_*.{code_ext}")):
            dst_file = code_dir / src_file.name
            shutil.copy2(src_file, dst_file)
            # Parse slide_id from filename: slide_01.py/html → 1
            sid = int(src_file.stem.split("_")[1])
            code = src_file.read_text(encoding="utf-8")
            self.codegen_compiler.slide_codes[sid] = code

        logger.info(
            "Loaded %d slide codes from prebuilt",
            len(self.codegen_compiler.slide_codes),
        )

        # Ensure task_brief is available for any subsequent repair turns
        self.codegen_compiler._task_brief = case_state.task_brief

        # 3. Recompile PPTX from loaded code (ensures consistent rendering)
        pptx_path = str(self.paths.deck_pptx_path(0))
        manifest = self.codegen_compiler.recompile_deck(
            blueprint=blueprint,
            case_dir=str(case_state.case_dir),
            output_path=pptx_path,
            code_dir=str(code_dir),
            evidence=case_state.evidence,
            source_store=case_state.source_store,
        )
        write_json(manifest, self.paths.compile_manifest_path(0))
        artifact_paths["pptx"] = pptx_path

        # 4. Render
        render_dir = str(self.paths.render_dir(0))
        render_result = self.render_manager.render_fast(pptx_path, render_dir)
        if render_result.render_meta:
            write_json(render_result.render_meta, self.paths.render_meta_path(0))
        artifact_paths["render_dir"] = render_dir

        # Validate render: abort if no PNGs were produced (e.g. LibreOffice lock contention)
        png_paths = render_result.png_paths or []
        if not png_paths:
            logger.error(
                "Prebuilt T0 render produced 0 PNGs (likely LibreOffice race condition). "
                "Falling back to copying evaluation results from prebuilt dir."
            )

        # 5. Extract
        extractions = self.extractor.extract(pptx_path)
        write_json(
            [e.model_dump() for e in extractions],
            self.paths.extractions_path(0),
        )

        # 6. Copy evaluation results from prebuilt dir (ensures identical T0 for A/B comparison)
        #    We do NOT re-evaluate because: (a) LLM judges are non-deterministic,
        #    (b) render failures would silently degrade visual evaluation.
        #    Prefer issues_v6.jsonl (re-evaluated with per-slide evidence).
        src_issues_path = None
        for candidate in [
            prebuilt_dir / "eval" / "issues_v6.jsonl",
            prebuilt_dir / "eval" / "issues.jsonl",
            prebuilt_dir / "issues_v6.jsonl",
            prebuilt_dir / "issues.jsonl",
            prebuilt_dir / "turn_00" / "eval" / "issues_v6.jsonl",
            prebuilt_dir / "turn_00" / "eval" / "issues.jsonl",
        ]:
            if candidate.exists():
                src_issues_path = candidate
                break

        if src_issues_path and src_issues_path.exists():
            import shutil
            dst_issues_path = self.paths.issues_path(0)
            shutil.copy2(src_issues_path, dst_issues_path)
            logger.info("Copied prebuilt T0 issues from %s (%d bytes)",
                       src_issues_path, src_issues_path.stat().st_size)
            # Load the copied issues
            issues = self._load_issues(0)
        else:
            # Fallback: re-evaluate if no prebuilt issues found
            logger.warning(
                "No prebuilt issues.jsonl found at %s, falling back to fresh evaluation",
                src_issues_path,
            )
            issues = self.eval_router.evaluate(
                extractions, png_paths,
                case_state.task_brief, source_summary,
                blueprint=blueprint,
                evidence=case_state.evidence,
                slide_codes=dict(self.codegen_compiler.slide_codes) if self.use_html_codegen else None,
                run_dir=str(self.paths.base),
                source_store=case_state.source_store,
            )
            # Build slide→evidence mapping for D/E actionability filter
            prebuilt_evidence_map: dict[int, set[str]] = {}
            for bp_slide in blueprint.slides:
                prebuilt_evidence_map[bp_slide.slide_id] = set(
                    bp_slide.linked_evidence_ids or []
                )
            issues = self.issue_normalizer.normalize(
                issues, slide_evidence_map=prebuilt_evidence_map,
            )
            write_jsonl(issues, self.paths.issues_path(0))

        artifact_paths["issues"] = str(self.paths.issues_path(0))

        # 7. Settle
        repair_units = []
        summary = self.turn_settler.settle(
            0, issues, [],
            repair_units, None, artifact_paths,
            previous_issue_counts=issue_count_history,
        )
        return summary

    def _backfill_source_doc_block_ids(self, blueprint, source_store, code_dir=None):
        """Assign source_doc_block_ids to slides that lack them.

        Uses keyword matching between slide content/title and DocumentBlock
        summaries.  Needed for prebuilt blueprints from gen_frontend which
        don't record source provenance.
        """
        import re as _re

        doc_blocks = source_store.doc_block_plan.blocks
        code_dir = Path(code_dir) if code_dir else None

        for bp_slide in blueprint.slides:
            if bp_slide.source_doc_block_ids:
                continue  # already has linkage

            # Build keyword set from slide title
            keywords: set[str] = set()
            prop = bp_slide.primary_proposition or ""
            for word in _re.split(r'\W+', prop.lower()):
                if len(word) > 3:
                    keywords.add(word)

            # Also extract keywords from slide HTML if available
            if code_dir:
                html_path = code_dir / f"slide_{bp_slide.slide_id:02d}.html"
                if html_path.exists():
                    html = html_path.read_text(encoding="utf-8", errors="replace")
                    text = _re.sub(r'<[^>]+>', ' ', html)
                    text = _re.sub(r'\s+', ' ', text)
                    for word in _re.split(r'\W+', text.lower()):
                        if len(word) > 4:
                            keywords.add(word)

            if not keywords:
                continue

            # Score each doc block by keyword overlap
            scored: list[tuple[int, str]] = []
            for db in doc_blocks:
                db_text = ((db.title or "") + " " + (db.summary or "")).lower()
                overlap = sum(1 for kw in keywords if kw in db_text)
                if overlap > 0:
                    scored.append((overlap, db.doc_block_id))

            scored.sort(reverse=True)
            bp_slide.source_doc_block_ids = [
                dbid for _, dbid in scored[:3]
            ]

    def _build_source_summary(self, case_state) -> str:
        """Build structured source summary for evaluators.

        Organizes evidence by section headings with chunk_id annotations,
        so evaluators can trace slide claims back to specific source chunks.

        Budget: 48K chars total, max 4000 chars per chunk.
        Also includes table data previews (up to 600 chars each).
        """
        parts = []
        budget = self.config.eval_mode.source_budget_chars
        used = 0

        for chunk in case_state.evidence.chunks:
            section = chunk.metadata.get(
                "section", chunk.metadata.get("heading", "")
            )
            header = (
                f"[{chunk.chunk_id}] {section}" if section else f"[{chunk.chunk_id}]"
            )
            content = chunk.content.strip()
            max_chunk = min(self.config.eval_mode.chunk_max_chars, budget - used - len(header) - 10)
            if max_chunk <= 100:
                break
            if len(content) > max_chunk:
                content = content[:max_chunk] + "..."
            entry = f"### {header}\n{content}"
            parts.append(entry)
            used += len(entry)

        # Append table summaries with data if budget allows
        if case_state.evidence.tables and used < budget - 500:
            parts.append("\n## Tables")
            for tbl in case_state.evidence.tables[:8]:
                cap = tbl.caption or tbl.table_id
                desc = f" — {tbl.description}" if tbl.description else ""
                tbl_content = (tbl.content or "")[:600]
                entry = f"[{tbl.table_id}] {cap}{desc}\n{tbl_content}"
                if used + len(entry) > budget:
                    break
                parts.append(entry)
                used += len(entry)

        return "\n\n".join(parts)

    def _load_issues(self, turn_index: int) -> list[Issue]:
        """Load issues from a turn's JSONL file."""
        path = self.paths.issues_path(turn_index)
        if not path.exists():
            return []
        from ..utils.io_utils import read_jsonl
        items = read_jsonl(path)
        return [Issue.model_validate(item) for item in items]

    def _match_and_merge_issues(
        self, new_issues: list[Issue], prev_issues: list[Issue]
    ) -> list[Issue]:
        """Merge judge-triaged issues with simple accounting.

        Since judges now receive previous issues and return verdicts
        (RESOLVED / PERSISTED / WORSENED) directly, this method only
        needs to log statistics. The heavy matching logic is no longer
        needed — judges handle it via previous_issue_verdicts.
        """
        from ..schemas.common import IssueStatus

        resolved_count = sum(
            1 for i in new_issues if i.status == IssueStatus.RESOLVED
        )
        open_count = sum(
            1 for i in new_issues if i.status == IssueStatus.OPEN
        )
        # Issues with resolved_at_turn set are triaged previous issues;
        # the rest are genuinely new issues or persisted ones.
        triaged_count = sum(
            1 for i in new_issues if i.resolved_at_turn is not None
        )

        logger.info(
            "Issue tracking (judge-driven): %d open, %d resolved, "
            "%d triaged from previous (of %d total)",
            open_count, resolved_count, triaged_count, len(new_issues),
        )

        return new_issues

    @staticmethod
    def _auto_keep_persistent_issues(
        issues: list[Issue], turn_index: int
    ) -> list[Issue]:
        """Auto-KEEP subjective issues that persist across 2+ turns.

        Issues like poor_flow (A3) are deck-level architectural choices
        that the repair agent cannot fix incrementally. If they persist
        after multiple repair attempts, mark them KEEP to stop wasting
        repair budget on them.

        NOTE: density_imbalance (formerly text_density) IS repairable now that the
        repair agent is allowed to condense content.
        """
        from ..schemas.common import RepairAction

        from ..schemas.issue_types import AUTO_KEEP_TYPES

        for iss in issues:
            if (
                iss.issue_type in AUTO_KEEP_TYPES
                and iss.status.value == "open"
                and "[PERSISTED]" in (iss.planned_fix or "")
                and iss.recommended_action != RepairAction.KEEP
            ):
                iss.recommended_action = RepairAction.KEEP
                iss.action_rationale = (
                    f"Auto-KEEP: {iss.issue_type} persisted through turn "
                    f"{turn_index}, beyond repair agent scope"
                )
                logger.info(
                    "Auto-KEEP applied to %s [%s] — persistent subjective issue",
                    iss.issue_id, iss.issue_type,
                )

        return issues

    # ------------------------------------------------------------------
    # HTML-mode helpers
    # ------------------------------------------------------------------

    def _html_render(self, code_dir, render_dir: str, turn_index: int):
        """Render HTML slides to PNGs and assemble PDF.

        In HTML mode, the HtmlCodeGenCompiler already renders PNGs into
        code_dir.parent / html_renders/. We copy them to the standard
        render output location and assemble a PDF.
        """
        from ..schemas.common import Status
        from ..schemas.render_result import RenderResult
        from ..render_backends.playwright_backend import PlaywrightRenderBackend

        png_src_dir = Path(code_dir).parent / "html_renders"
        png_out_dir = Path(render_dir) / "slide_png"
        pdf_dir = Path(render_dir) / "pdf"
        png_out_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)

        import shutil
        png_paths = []
        if png_src_dir.exists():
            for png in sorted(png_src_dir.glob("slide_*.png")):
                dst = png_out_dir / png.name
                shutil.copy2(png, dst)
                png_paths.append(str(dst))
        else:
            logger.warning(
                "HTML render directory not found: %s — "
                "HtmlCodeGenCompiler may not have produced output.",
                png_src_dir,
            )

        if not png_paths:
            logger.error(
                "No slide PNGs found in %s — check HtmlCodeGenCompiler output.",
                png_src_dir,
            )

        # Assemble PDF
        pdf_path = str(pdf_dir / "deck.pdf")
        if png_paths:
            backend = PlaywrightRenderBackend()
            backend.assemble_pngs_to_pdf(png_paths, pdf_path)

        # Also create slides.pdf in the turn results directory.
        slides_pdf = Path(render_dir).parent / "slides.pdf"
        if Path(pdf_path).exists():
            shutil.copy2(pdf_path, slides_pdf)

        return RenderResult(
            backend_name="playwright",
            status=Status.OK if png_paths else Status.ERROR,
            pdf_path=pdf_path if Path(pdf_path).exists() else "",
            png_paths=png_paths,
            slide_count=len(png_paths),
        )

    def _extract_from_html(self, turn_index: int):
        """Extract slide structure from HTML codes for geom checks.

        Returns a list of SlideExtraction objects built from HTML content
        analysis. Tries Playwright for real DOM bounding boxes; falls back
        to approximate coordinates if unavailable.
        """
        from ..schemas.extraction import ExtractedObject, SlideExtraction
        from ..schemas.issue_types import SlideDimensions
        from ..utils.html_text import extract_title_and_body
        import re

        # Try to get real DOM layout from Playwright
        pw_states: dict[int, object] = {}
        try:
            from ..modules.redeck.html_spatial_state import extract_html_slide_state
            for sid, html in sorted(self.codegen_compiler.slide_codes.items()):
                try:
                    state = extract_html_slide_state(sid, html)
                    pw_states[sid] = state
                except Exception as e:
                    logger.debug("Playwright extraction failed for slide %d: %s", sid, e)
        except ImportError:
            logger.debug("html_spatial_state not available, using approximate bboxes")

        extractions = []
        for sid, html in sorted(self.codegen_compiler.slide_codes.items()):
            title, body = extract_title_and_body(html)

            # Combine for total text length
            text_only = f"{title} {body}".strip()

            # Count images
            img_count = len(re.findall(r'<img\b', html, re.IGNORECASE))

            # Build objects from Playwright real DOM blocks if available
            objects = []
            pw_state = pw_states.get(sid)

            if pw_state and hasattr(pw_state, 'blocks') and pw_state.blocks:
                emu = SlideDimensions.EMU_PER_INCH  # blocks are in inches, not pixels
                for blk in pw_state.blocks:
                    obj_type = "text_box"
                    has_img = False
                    if blk.shape_type in ("picture", "image"):
                        obj_type = "picture"
                        has_img = True
                    elif blk.shape_type in ("chart", "table"):
                        obj_type = blk.shape_type

                    objects.append(ExtractedObject(
                        object_id=blk.block_id,
                        shape_name=blk.var_name or blk.block_id,
                        object_type=obj_type,
                        bbox_emu=[
                            int(blk.x * emu), int(blk.y * emu),
                            int(blk.w * emu), int(blk.h * emu),
                        ],
                        text_content=" ".join(blk.text_lines) if blk.text_lines else '',
                        font_sizes_pt=[18.0],
                        has_image=has_img,
                        z_order=0,
                    ))
            else:
                # Fallback: approximate bboxes
                if title:
                    objects.append(ExtractedObject(
                        object_id=f"slide_{sid}_title",
                        shape_name="title",
                        object_type="text_box",
                        bbox_emu=[457200, 228600, 11430000, 914400],
                        text_content=title,
                        font_sizes_pt=[28.0],
                        z_order=0,
                    ))
                if body:
                    objects.append(ExtractedObject(
                        object_id=f"slide_{sid}_body",
                        shape_name="body",
                        object_type="text_box",
                        bbox_emu=[457200, 1371600, 11430000, 4572000],
                        text_content=body,
                        font_sizes_pt=[18.0],
                        z_order=1,
                    ))
                for i, img_match in enumerate(re.finditer(r'<img\s[^>]*src=["\']([^"\']+)["\']', html)):
                    objects.append(ExtractedObject(
                        object_id=f"slide_{sid}_img_{i}",
                        shape_name=f"image_{i}",
                        object_type="picture",
                        bbox_emu=[6096000, 1371600, 5334000, 4572000],
                        has_image=True,
                        image_path=img_match.group(1),
                        z_order=10 + i,
                    ))

            extractions.append(SlideExtraction(
                slide_id=sid,
                slide_index=sid - 1,
                title=title,
                objects=objects,
                total_text_length=len(text_only),
                total_objects=len(objects),
            ))

        logger.info("Extracted %d slides from HTML codes", len(extractions))
        write_json(
            [e.model_dump() for e in extractions],
            self.paths.extractions_path(turn_index),
        )
        return extractions
