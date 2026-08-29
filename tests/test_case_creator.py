from app.modules.case_creator import CaseCreator


def _brief(source_kind: str) -> str:
    return CaseCreator()._generate_task_brief(
        {"title": "Example Source", "author": "Example Publisher", "total_pages": 24},
        [],
        [],
        "executive_briefing",
        "business leaders",
        [12, 16],
        source_kind,
    )


def test_document_brief_uses_document_semantics():
    brief = _brief("document")

    assert "an executive briefing presentation" in brief
    assert "## Source Information" in brief
    assert "central message and intended context" in brief
    assert "forward-looking statements" in brief
    assert "Methodology overview" not in brief
    assert "prior work / baselines" not in brief
    assert "12-16 slides" in brief


def test_paper_brief_keeps_research_semantics():
    brief = _brief("paper")

    assert "summarizing the paper" in brief
    assert "## Paper Information" in brief
    assert "Methodology overview" in brief
    assert "Comparison with prior work / baselines" in brief
