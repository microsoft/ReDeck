"""Shared helpers for slide repair modules.

Extracted from the legacy multi_action.py to support agent_repair.py.
"""

import json
import re
import logging
from collections import Counter

from bs4 import BeautifulSoup, NavigableString

from ...schemas.issue_types import CONTENT_ACCURACY_TYPES as CONTENT_ACCURACY_ISSUE_TYPES

_logger = logging.getLogger(__name__)


_EDITORIAL_PREFIX_RE = re.compile(
    r"^(?:"
    r"Text\s+to\s+INSERT|Final\s+text|Correct\s+content|"
    r"Add(?:\s+(?:evidence|source[-\s]grounded|missing|new|required|one|the|a)?"
    r"\s*(?:bullets?|rows?|points?|qualifiers?|paragraphs?|sentences?|texts?|evidence))?|"
    r"Insert|Replace\s+with|"
    r"Use(?:\s+source[\s-]+(?:grounded|backed|wording)(?:\s+(?:content\s+)?only)?)?"
    r")\s*:\s*",
    re.IGNORECASE,
)

_EDITORIAL_DIRECTIVE_FRAGMENT_RE = re.compile(
    r"\b(?:"
    r"Text\s+to\s+INSERT|Final\s+text|Correct\s+content|"
    r"Add(?:\s+(?:evidence|source[-\s]grounded|missing|new|required|one|the|a)?"
    r"\s*(?:bullets?|rows?|points?|qualifiers?|paragraphs?|sentences?|texts?|evidence))?|"
    r"Insert|Replace\s+with|"
    r"Use(?:\s+source[\s-]+(?:grounded|backed|wording)(?:\s+(?:content\s+)?only)?)?"
    r")\s*:\s*[\"\u201c\u2018]?",
    re.IGNORECASE,
)


def normalize_correct_content_text(text: str) -> str:
    """Convert judge repair instructions into final visible slide text.

    Evaluators sometimes put an edit command in ``correct_content`` (for
    example ``Add evidence bullet: "..."``). The repair pipeline inserts this
    field as visible content, so strip only directive prefixes and wrapping
    quotes while leaving real source wording intact.
    """
    if not isinstance(text, str):
        return ""
    value = re.sub(r"\s+", " ", text).strip()
    if not value:
        return ""

    remove_replace = re.match(
        r"^(?:REMOVE|DELETE)\b.*?"
        r"(?:Replace\s+with|Use\s+instead)[:\s]*[\"']?(.+?)[\"']?\s*$",
        value,
        re.IGNORECASE | re.DOTALL,
    )
    if remove_replace:
        value = remove_replace.group(1).strip()
    elif re.match(
        r"^(?:No verified|Keep only|Remove the|REMOVE|DELETE)(?:\b|\s*:)",
        value,
        re.IGNORECASE,
    ):
        return ""

    for _ in range(4):
        before = value
        value = re.sub(r"^(?:[-*\u2022]\s*)+", "", value).strip()
        value = _EDITORIAL_PREFIX_RE.sub("", value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        value = value.lstrip('"\'\u201c\u2018').rstrip('"\'\u201d\u2019').strip()
        if value == before:
            break
    return value


def extract_table_row_specs_from_correct_content(text: str) -> tuple[str, ...]:
    """Extract source-backed table row specs from judge repair text.

    Some probes return ``correct_content`` as an edit command, for example
    ``Add rows: "Model A | 0.1 | 0.2" and "Model B | 0.3 | 0.4"``. The
    slide should contain table cells, not that command sentence. This returns
    the pipe-separated row payloads so callers can instruct the agent to edit
    ``<tr>/<td>`` structure directly.
    """
    if not isinstance(text, str):
        return ()
    value = re.sub(r"\s+", " ", text).strip()
    if not value or "|" not in value:
        return ()

    quoted_rows: list[str] = []
    for match in re.finditer(
        r"[\"\u201c\u2018]([^\"\u201d\u2019]+\|[^\"\u201d\u2019]+)[\"\u201d\u2019]",
        value,
    ):
        row = normalize_correct_content_text(match.group(1))
        row = re.sub(r"\s+", " ", row).strip(" .;")
        if row and row not in quoted_rows:
            quoted_rows.append(row)
    if quoted_rows:
        return tuple(quoted_rows)

    normalized = normalize_correct_content_text(value)
    if "|" not in normalized:
        return ()

    rows: list[str] = []
    for part in re.split(r"\s+(?:and|;|,\s*and)\s+", normalized):
        row = re.sub(r"\s+", " ", part).strip(" \"'\u201c\u201d\u2018\u2019.;")
        if "|" in row and row not in rows:
            rows.append(row)
    return tuple(rows)


def _editorial_directive_insensitive_tokens(strings: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    text = re.sub(r"\s+", " ", " ".join(strings or [])).strip()
    if not text:
        return ()
    text = _EDITORIAL_DIRECTIVE_FRAGMENT_RE.sub("", text)
    text = re.sub(r"[\"\u201c\u201d\u2018\u2019]", "", text)
    return tuple(re.findall(r"\w+|[^\w\s]", text.casefold()))


def issues_explicitly_request_image_crop(issues) -> bool:
    """Return whether the VLM brief explicitly asks to crop an image.

    Image cropping is normally a regression signal. When the diagnosed defect
    is itself an uncropped/raw figure, it is an intended target-side effect and
    should be judged by the render preview instead of vetoed mechanically.
    """
    for issue in issues or []:
        if getattr(issue, "issue_type", "") != "raw_figure":
            continue
        evidence = getattr(issue, "evidence", None)
        fix_detail = getattr(issue, "fix_detail", None)
        parts = [
            getattr(evidence, "description", ""),
            getattr(issue, "why_this_fails", ""),
            getattr(issue, "planned_fix", ""),
            getattr(fix_detail, "correct_content", ""),
            getattr(fix_detail, "target_location", ""),
            getattr(fix_detail, "action_type", ""),
        ]
        brief = " ".join(part for part in parts if isinstance(part, str)).lower()
        if "crop" in brief or "uncropped" in brief:
            return True
    return False


def html_image_css_crop_hints(html: str) -> list[str]:
    """Return CSS patterns that crop an embedded image without a new asset.

    B17/raw_figure fixes should normally produce a presentation-adapted source
    image or chart, then display it with ``object-fit: contain``. CSS windowing
    can make DOM geometry look clean while semantically cutting away the paper
    figure content, so these hints are treated as raw-figure repair risks.
    """
    if not html:
        return []

    hints: list[str] = []
    lower = html.lower()

    def add(label: str) -> None:
        if label not in hints:
            hints.append(label)

    if re.search(r"\bobject-view-box\s*:", lower):
        add("object-view-box")
    if re.search(r"\bobject-fit\s*:\s*(cover|none)\b", lower):
        add("object-fit cover/none")
    if re.search(r"\bobject-position\s*:[^;{}]*-\s*\d", lower):
        add("negative object-position")
    if re.search(r"\bclip-path\s*:", lower) or re.search(r"\bclip\s*:\s*rect\s*\(", lower):
        add("clip-path/clip rect")

    # Rules scoped to img/image selectors that move or scale the bitmap inside a
    # fixed window. This catches the common overflow:hidden + absolute/negative
    # offset repair pattern without flagging unrelated layout containers.
    for _selector, body in re.findall(r"([^{}]*\b(?:img|image)\b[^{}]*)\{([^{}]*)\}", lower):
        if re.search(r"\b(left|top|right|bottom)\s*:\s*-\s*\d", body):
            add("negative image offset")
        if re.search(r"\btransform\s*:[^;{}]*scale\s*\(", body):
            add("image transform scale")
        if re.search(r"\bclip-path\s*:", body) or re.search(r"\bclip\s*:\s*rect\s*\(", body):
            add("image clip path")
        if re.search(r"\bobject-fit\s*:\s*(cover|none)\b", body):
            add("image object-fit crop")

    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["img", "image"]):
            style = str(tag.get("style", "")).lower()
            if not style:
                continue
            if re.search(r"\bobject-view-box\s*:", style):
                add("inline object-view-box")
            if re.search(r"\bobject-fit\s*:\s*(cover|none)\b", style):
                add("inline object-fit crop")
            if re.search(r"\bobject-position\s*:[^;{}]*-\s*\d", style):
                add("inline negative object-position")
            if re.search(r"\b(left|top|right|bottom)\s*:\s*-\s*\d", style):
                add("inline negative image offset")
            if re.search(r"\btransform\s*:[^;{}]*scale\s*\(", style):
                add("inline image transform scale")
            if re.search(r"\bclip-path\s*:", style) or re.search(r"\bclip\s*:\s*rect\s*\(", style):
                add("inline image clip")
    except Exception:
        # BeautifulSoup parsing is best-effort; regex hints above still cover
        # the relevant CSS repair patterns.
        pass

    return hints


def can_exempt_raw_figure_image_crop(issues, html: str) -> bool:
    """Whether image-crop regressions may be ignored for a raw-figure repair.

    A B17 brief may request a crop, but CSS-only crop mechanisms are not a safe
    final state. They can pass DOM containment while visually cutting away the
    dense figure. Only allow the old image-crop exemption when the current code
    does not contain CSS crop/windowing hints.
    """
    return (
        issues_explicitly_request_image_crop(issues)
        and not html_image_css_crop_hints(html)
    )


def is_raw_figure_asset_replacement(issues, before_html: str, after_html: str) -> bool:
    """Return whether a raw figure/table issue replaced an image with a real asset."""
    if not any(getattr(issue, "issue_type", "") in {"raw_figure", "raw_table"} for issue in issues or []):
        return False
    before_srcs = re.findall(
        r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]",
        before_html or "",
        flags=re.IGNORECASE,
    )
    after_srcs = re.findall(
        r"<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]",
        after_html or "",
        flags=re.IGNORECASE,
    )
    if not before_srcs or len(before_srcs) != len(after_srcs):
        return False
    for before_src, after_src in zip(before_srcs, after_srcs, strict=False):
        if before_src == after_src:
            continue
        lowered = after_src.lower()
        if (
            "generated_assets/" in lowered
            or "repair_assets/" in lowered
            or lowered.endswith(".svg")
        ):
            return True
    return False


