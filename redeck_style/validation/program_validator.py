"""Compile-time validation for bounded creative briefs."""

from redeck_style.domain.constraints import MIN_BODY_PX, MIN_LABEL_PX
from redeck_style.domain.density import DENSITY_MODES
from redeck_style.domain.asset_presentation import ASSET_MODES


class ProgramValidationError(ValueError):
    pass


def validate_program(program, library):
    errors = []
    if program.content_profile.asset_mode not in (*ASSET_MODES, "none"):
        errors.append(f"unsupported asset mode {program.content_profile.asset_mode}")
    if program.information_density not in DENSITY_MODES:
        errors.append(f"unsupported information density {program.information_density}")
    dialect = library.resolve_dialect(program.dialect_id)
    if program.schema_version != "2.0.0":
        errors.append(f"unsupported program schema {program.schema_version}")
    if not program.composition.strategy:
        errors.append("composition strategy is required")
    if not program.composition.focal_role:
        errors.append("composition focal role is required")
    if "title" not in program.composition.required_roles:
        errors.append("composition must provide a title role")
    if not 16 <= program.guardrails.safe_margin_px <= 96:
        errors.append("safe margin must be between 16 and 96 pixels")
    if program.guardrails.min_body_px < MIN_BODY_PX or program.guardrails.min_label_px < MIN_LABEL_PX:
        errors.append("typographic minimums are too small")

    counts = {}
    assigned = set()
    modes = {"required", "adapt", "optional"}
    for selection in program.vocab:
        item = library.items.get(selection.vocab_id)
        if not item:
            errors.append(f"unknown vocab {selection.vocab_id}")
            continue
        if item.kind != selection.kind:
            errors.append(f"kind mismatch for {selection.vocab_id}")
        if item.kind not in dialect.allowed_kinds or item.id in dialect.exclusions:
            errors.append(f"material excluded from design family: {item.id}")
        if item not in library.query(item.kind, program.dialect_id):
            errors.append(f"material outside design family: {item.id}")
        if selection.mode not in modes:
            errors.append(f"invalid vocab mode {selection.mode}")
        counts[selection.kind] = counts.get(selection.kind, 0) + 1
        if selection.kind == "content":
            assigned.update(selection.parameters.get("evidence_ids", []))
        code = " ".join(str(value) for value in item.program.values())
        if "--source-" in code:
            errors.append(f"unresolved source color in {item.id}")
        if "--style-" in code:
            errors.append(f"unresolved legacy style token in {item.id}")

    for kind in ("background", "typography", "content"):
        if counts.get(kind, 0) != 1:
            errors.append(f"program requires exactly one {kind}, found {counts.get(kind, 0)}")
    if counts.get("decoration", 0) > program.guardrails.max_decoration_systems:
        errors.append("decoration-system budget exceeded")
    missing = set(program.content_profile.evidence_ids) - assigned
    if missing:
        errors.append(f"unassigned evidence: {sorted(missing)}")
    layout_id = program.composition.layout_inspiration_id
    if layout_id not in {item.id for item in library.query("layout", program.dialect_id)}:
        errors.append(f"layout outside design family: {layout_id}")
    materials = [library.items[selection.vocab_id] for selection in program.vocab if selection.vocab_id in library.items]
    errors.extend(library.compatibility.selection_errors(layout_id, materials))
    if errors:
        raise ProgramValidationError("; ".join(errors))
    return program
