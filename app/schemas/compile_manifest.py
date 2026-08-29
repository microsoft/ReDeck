"""CompileManifest schema - record of compilation output."""

from pydantic import BaseModel, Field


class CompiledObjectRecord(BaseModel):
    """Record of a single compiled object."""

    object_id: str
    slide_id: int
    object_type: str
    shape_name: str = ""
    editable: bool = True
    bbox_emu: list[int] = Field(default_factory=list, description="[left, top, width, height] in EMU")


class CompileManifest(BaseModel):
    """Manifest of the compilation output."""

    pptx_path: str
    total_slides: int
    objects: list[CompiledObjectRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    compile_backend: str = "python_pptx"
    timing_sec: float = 0.0