def _normalized_visible_strings(
    soup: BeautifulSoup,
    *,
    casefold: bool = False,
) -> tuple[str, ...]:
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["style", "script"]):
        tag.decompose()
    strings = tuple(
        re.sub(r"\s+", " ", text).strip()
        for text in clone.stripped_strings
        if text.strip()
    )
    if casefold:
        return tuple(text.casefold() for text in strings)
    return strings


_TEXT_STOP_TOKENS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "into", "onto",
    "than", "then", "only", "also", "over", "under", "between", "within",
    "slide", "page", "source", "figure", "table", "section", "summary",
})


def _meaningful_tokens_from_text(text: str) -> tuple[str, ...]:
    tokens = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.%xX+\-/]*", text):
        normalized = token.casefold().strip("._:;,%+-/")
        if not normalized or normalized in _TEXT_STOP_TOKENS:
            continue
        if any(char.isdigit() for char in normalized) or len(normalized) >= 4:
            tokens.append(normalized)
    return tuple(tokens)


def _meaningful_visible_tokens(soup: BeautifulSoup) -> tuple[str, ...]:
    return _meaningful_tokens_from_text(" ".join(_normalized_visible_strings(soup)))


_HIDDEN_STYLE_PATTERNS = (
    r"display\s*:\s*none",
    r"visibility\s*:\s*(?:hidden|collapse)",
    r"opacity\s*:\s*0(?:\.0+)?(?:\s|;|$)",
    r"font-size\s*:\s*0(?:px|pt|rem|em)?",
    r"color\s*:\s*transparent",
    r"clip\s*:\s*rect\s*\(\s*0(?:px)?\s*,\s*0(?:px)?\s*,\s*0(?:px)?\s*,\s*0(?:px)?\s*\)",
    r"clip-path\s*:\s*inset\s*\(\s*(?:50|100)%",
)
_OFF_CANVAS_STYLE_PATTERN = re.compile(
    r"(?:left|top|right|bottom)\s*:\s*-\s*(?:[2-9]\d{2,}|\d{4,})(?:px|pt|rem|em)?",
    re.IGNORECASE,
)
_NEGATIVE_TRANSLATE_STYLE_PATTERN = re.compile(
    r"translate(?:3d|x|y)?\s*\([^)]*-\s*(?:[2-9]\d{2,}|\d{4,})(?:px|pt|rem|em)?",
    re.IGNORECASE,
)


