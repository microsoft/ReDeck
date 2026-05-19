"""SlideExtraction schema - structural data extracted from compiled PPTX."""

from pydantic import BaseModel, Field


class ExtractedObject(BaseModel):
    """An object extracted from a compiled slide."""

    object_id: str
    shape_name: str = ""
    object_type: str = Field(description="text_box, picture, chart, table, shape, group")
    bbox_emu: list[int] = Field(default_factory=list, description="[left, top, width, height]")
    text_content: str = ""
    font_sizes_pt: list[float] = Field(default_factory=list)
    has_image: bool = False
    image_path: str = ""
    z_order: int = 0


class SlideExtraction(BaseModel):
    """Structural extraction for a single slide."""

    slide_id: int
    slide_index: int
    title: str = ""
    objects: list[ExtractedObject] = Field(default_factory=list)
    total_text_length: int = 0
    total_objects: int = 0
    has_notes: bool = False
    notes_text: str = ""
