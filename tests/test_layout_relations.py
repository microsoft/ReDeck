"""Tests for peer-aware, measurement-only layout relation feedback."""

from app.modules.redeck.agent_repair import AgentRepair
from app.modules.redeck.html_spatial_state import (
    extract_html_slide_state,
    format_html_compact_state,
    infer_layout_relations,
)
from app.modules.redeck.spatial_state import ContentBlock, SlideState
from app.schemas.common import Severity
from app.schemas.issue import Issue, IssueEvidence


def _peer_state(*, repaired: bool = False, split_peer: bool = False) -> SlideState:
    card_x = [100, 340, 610] if not repaired else [100, 350, 600]
    card_y = [100, 140, 100] if not repaired else [100, 100, 100]
    if split_peer:
        card_y[-1] = 500
    copy_heights = [110, 150, 110] if not repaired else [110, 110, 110]
    blocks = []
    for index, (x, y, copy_height) in enumerate(
        zip(card_x, card_y, copy_heights),
        1,
    ):
        card_path = f"/html/body/main[1]/div[{index}]"
        blocks.append(ContentBlock(
            block_id=f"card_{index}",
            var_name="div",
            shape_type="shape",
            css_selector=".card",
            css_classes=("card",),
            text_chars=0,
            bbox_px=(x, y, 200, 200),
            x=x / 96,
            y=y / 96,
            w=200 / 96,
            h=200 / 96,
            dom_path=card_path,
            is_filled=True,
        ))
        blocks.append(ContentBlock(
            block_id=f"copy_{index}",
            var_name="p",
            shape_type="textbox",
            css_selector=".card-copy",
            text_lines=[f"Card {index} copy"],
            text_chars=11,
            bbox_px=(x + 20, y + 30, 160, copy_height),
            x=(x + 20) / 96,
            y=(y + 30) / 96,
            w=160 / 96,
            h=copy_height / 96,
            dom_path=f"{card_path}/p[1]",
        ))
    return SlideState(slide_id=1, blocks=blocks)


def test_repeated_card_siblings_form_high_confidence_row_relation():
    relation = infer_layout_relations(_peer_state())[0]

    assert relation["confidence"] == "high"
    assert relation["orientation"] == "row"
    assert relation["member_ids"] == ["card_1", "card_2", "card_3"]
    assert relation["metrics"]["bottom_spread_px"] == 40
    assert relation["metrics"]["gap_spread_px"] == 30
    assert relation["metrics"]["internal_bottom_slack_spread_px"] == 40


def test_different_title_and_body_roles_are_not_inferred_as_peers():
    state = SlideState(slide_id=1, blocks=[
        ContentBlock(
            block_id="title", var_name="h1", shape_type="title",
            css_selector=".title", text_lines=["Quarterly results"],
            text_chars=17, bbox_px=(80, 60, 600, 60),
            dom_path="/html/body/main[1]/h1[1]",
        ),
        ContentBlock(
            block_id="body", var_name="p", shape_type="textbox",
            css_selector=".body", text_lines=["Revenue increased."],
            text_chars=18, bbox_px=(80, 150, 600, 80),
            dom_path="/html/body/main[1]/p[1]",
        ),
    ])

    assert infer_layout_relations(state) == []


def test_compact_state_includes_relation_map_before_space_map():
    compact = format_html_compact_state(_peer_state())

    assert "RELATION MAP" in compact
    assert compact.index("RELATION MAP") < compact.index("SPACE MAP")
    assert "left=" in compact
    assert "right=" in compact
    assert "internal slack spread: bottom=40px, right=0px" in compact


def test_shared_utility_class_does_not_merge_different_tags_and_roles():
    html = """
    <html><body style="margin:0;width:1280px;height:720px">
      <main style="position:relative;width:1280px;height:720px">
        <div class="shared card" style="position:absolute;left:80px;top:140px;
             width:300px;height:180px;background:#eee">Card content</div>
        <h2 class="shared section-title" style="position:absolute;left:430px;
             top:140px;width:300px;height:180px;background:#ddd;margin:0">
          Section title
        </h2>
        <div class="shared card" style="position:absolute;left:780px;top:140px;
             width:300px;height:180px;background:#eee">Other card</div>
      </main>
    </body></html>
    """
    state = extract_html_slide_state(1, html)

    relations = infer_layout_relations(state)
    relation_tags = [
        {
            next(block.var_name for block in state.blocks if block.block_id == member_id)
            for member_id in relation["member_ids"]
        }
        for relation in relations
    ]

    assert {"div", "h2"} not in relation_tags
    assert any(tags == {"div"} for tags in relation_tags)


def test_alignment_delta_compares_only_named_peer_metric():
    issue = Issue(
        issue_id="b13_cards",
        rubric_id="B13",
        issue_type="alignment_inconsistency",
        severity=Severity.MAJOR,
        affected_slides=[1],
        evidence=IssueEvidence(
            description="The .card bottom edges are visibly misaligned.",
        ),
        planned_fix="Align the three .card bottom edges.",
    )

    delta = AgentRepair._format_alignment_relation_delta(
        _peer_state(),
        _peer_state(repaired=True),
        [issue],
    )

    assert "bottom-edge spread" in delta
    assert "40px -> 0px (improved)" in delta
    assert "not a resolution verdict" in delta


def test_alignment_delta_refuses_unmatched_global_inference():
    issue = Issue(
        issue_id="b13_badges",
        rubric_id="B13",
        issue_type="alignment_inconsistency",
        severity=Severity.MAJOR,
        affected_slides=[1],
        evidence=IssueEvidence(
            description="The benchmark badges have mismatched bottom edges.",
        ),
    )

    delta = AgentRepair._format_alignment_relation_delta(
        _peer_state(),
        _peer_state(repaired=True),
        [issue],
    )

    assert "no candidate peer group matched" in delta
    assert "Do not use a global relation" in delta


def test_alignment_delta_refuses_partial_peer_subset():
    issue = Issue(
        issue_id="b13_cards",
        rubric_id="B13",
        issue_type="alignment_inconsistency",
        severity=Severity.MAJOR,
        affected_slides=[1],
        evidence=IssueEvidence(
            description="The three .card bottom edges are misaligned.",
        ),
    )

    delta = AgentRepair._format_alignment_relation_delta(
        _peer_state(),
        _peer_state(repaired=True, split_peer=True),
        [issue],
    )

    assert "no current peer group retains the complete member set" in delta
    assert "(improved)" not in delta


def test_alignment_metric_distinguishes_location_from_alignment_axis():
    assert AgentRepair._alignment_metric_for_text(
        "The cards in the right column have uneven spacing."
    ) == "gap_spread_px"
    assert AgentRepair._alignment_metric_for_text(
        "The left-side panels have inconsistent gaps."
    ) == "gap_spread_px"
    assert AgentRepair._alignment_metric_for_text(
        "There is excess whitespace on the right inside each card."
    ) == "internal_right_slack_spread_px"


def test_relation_inference_does_not_drop_groups_larger_than_twelve():
    blocks = [
        ContentBlock(
            block_id=f"label_{index}", var_name="div", shape_type="textbox",
            css_selector=".label", css_classes=("label",), text_chars=6,
            text_lines=[f"L{index}"], bbox_px=(20 + index * 50, 100, 40, 20),
            dom_path=f"main[0]/div[{index}]",
        )
        for index in range(13)
    ]

    relations = infer_layout_relations(SlideState(slide_id=1, blocks=blocks))

    assert any(len(relation["member_ids"]) == 13 for relation in relations)