def _style_hides_text(style: str) -> bool:
    normalized = re.sub(r"\s+", " ", style or "").lower()
    if not normalized:
        return False
    if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _HIDDEN_STYLE_PATTERNS):
        return True
    return bool(
        _OFF_CANVAS_STYLE_PATTERN.search(normalized)
        or _NEGATIVE_TRANSLATE_STYLE_PATTERN.search(normalized)
    )


def _hidden_selector_keys(soup: BeautifulSoup) -> tuple[set[str], set[str]]:
    """Return class/id selectors whose CSS block visually hides content."""
    classes: set[str] = set()
    ids: set[str] = set()
    for style_tag in soup.find_all("style"):
        css = style_tag.get_text("\n", strip=False)
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css, re.DOTALL):
            selector_text, declarations = match.groups()
            if not _style_hides_text(declarations):
                continue
            for selector in selector_text.split(","):
                for class_name in re.findall(r"\.([A-Za-z_][\w-]*)", selector):
                    classes.add(class_name)
                for id_name in re.findall(r"#([A-Za-z_][\w-]*)", selector):
                    ids.add(id_name)
    return classes, ids


def _tag_is_hidden_text_candidate(
    tag,
    *,
    hidden_classes: set[str],
    hidden_ids: set[str],
) -> bool:
    if tag.name in {"script", "style", "meta", "link"}:
        return False
    if tag.has_attr("hidden"):
        return True
    if tag.get("aria-hidden", "").lower() == "true":
        return True
    if _style_hides_text(tag.get("style", "")):
        return True
    tag_classes = tag.get("class", []) or []
    if any(class_name in hidden_classes for class_name in tag_classes):
        return True
    tag_id = tag.get("id", "")
    return bool(tag_id and tag_id in hidden_ids)


def _hidden_text_blocks(soup: BeautifulSoup) -> Counter:
    hidden_classes, hidden_ids = _hidden_selector_keys(soup)
    blocks: Counter = Counter()
    for tag in soup.find_all(True):
        if tag.find_parent("svg") is not None:
            continue
        if not _tag_is_hidden_text_candidate(
            tag,
            hidden_classes=hidden_classes,
            hidden_ids=hidden_ids,
        ):
            continue
        if any(
            _tag_is_hidden_text_candidate(
                parent,
                hidden_classes=hidden_classes,
                hidden_ids=hidden_ids,
            )
            for parent in tag.find_parents()
        ):
            continue
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
        if _meaningful_tokens_from_text(text):
            blocks[text.casefold()] += 1
    return blocks


def validate_no_hidden_text_duplicates(
    before_html: str,
    after_html: str,
) -> tuple[bool, str]:
    """Reject repairs that satisfy source text guards with hidden copies.

    Visual repairs may move or restyle text, but protected content must remain
    genuinely visible. This catches hidden/off-canvas duplicates and newly
    hidden protected text before source-level string comparison can be fooled.
    """
    before = BeautifulSoup(before_html, "html.parser")
    after = BeautifulSoup(after_html, "html.parser")
    before_hidden = _hidden_text_blocks(before)
    after_hidden = _hidden_text_blocks(after)
    added_hidden = after_hidden - before_hidden
    if not added_hidden:
        return True, "no hidden protected text added"

    protected_tokens = Counter(_meaningful_visible_tokens(before))
    for hidden_text, count in added_hidden.items():
        hidden_tokens = Counter(_meaningful_tokens_from_text(hidden_text))
        if not hidden_tokens:
            continue
        overlap = sum((hidden_tokens & protected_tokens).values())
        retention = overlap / max(1, sum(hidden_tokens.values()))
        if retention >= 0.60:
            sample = hidden_text[:80]
            if count > 1:
                sample = f"{sample} ({count} copies)"
            return False, f"hidden duplicate/protected text added: {sample!r}"
    return True, "no hidden protected text added"


def _counter_retention(
    before_tokens: tuple[str, ...],
    after_tokens: tuple[str, ...],
) -> float:
    if not before_tokens:
        return 1.0
    overlap = Counter(before_tokens) & Counter(after_tokens)
    return sum(overlap.values()) / len(before_tokens)


def _outside_svg_tag_counts(soup: BeautifulSoup, tag_names: set[str]) -> Counter:
    counts: Counter = Counter()
    for tag in soup.find_all(True):
        if tag.name not in tag_names:
            continue
        if tag.name != "svg" and tag.find_parent("svg") is not None:
            continue
        counts[tag.name] += 1
    return counts


_MEANINGFUL_BLOCK_TAGS = {
    "article", "aside", "blockquote", "caption", "dd", "dt", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section", "td",
    "th", "tr",
}


def _meaningful_block_texts(soup: BeautifulSoup) -> tuple[str, ...]:
    blocks = []
    for tag in soup.find_all(_MEANINGFUL_BLOCK_TAGS):
        if tag.find_parent("svg") is not None:
            continue
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
        tokens = _meaningful_tokens_from_text(text)
        if len(tokens) >= 2 or any(
            any(char.isdigit() for char in token) for token in tokens
        ):
            blocks.append(" ".join(tokens[:24]))
    return tuple(blocks)


def _non_svg_structural_tag_count(soup: BeautifulSoup) -> int:
    ignored = {"html", "body", "head", "style", "script", "meta", "link"}
    total = 0
    for tag in soup.find_all(True):
        if tag.name in ignored:
            continue
        if tag.name != "svg" and tag.find_parent("svg") is not None:
            continue
        total += 1
    return total


