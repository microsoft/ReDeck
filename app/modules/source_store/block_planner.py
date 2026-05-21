"""LLMDocumentBlockPlanner — use LLM to semantically chunk the document."""

import json
from .models import AtomicBlock, Asset, TableData, DocumentBlock, DocumentBlockPlan


SYSTEM_PROMPT = """\
You are a document analyst. Your task is to read a full document (with ID-anchored blocks) \
and produce a semantic chunking plan that groups related content into DocumentBlocks.

Each DocumentBlock should:
- Cover a coherent topic/section that could support 1-3 slides
- Reference ONLY existing block IDs (Bxxx), asset IDs (Axxx), and table IDs (Txxx)
- Have a clear role, summary, and keywords

Rules:
1. Only reference IDs that appear in the input (Bxxx, Axxx, Txxx).
2. Every atomic block should be assigned to at least one DocumentBlock. Minimize gaps.
3. Each DocumentBlock should be self-contained enough to support slide content generation.
4. Assign importance: "high" for core contributions/results, "medium" for methods/context, "low" for appendix/references.
5. slide_usage_hint: title_slide, concept_slide, evidence_slide, visual_slide, backup

Output valid JSON matching the schema. No markdown fences.
"""

USER_TEMPLATE = """\
## Anchored Document

{anchored_doc}

## Summary Stats
- Total atomic blocks: {n_blocks}
- Total assets: {n_assets}
- Total tables: {n_tables}

## Output Schema

```json
{{
  "document_profile": "paper",
  "blocks": [
    {{
      "doc_block_id": "DB001",
      "title": "...",
      "section_path": "...",
      "role": "overview|background|method|evidence|result|caveat|appendix|generic",
      "summary": "...",
      "keywords": ["..."],
      "included_atomic_block_ids": ["B001", "B002"],
      "linked_asset_ids": ["A001"],
      "linked_table_ids": [],
      "page_range": [1, 2],
      "importance": "high|medium|low",
      "slide_usage_hint": "title_slide|concept_slide|evidence_slide|visual_slide|backup",
      "split_reason": "..."
    }}
  ]
}}
```

Produce the DocumentBlockPlan now.
"""


class LLMDocumentBlockPlanner:
    """Use LLM to produce semantic document blocks."""

    def __init__(self, llm_client):
        self.llm = llm_client

    def plan(
        self,
        anchored_doc: str,
        blocks: list[AtomicBlock],
        assets: list[Asset],
        tables: list[TableData],
        model: str | None = None,
    ) -> DocumentBlockPlan:
        user_content = USER_TEMPLATE.format(
            anchored_doc=anchored_doc,
            n_blocks=len(blocks),
            n_assets=len(assets),
            n_tables=len(tables),
        )

        result = self.llm.call_json(
            system_prompt=SYSTEM_PROMPT,
            user_content=user_content,
            response_model=DocumentBlockPlan,
            model=model,
            module_name="source_store.block_planner",
            max_tokens=8192,
            temperature=0.1,
        )
        return result
