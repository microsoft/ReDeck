from unittest.mock import Mock

from app.modules.source_store.block_planner import LLMDocumentBlockPlanner
from app.modules.source_store.models import DocumentBlockPlan


def test_document_profile_does_not_prompt_as_academic_paper():
    llm = Mock()
    llm.call_json.return_value = DocumentBlockPlan(document_profile="business_report")

    planner = LLMDocumentBlockPlanner(llm)
    planner.plan("[B001] Revenue grew.", [], [], [], source_kind="document")

    call = llm.call_json.call_args.kwargs
    assert "full source document" in call["system_prompt"]
    assert "full academic paper" not in call["system_prompt"]
    assert '"document_profile": "business_report"' in call["user_content"]


def test_paper_profile_preserves_academic_context():
    llm = Mock()
    llm.call_json.return_value = DocumentBlockPlan(document_profile="paper")

    planner = LLMDocumentBlockPlanner(llm)
    planner.plan("[B001] Method.", [], [], [], source_kind="paper")

    call = llm.call_json.call_args.kwargs
    assert "full academic paper" in call["system_prompt"]
    assert '"document_profile": "paper"' in call["user_content"]