def validate_repair_not_visual_downgrade(
    before_html: str,
    after_html: str,
    *,
    allow_structure_reduction: bool = False,
) -> tuple[bool, str]:
    """Reject repairs that pass issue counts by emptying the slide.

    This protects the visual payload shape: figures, tables, lists, and
    meaningful content blocks should not collapse unless the caller is applying
    a content issue that explicitly authorizes removal or replacement.
    """
    before = BeautifulSoup(before_html, "html.parser")
    after = BeautifulSoup(after_html, "html.parser")

    protected_tags = {"img", "svg", "canvas", "video", "audio", "table", "figure"}
    before_protected = _outside_svg_tag_counts(before, protected_tags)
    after_protected = _outside_svg_tag_counts(after, protected_tags)
    for tag_name in sorted(protected_tags):
        before_count = before_protected.get(tag_name, 0)
        after_count = after_protected.get(tag_name, 0)
        if after_count < before_count:
            return (
                False,
                f"dropped {tag_name} elements ({before_count}->{after_count})",
            )

    if allow_structure_reduction:
        return True, "structure reduction allowed"

    list_counts = _outside_svg_tag_counts(before, {"ul", "ol", "li"})
    after_list_counts = _outside_svg_tag_counts(after, {"ul", "ol", "li"})
    before_lists = list_counts.get("ul", 0) + list_counts.get("ol", 0)
    after_lists = after_list_counts.get("ul", 0) + after_list_counts.get("ol", 0)
    if before_lists and after_lists < before_lists:
        return False, f"dropped list containers ({before_lists}->{after_lists})"
    before_items = list_counts.get("li", 0)
    after_items = after_list_counts.get("li", 0)
    if before_items >= 4 and after_items < max(1, int(before_items * 0.75)):
        return False, f"list item structure collapsed ({before_items}->{after_items})"

    table_counts = _outside_svg_tag_counts(before, {"tr", "th", "td"})
    after_table_counts = _outside_svg_tag_counts(after, {"tr", "th", "td"})
    for tag_name, label in (
        ("tr", "table rows"), ("td", "table cells"), ("th", "table headers"),
    ):
        before_count = table_counts.get(tag_name, 0)
        after_count = after_table_counts.get(tag_name, 0)
        if before_count >= 4 and after_count < max(1, int(before_count * 0.75)):
            return False, f"{label} collapsed ({before_count}->{after_count})"

    before_tokens = _meaningful_visible_tokens(before)
    after_tokens = _meaningful_visible_tokens(after)
    if len(before_tokens) >= 12:
        retention = _counter_retention(before_tokens, after_tokens)
        if retention < 0.70:
            return False, f"meaningful text retention too low ({retention:.0%})"
        if len(after_tokens) < len(before_tokens) * 0.65:
            return False, (
                f"meaningful text volume collapsed "
                f"({len(before_tokens)}->{len(after_tokens)} tokens)"
            )

    before_blocks = _meaningful_block_texts(before)
    after_blocks = _meaningful_block_texts(after)
    if len(before_blocks) >= 6 and len(after_blocks) < max(
        3, int(len(before_blocks) * 0.55),
    ):
        return False, (
            f"meaningful content blocks collapsed "
            f"({len(before_blocks)}->{len(after_blocks)})"
        )

    before_struct = _non_svg_structural_tag_count(before)
    after_struct = _non_svg_structural_tag_count(after)
    if (
        before_struct >= 18
        and after_struct < before_struct * 0.45
        and len(after_blocks) < max(1, int(len(before_blocks) * 0.75))
    ):
        return False, f"DOM structure collapsed ({before_struct}->{after_struct} tags)"

    return True, "no visual downgrade detected"


def _css_numeric_values(html: str, property_pattern: str) -> list[float]:
    """Extract the first numeric CSS value for matching declarations."""
    return [
        float(value)
        for value in re.findall(
            rf"(?:{property_pattern})[^:]*:\s*([\d.]+)",
            html,
            flags=re.IGNORECASE,
        )
    ]


def _css_font_sizes_by_selector(html: str) -> dict[str, float]:
    """Return simple selector-to-font-size declarations from inline styles."""
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:
        return {}

    sizes: dict[str, float] = {}
    for style in soup.find_all("style"):
        css = re.sub(r"/\*.*?\*/", "", style.get_text(" "), flags=re.DOTALL)
        for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            match = re.search(
                r"(?:^|;)\s*font-size\s*:\s*([\d.]+)px\b",
                body,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            size = float(match.group(1))
            for selector in selector_group.split(","):
                selector = selector.strip()
                if selector and not selector.startswith("@"):
                    sizes[selector] = size
    return sizes


def _dominant_font_role_is_repeated_peer(
    before_html: str,
    after_html: str,
    before_max: float,
) -> bool:
    """Whether the largest type belongs to repeated peers, not one page hero.

    A repeated comparison-card score can legitimately be calibrated together
    with the rest of the card rhythm. Treating its CSS maximum as a unique hero
    makes the compression guard push every peer back toward an oversized state.
    Average-scale and content-preservation gates still protect global collapse.
    """
    before_sizes = _css_font_sizes_by_selector(before_html)
    after_sizes = _css_font_sizes_by_selector(after_html)
    if not before_sizes or not after_sizes:
        return False

    try:
        before_soup = BeautifulSoup(before_html or "", "html.parser")
        after_soup = BeautifulSoup(after_html or "", "html.parser")
    except Exception:
        return False

    for selector, size in before_sizes.items():
        if abs(size - before_max) > 0.01 or selector not in after_sizes:
            continue
        try:
            before_matches = before_soup.select(selector)
            after_matches = after_soup.select(selector)
        except Exception:
            continue
        if len(before_matches) >= 2 and len(after_matches) == len(before_matches):
            return True
    return False


def validate_repair_not_visual_compression(
    before_html: str,
    after_html: str,
    *,
    allow_dominant_element_removal: bool = False,
) -> tuple[bool, str]:
    """Reject global typography/spacing compression used to force a fit.

    The external dispatcher and the in-agent verifier must share this gate.
    Otherwise an agent can receive a clean spatial verification, submit, and
    only then lose the entire repair because a dominant title/hero was shrunk.
    """
    before_fonts = _css_numeric_values(before_html, r"font-size")
    after_fonts = _css_numeric_values(after_html, r"font-size")
    if not before_fonts or not after_fonts:
        return True, "no comparable font declarations"

    before_max = max(before_fonts)
    after_max = max(after_fonts)
    before_avg = sum(before_fonts) / len(before_fonts)
    after_avg = sum(after_fonts) / len(after_fonts)
    repeated_dominant_role = _dominant_font_role_is_repeated_peer(
        before_html,
        after_html,
        before_max,
    )

    dominant_scale_calibration = (
        before_max >= 88
        and after_max >= 56
        and after_avg >= before_avg * 0.75
    )

    if (
        after_max < before_max * 0.70
        and not allow_dominant_element_removal
        and not dominant_scale_calibration
        and not repeated_dominant_role
    ):
        return False, (
            "dominant font shrank "
            f"{before_max:.0f}px->{after_max:.0f}px "
            f"({(1 - after_max / before_max) * 100:.0f}% reduction)"
        )
    avg_floor = 0.75
    if after_avg < before_avg * avg_floor:
        return False, (
            "average font size shrank "
            f"{before_avg:.1f}px->{after_avg:.1f}px "
            f"({(1 - after_avg / before_avg) * 100:.0f}% reduction)"
        )

    if (
        after_max < before_max * 0.80
        and not allow_dominant_element_removal
        and not dominant_scale_calibration
        and not repeated_dominant_role
    ):
        before_spacing = _css_numeric_values(before_html, r"margin|padding")
        after_spacing = _css_numeric_values(after_html, r"margin|padding")
        if before_spacing and after_spacing:
            before_spacing_avg = sum(before_spacing) / len(before_spacing)
            after_spacing_avg = sum(after_spacing) / len(after_spacing)
            if after_spacing_avg < before_spacing_avg * 0.75:
                return False, (
                    "combined visual compression: dominant font "
                    f"{before_max:.0f}px->{after_max:.0f}px and average "
                    f"spacing {before_spacing_avg:.1f}->{after_spacing_avg:.1f}"
                )

    return True, "no visual compression detected"


def issues_allow_dominant_element_removal(issues) -> bool:
    """Return whether a visual issue intentionally removes a large redundant block."""
    action_types = {"remove_element", "remove_text", "merge_text", "restructure_layout"}
    remove_re = re.compile(r"\b(remove|delete|eliminate|drop|merge|consolidate)\b", re.I)
    target_re = re.compile(
        r"\b(callout|hero|card|badge|footer|bottom[- ]?bar|metric|block|element|banner)\b",
        re.I,
    )
    for issue in issues or []:
        if getattr(issue, "issue_type", "") != "form_redundancy":
            continue
        fix_detail = getattr(issue, "fix_detail", None)
        action_type = (getattr(fix_detail, "action_type", "") or "").lower()
        parts = [
            getattr(issue, "planned_fix", ""),
            getattr(issue, "why_this_fails", ""),
            getattr(getattr(issue, "evidence", None), "description", ""),
            getattr(fix_detail, "correct_content", "") if fix_detail else "",
            getattr(fix_detail, "target_location", "") if fix_detail else "",
            action_type,
        ]
        text = " ".join(part for part in parts if isinstance(part, str))
        if action_type in action_types and remove_re.search(text) and target_re.search(text):
            return True
        if remove_re.search(text) and target_re.search(text) and re.search(
            r"duplicat|redundan|repeat", text, re.I,
        ):
            return True
    return False


def _format_insensitive_visible_tokens(
    soup: BeautifulSoup,
) -> tuple[tuple[str, ...], ...]:
    """Compare text payload while ignoring case and whitespace formatting.

    This deliberately retains every word/number token, punctuation mark, text
    node, and their order. It therefore permits repairs such as ``Page 1 ;``
    to ``Page 1;`` without treating arbitrary rewording as formatting.
    """
    return tuple(
        tokens for tokens in (
            _editorial_directive_insensitive_tokens((text,))
            for text in _normalized_visible_strings(soup)
        )
        if tokens
    )


def _source_visible_text_inventory(
    soup: BeautifulSoup,
    *,
    casefold: bool = False,
    formatting_insensitive: bool = False,
) -> Counter:
    """Return source-visible text content without freezing DOM order.

    Visual reflow may move intact semantic units in the DOM so that source
    order follows the new visual reading path. The hard scope guard should
    catch text deletion, addition, or rewriting, while rendered-order changes
    remain an inspection signal. Token counts also tolerate harmless wrapper
    changes around otherwise unchanged text.
    """
    strings = _normalized_visible_strings(soup, casefold=casefold)
    if formatting_insensitive:
        tokens = _editorial_directive_insensitive_tokens(strings)
    else:
        tokens = tuple(
            token.casefold() if casefold else token
            for text in strings
            for token in re.findall(r"\w+|[^\w\s]", text)
        )
    return Counter(tokens)


def _non_svg_semantic_inventory(soup: BeautifulSoup) -> Counter:
    """Describe meaningful non-SVG DOM without freezing layout attributes."""
    inventory: Counter = Counter()
    for tag in soup.find_all(True):
        if tag.name in {"html", "body", "head", "style", "script"}:
            continue
        if tag.name == "svg":
            inventory[("svg", tag.get("aria-label", ""), tag.get("role", ""))] += 1
            continue
        if tag.find_parent("svg") is not None:
            continue
        direct_text = " ".join(
            re.sub(r"\s+", " ", str(child)).strip()
            for child in tag.children
            if isinstance(child, NavigableString) and str(child).strip()
        )
        media_ref = ""
        if tag.name in {"img", "video", "audio", "source"}:
            media_ref = tag.get("src", "")
        elif tag.name == "a":
            media_ref = tag.get("href", "")
        inventory[(tag.name, direct_text, media_ref, tag.get("role", ""))] += 1
    return inventory


def _svg_semantic_inventory(soup: BeautifulSoup) -> Counter:
    """Capture SVG semantics while deliberately allowing geometry rewrites."""
    inventory: Counter = Counter()
    for svg in soup.find_all("svg"):
        inventory[("svg", svg.get("aria-label", ""), svg.get("role", ""))] += 1
        for tag in svg.find_all(["title", "desc", "image"]):
            value = tag.get("href", "") or tag.get("xlink:href", "")
            if tag.name != "image":
                value = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
            inventory[(tag.name, value)] += 1
    return inventory


def _media_and_accessibility_inventory(
    soup: BeautifulSoup,
    *,
    allow_image_replacement: bool = False,
) -> Counter:
    """Capture non-layout semantics that visual-only repairs must preserve."""
    inventory: Counter = Counter()
    media_tags = {"a", "audio", "image", "img", "source", "video"}
    semantic_attrs = (
        "alt", "aria-describedby", "aria-label", "aria-labelledby", "role",
    )
    media_index = 0
    for tag in soup.find_all(True):
        if tag.name in media_tags:
            media_index += 1
            media_ref = (
                tag.get("src", "")
                or tag.get("href", "")
                or tag.get("xlink:href", "")
            )
            # A raw-figure/table diagnosis may legitimately replace one image
            # target with a source-grounded crop or generated chart. Keep the
            # media slot/type and accessibility contract frozen while allowing
            # only the raster/SVG-image target to change.
            if allow_image_replacement and tag.name in {"img", "image"}:
                media_ref = "<replaceable-image-target>"
            semantic_values = tuple(tag.get(attr, "") for attr in semantic_attrs)
            inventory[("media-slot", media_index, tag.name, media_ref, *semantic_values)] += 1
        semantic_values = tuple(tag.get(attr, "") for attr in semantic_attrs)
        if any(semantic_values):
            inventory[("accessibility", tag.name, *semantic_values)] += 1
    return inventory


def validate_visual_repair_scope(
    before_html: str,
    after_html: str,
    *,
    allow_image_replacement: bool = False,
    allow_text_case_change: bool = False,
    allow_text_formatting_change: bool = False,
    allow_text_content_change: bool = False,
) -> tuple[bool, str]:
    """Validate invariants shared by all visual-only HTML repairs.

    Layout, geometry, styling, and DOM order may change. Source-visible text
    content, media targets, and accessibility semantics may not. Rendered text
    order is evaluated separately as an advisory signal because a coherent
    reflow can legitimately change it. Raw-figure/table repairs can opt into
    changing an existing image target; image count/type and accessibility
    semantics still remain invariant. Formatting-error repairs may opt into
    case/whitespace normalization while retaining the source content.
    """
    before = BeautifulSoup(before_html, "html.parser")
    after = BeautifulSoup(after_html, "html.parser")

    hidden_ok, hidden_reason = validate_no_hidden_text_duplicates(
        before_html,
        after_html,
    )
    if not hidden_ok:
        return False, hidden_reason

    if not allow_text_content_change:
        before_text = _source_visible_text_inventory(
            before,
            casefold=allow_text_case_change,
            formatting_insensitive=allow_text_formatting_change,
        )
        after_text = _source_visible_text_inventory(
            after,
            casefold=allow_text_case_change,
            formatting_insensitive=allow_text_formatting_change,
        )
        if before_text != after_text:
            return False, "source-visible text content changed"
    before_media = _media_and_accessibility_inventory(
        before,
        allow_image_replacement=allow_image_replacement,
    )
    after_media = _media_and_accessibility_inventory(
        after,
        allow_image_replacement=allow_image_replacement,
    )
    if before_media != after_media:
        return False, "media references or accessibility semantics changed"
    return True, "scope preserved"


def validate_rendered_text_preservation(
    before_state,
    after_state,
    *,
    allow_revealed_text: bool = False,
    allow_text_formatting_change: bool = False,
    allow_text_content_change: bool = False,
) -> tuple[bool, str]:
    """Require a visual repair to preserve text that is actually rendered.

    ``validate_visual_repair_scope`` protects source-level text and semantics,
    but source parsing cannot see CSS effects such as ``display:none`` or an
    ancestor with ``opacity:0``.  HTML spatial extraction records ordered text
    runs that produced visible pixels; comparing their normalized concatenation
    catches those regressions while allowing harmless span/wrapper changes.
    """
    if allow_text_content_change:
        return True, "rendered text change allowed by issue contract"

    if allow_text_formatting_change:
        normalize = lambda runs: list(
            _editorial_directive_insensitive_tokens(runs or [])
        )
    else:
        normalize = lambda runs: " ".join(" ".join(runs or []).split()).split()
    before_tokens = normalize(getattr(before_state, "visible_text_runs", []))
    after_tokens = normalize(getattr(after_state, "visible_text_runs", []))
    if before_tokens == after_tokens:
        return True, "rendered text preserved"

    # Existing visible tokens must remain an ordered subsequence. This catches
    # deletion and reordering while tolerating wrapper/span changes. A repair for
    # clipping/overflow may reveal source text that was already present in the DOM;
    # validate_visual_repair_scope separately guarantees that no source text was
    # added by the visual-only edit.
    cursor = 0
    for token in after_tokens:
        if cursor < len(before_tokens) and token == before_tokens[cursor]:
            cursor += 1
    if cursor != len(before_tokens):
        missing = before_tokens[cursor:cursor + 8]
        detail = ", ".join(repr(token) for token in missing)
        suffix = f"; missing or reordered visible tokens include {detail}" if detail else ""
        return False, f"rendered visible text or reading order changed{suffix}"

    if allow_revealed_text:
        return True, "rendered text preserved; previously clipped source text became visible"

    return False, "new rendered text appeared outside an overflow/clipping repair"


def issues_allow_rendered_text_reveal(issues) -> bool:
    """Return whether current issue contracts permit clipped DOM text to appear."""
    reveal_types = {
        "text_overflow", "container_contract_breach", "out_of_bounds",
    }
    return any(getattr(issue, "issue_type", "") in reveal_types for issue in issues or [])


def issues_allow_support_copy_compression(issues) -> bool:
    """Return whether the judge explicitly authorized support-copy compression.

    This is a narrow visual-repair contract for dense fixed-canvas layouts. It
    does not authorize deleting facts, values, labels, titles, or source notes;
    it only lets the agent shorten the explanatory copy named by the issue when
    geometry alone cannot produce a readable composition.
    """
    for issue in issues or []:
        fix_detail = getattr(issue, "fix_detail", None)
        action_type = (
            getattr(fix_detail, "action_type", "") if fix_detail else ""
        )
        if str(action_type or "").strip().lower() == "compress_support_copy":
            return True
    return False


def issues_allow_visible_text_change(issues) -> bool:
    """Return whether visual issues explicitly authorize visible text edits.

    Most B-family repairs are layout/style only. Narrow exceptions exist for
    explicitly authorized support-copy compression, B14 duplicate removal, and
    B12 formatting normalization. Without this contract, the retention guards
    reject those intended repairs as visual-only text regressions.
    """
    if issues_allow_support_copy_compression(issues):
        return True

    action_types = {
        "remove_element", "remove_text", "rewrite_claim", "merge_text",
        "restructure_layout",
    }
    intent_re = re.compile(
        r"\b(remove|delete|merge|deduplicate|de-duplicate|rewrite|retain one|keep only)\b",
        re.IGNORECASE,
    )
    for issue in issues or []:
        fix_detail = getattr(issue, "fix_detail", None)
        evidence = getattr(issue, "evidence", None)
        text = " ".join(
            part for part in (
                getattr(issue, "planned_fix", ""),
                getattr(issue, "why_this_fails", ""),
                getattr(evidence, "description", "") if evidence else "",
                getattr(fix_detail, "correct_content", "") if fix_detail else "",
                getattr(fix_detail, "target_location", "") if fix_detail else "",
                getattr(fix_detail, "action_type", "") if fix_detail else "",
            )
            if isinstance(part, str) and part.strip()
        )

        if getattr(issue, "issue_type", "") == "formatting_error":
            if re.search(
                r"latex|backslash|braces?|escaped|underscore|caret|subscript|"
                r"superscript|raw\s+(?:math|notation|code)|code\s+artifact|"
                r"formula-heavy|math\s+notation",
                text,
                re.IGNORECASE,
            ):
                return True

        if getattr(issue, "issue_type", "") != "form_redundancy":
            continue
        action_type = (getattr(fix_detail, "action_type", "") or "").lower()
        if action_type in action_types:
            return True
        if intent_re.search(text) and re.search(r"duplicat|redundan|repeat", text, re.IGNORECASE):
            return True
    return False


_SVG_TOPOLOGY_TAGS = {
    "circle", "ellipse", "image", "line", "marker", "path", "polygon",
    "polyline", "rect", "text", "tspan", "use",
}
_SVG_EDGE_TAGS = {"line", "path", "polyline"}
_SVG_SHAPE_TAGS = {"circle", "ellipse", "polygon", "rect"}


def _svg_topology_signatures(soup: BeautifulSoup) -> tuple[dict, ...]:
    signatures = []
    for svg in soup.find_all("svg"):
        counts: Counter = Counter()
        for tag in svg.find_all(True):
            if tag.name in _SVG_TOPOLOGY_TAGS:
                counts[tag.name] += 1
        labels = tuple(
            re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
            for tag in svg.find_all("text")
            if tag.get_text(" ", strip=True)
        )
        non_text = sum(
            count for name, count in counts.items()
            if name not in {"text", "tspan"}
        )
        edge_count = sum(counts.get(name, 0) for name in _SVG_EDGE_TAGS)
        shape_count = sum(counts.get(name, 0) for name in _SVG_SHAPE_TAGS)
        categories = frozenset(name for name, count in counts.items() if count)
        signatures.append({
            "counts": counts,
            "labels": labels,
            "non_text": non_text,
            "edge_count": edge_count,
            "shape_count": shape_count,
            "categories": categories,
        })
    return tuple(signatures)


def validate_svg_topology_preservation(
    before_html: str,
    after_html: str,
) -> tuple[bool, str]:
    """Require SVG repairs to preserve high-level diagram topology."""
    before = BeautifulSoup(before_html, "html.parser")
    after = BeautifulSoup(after_html, "html.parser")
    before_sigs = _svg_topology_signatures(before)
    after_sigs = _svg_topology_signatures(after)

    if len(before_sigs) != len(after_sigs):
        return False, f"SVG count changed ({len(before_sigs)}->{len(after_sigs)})"

    for index, (before_sig, after_sig) in enumerate(zip(before_sigs, after_sigs), 1):
        if before_sig["labels"] != after_sig["labels"]:
            return False, f"SVG {index} text label order changed"

        before_non_text = before_sig["non_text"]
        after_non_text = after_sig["non_text"]
        if before_non_text >= 5 and after_non_text < before_non_text * 0.60:
            return False, (
                f"SVG {index} primitive topology collapsed "
                f"({before_non_text}->{after_non_text})"
            )

        before_edges = before_sig["edge_count"]
        after_edges = after_sig["edge_count"]
        if before_edges >= 1 and after_edges == 0:
            return False, f"SVG {index} connector topology removed ({before_edges}->0)"
        if before_edges >= 4 and after_edges < max(1, int(before_edges * 0.50)):
            return False, f"SVG {index} connector topology collapsed ({before_edges}->{after_edges})"

        before_shapes = before_sig["shape_count"]
        after_shapes = after_sig["shape_count"]
        if before_shapes >= 4 and after_shapes < max(1, int(before_shapes * 0.50)):
            return False, f"SVG {index} node/shape topology collapsed ({before_shapes}->{after_shapes})"

        before_markers = before_sig["counts"].get("marker", 0)
        after_markers = after_sig["counts"].get("marker", 0)
        if after_markers < before_markers:
            return False, f"SVG {index} marker topology dropped ({before_markers}->{after_markers})"

        before_categories = before_sig["categories"]
        after_categories = after_sig["categories"]
        if len(before_categories) >= 4 and len(after_categories) < len(before_categories) - 2:
            return False, f"SVG {index} primitive diversity collapsed"

    return True, "SVG topology preserved"


def validate_svg_repair_scope(before_html: str, after_html: str) -> tuple[bool, str]:
    """Validate the semantic scope of a pure SVG-geometry repair.

    Paths, markers, endpoints, node geometry, and styling may change. Visible
    text, media references, accessibility semantics, semantic DOM outside SVG,
    and high-level SVG topology must remain intact.
    """
    scope_ok, scope_reason = validate_visual_repair_scope(before_html, after_html)
    if not scope_ok:
        return scope_ok, scope_reason

    before = BeautifulSoup(before_html, "html.parser")
    after = BeautifulSoup(after_html, "html.parser")
    before_dom = _non_svg_semantic_inventory(before)
    after_dom = _non_svg_semantic_inventory(after)
    if before_dom != after_dom:
        return False, "semantic DOM outside SVG changed"

    before_svg = _svg_semantic_inventory(before)
    after_svg = _svg_semantic_inventory(after)
    if before_svg != after_svg:
        return False, "SVG accessibility labels, descriptions, or media changed"

    topology_ok, topology_reason = validate_svg_topology_preservation(
        before_html, after_html,
    )
    if not topology_ok:
        return False, topology_reason

    return True, "scope preserved"


def _extract_json(response: str) -> dict | None:
    """Extract JSON from LLM response (code blocks or direct)."""
    # Try code fences
    json_blocks = re.findall(
        r'```(?:json)?\s*\n(.*?)```', response, re.DOTALL,
    )
    for block in json_blocks:
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            pass

    # Try direct JSON
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    # Try line-by-line: handles multi-JSON-object responses where each
    # line is a separate valid JSON object (plan + apply_edits + verify).
    # This must come BEFORE brace matching because CSS content inside
    # JSON string values contains { } that confuse naive depth counting.
    for line in response.strip().split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "tool" in data:
                    return data
            except json.JSONDecodeError:
                pass

    # Try extracting { ... } with brace matching (fallback for responses
    # with JSON embedded in prose text)
    depth = 0
    start = None
    for i, ch in enumerate(response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(response[start:i + 1])
                except json.JSONDecodeError:
                    start = None

    return None


def _has_extra_json(response: str) -> bool:
    """Check whether the response contains more than one top-level JSON object.

    Returns True if multiple JSON objects are detected, meaning the LLM
    tried to output multiple tool calls in a single message.
    """
    # Fast path: line-by-line check (handles the common multi-line pattern)
    json_count = 0
    for line in response.strip().split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                json.loads(line)
                json_count += 1
                if json_count >= 2:
                    return True
            except json.JSONDecodeError:
                pass
    # Fallback: brace matching for JSON embedded in prose
    count = 0
    depth = 0
    start = None
    for i, ch in enumerate(response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    json.loads(response[start:i + 1])
                    count += 1
                    if count >= 2:
                        return True
                except json.JSONDecodeError:
                    pass
                start = None
    return False


def _extract_all_json(response: str) -> list[dict]:
    """Extract the contiguous prefix of valid top-level tool calls.

    A malformed object between two valid calls is a sequencing barrier.  Do not
    silently skip it and execute a later verification against unchanged code.
    """
    results = []
    # Fast path: line-by-line extraction (common multi-line pattern)
    for line in response.strip().split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "tool" in data:
                    results.append(data)
                elif results:
                    break
            except json.JSONDecodeError:
                if results:
                    break
        elif line and results:
            break
    if results:
        return results
    # Fallback: brace matching for JSON embedded in prose
    depth = 0
    start = None
    for i, ch in enumerate(response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    data = json.loads(response[start:i + 1])
                    if isinstance(data, dict) and "tool" in data:
                        results.append(data)
                    elif results:
                        break
                except json.JSONDecodeError:
                    if results:
                        break
                start = None
    return results


def _apply_edits(code: str, edits: list[dict]) -> str:
    """Apply search/replace edits sequentially.

    Replaces one unambiguous occurrence by default. Callers may provide
    ``expected_matches`` to replace all verified matches, or ``occurrence``
    (1-based) to replace one specific match.
    Returns the modified code.
    """
    modified = code
    for edit in edits:
        search = edit.get("search", "")
        replace = edit.get("replace", "")
        insert_after = edit.get("insert_after", "")

        occurrence = edit.get("occurrence")
        expected_matches = edit.get("expected_matches")

        if insert_after and not search:
            # Insertion mode
            matches = modified.count(insert_after)
            if occurrence is not None:
                try:
                    occurrence = int(occurrence)
                except (TypeError, ValueError):
                    continue
                if occurrence < 1 or occurrence > matches:
                    continue
                idx = -1
                start = 0
                for _ in range(occurrence):
                    idx = modified.find(insert_after, start)
                    start = idx + len(insert_after)
            elif matches == 1:
                idx = modified.find(insert_after)
            else:
                continue
            if idx >= 0:
                line_end = modified.find("\n", idx + len(insert_after))
                if line_end >= 0:
                    modified = (
                        modified[:line_end]
                        + "\n" + replace
                        + modified[line_end:]
                    )
        elif search:
            matches = modified.count(search)
            if occurrence is not None:
                try:
                    occurrence = int(occurrence)
                except (TypeError, ValueError):
                    continue
                if occurrence < 1 or occurrence > matches:
                    continue
                start = 0
                idx = -1
                for _ in range(occurrence):
                    idx = modified.find(search, start)
                    start = idx + len(search)
                modified = modified[:idx] + replace + modified[idx + len(search):]
            elif expected_matches is not None:
                try:
                    expected = int(expected_matches)
                except (TypeError, ValueError):
                    continue
                if matches == expected and matches > 0:
                    modified = modified.replace(search, replace)
            elif matches == 1:
                modified = modified.replace(search, replace, 1)

    return modified


def _parse_viz_data(response: str) -> dict | None:
    """Parse viz_data JSON from response."""
    data = _extract_json(response)
    if not data:
        return None
    if (isinstance(data.get("categories"), list)
            and isinstance(data.get("series"), list)
            and len(data["categories"]) > 0
            and len(data["series"]) > 0):
        return data
    return None


# ── Extracted utilities (previously duplicated closures in agent_repair.py) ──

def dom_parent_path(dom_path: str) -> str:
    """Return the parent portion of a '/'-separated DOM path."""
    return dom_path.rsplit("/", 1)[0] if "/" in dom_path else ""


def compute_overflow_px(blocks, canvas_h: int = 720) -> int:
    """Compute max overflow past canvas bottom from block bounding boxes."""
    max_bottom = max(
        (b.bbox_px[1] + b.bbox_px[3] for b in blocks),
        default=0,
    )
    return max(0, int(max_bottom - canvas_h))
