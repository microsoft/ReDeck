"""Issue-scoped content edits with frozen source evidence and shared repair guards."""

import html
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from .evaluation.snapshot import file_hash
from .repair import validate_repair


CONTENT_TYPES = frozenset({
    "fabricated", "incorrect_claim", "numeric_error", "entity_error",
    "chart_misinterpretation", "unfaithful_compression", "missing_entity",
    "missing_context", "missing_point", "missing_evidence", "missing_conclusion",
    "unsupported_causality", "misleading_omission", "implementation_language",
})
POLICY_VERSION = "source-bound-content-repair-v1"


class Fragment(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.stack = []
        self.feed(source)
        if self.stack:
            raise ValueError("Content fragments must have balanced markup")

    def handle_starttag(self, tag, attrs):
        if tag not in {"p", "li", "tr", "td", "th", "span", "strong", "em", "b", "i", "sup", "sub", "br", "h1", "h2", "h3"}:
            raise ValueError("Content edits cannot change active code, media or page containers")
        if any(name.lower().startswith("on") or name.lower() in {"style", "src", "href"} for name, value in attrs):
            raise ValueError("Content fragments cannot carry styling or resource attributes")
        self.tags.append((tag, tuple(attrs)))
        if tag != "br":
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("Content fragments must have balanced markup")
        self.tags.append(("/" + tag, ()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)

    def handle_data(self, data):
        self.text.append(data)

    def handle_comment(self, data):
        raise ValueError("Content edits cannot inject comments")

    def handle_decl(self, decl):
        raise ValueError("Content edits cannot inject declarations")

    def handle_pi(self, data):
        raise ValueError("Content edits cannot inject processing instructions")


class BodySpans(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [match.end() for match in re.finditer("\n", source)]
        self.markup = []
        self.blocked = []
        self.ignored = 0
        self.feed(source)

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        start = self.source_offset()
        self.markup.append((start, start + len(self.get_starttag_text())))
        if tag in {"script", "style", "title", "template", "textarea"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        start = self.source_offset()
        self.markup.append((start, self.source.index(">", start) + 1))
        if tag in {"script", "style", "title", "template", "textarea"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data):
        if self.ignored:
            self.blocked.append((self.source_offset(), self.source_offset() + len(data)))

    def handle_comment(self, data):
        self.blocked.append((self.source_offset(), self.source_offset() + len(data) + 7))

    def allows(self, start, end):
        return (not any(start < right and end > left for left, right in self.blocked)
                and all(not (start < right and end > left) or (start <= left and end >= right)
                        for left, right in self.markup))


def normalized(text):
    return " ".join(html.unescape(text).split())


def tokens(text):
    return Counter(re.findall(r"\w+|[^\w\s]", normalized(text)))


class SourceCatalog:
    def __init__(self, context):
        self.context = context
        self.root = Path(context["source_dir"]).resolve()
        self.documents = {}
        self.verify()
        for name in context["source_hashes"]:
            if Path(name).suffix.lower() in {".md", ".json", ".txt"}:
                self.documents[name] = (self.root / name).read_text()
        if not self.documents.get("paper_full.md"):
            raise ValueError("Content repair requires the frozen source paper")

    def verify(self):
        for name, expected in self.context["source_hashes"].items():
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root) or file_hash(path) != expected:
                raise ValueError(f"Frozen repair source changed: {name}")

    def search(self, query, tables_only=False):
        self.verify()
        terms = set(re.findall(r"\w{3,}", query.lower()))
        matches = []
        for name, text in self.documents.items():
            if tables_only and not name.startswith("tables/"):
                continue
            for offset in range(0, len(text), 1800):
                excerpt = text[offset:offset + 2400]
                score = sum(term in excerpt.lower() for term in terms)
                if score:
                    matches.append((score, name, offset, excerpt))
        return self.merge_results([{"source_ref": name, "offset": offset, "excerpt": excerpt}
                for score, name, offset, excerpt in sorted(matches, key=lambda item: -item[0])[:5]])

    def merge_results(self, results, max_characters=12000):
        self.verify()
        merged = []
        for result in results:
            reference, start, excerpt = result["source_ref"], result["offset"], result["excerpt"]
            end = start + len(excerpt)
            if self.documents[reference][start:end] != excerpt:
                raise ValueError("Source retrieval interval does not match frozen evidence")
            overlaps = [item for item in merged if item["source_ref"] == reference
                        and start <= item["offset"] + len(item["excerpt"]) and item["offset"] <= end]
            for item in overlaps:
                start = min(start, item["offset"])
                end = max(end, item["offset"] + len(item["excerpt"]))
            size = sum(len(item["excerpt"]) for item in merged if item not in overlaps) + end - start
            if size > max_characters:
                continue
            position = min((merged.index(item) for item in overlaps), default=len(merged))
            merged = [item for item in merged if item not in overlaps]
            merged.insert(position, {"source_ref": reference, "offset": start,
                                     "excerpt": self.documents[reference][start:end]})
        return merged

    def validate_quote(self, edit):
        self.verify()
        reference = edit.get("source_ref", "")
        quotes = edit.get("source_quotes", [edit.get("source_quote", "")])
        if reference not in self.documents or not isinstance(quotes, list) or not 1 <= len(quotes) <= 4:
            raise ValueError("Every factual edit needs a frozen source reference and exact quote")
        if any(not isinstance(quote, str) or len(normalized(quote)) < 12
               or normalized(quote) not in normalized(self.documents[reference]) for quote in quotes):
            raise ValueError("Source quote must be a contiguous exact passage from the frozen source; use source_quotes for separate passages")
        added_numbers = set(re.findall(r"\d+(?:\.\d+)?", edit.get("replace", "")))
        old_numbers = set(re.findall(r"\d+(?:\.\d+)?", edit.get("search", "")))
        if (added_numbers - old_numbers) - set(re.findall(r"\d+(?:\.\d+)?", " ".join(quotes))):
            raise ValueError("New numbers must occur in the cited source quote")


def actionable_issues(issues, slide_id):
    return [issue for issue in issues if issue.get("issue_type") in CONTENT_TYPES
            and issue.get("affected_slides") == [slide_id]
            and issue.get("status", "open") == "open"
            and issue.get("observation_status") != "unconfirmed"
            and issue.get("recommended_action") != "KEEP"]


def validate_editorial(edit, issue, catalog):
    from .evaluation.editorial import LEAK_PATTERNS
    from .domain.editorial import SYNTHETIC_SOURCE_FORMS

    evidence = issue.get("evidence") or {}
    observed = normalized(evidence.get("observed_text", ""))
    search, replacement = normalized(edit["search"]), normalized(edit["replace"])
    if not observed or search != observed:
        raise ValueError("Editorial edits must target the exact observed text object")
    pattern = next((pattern for kind, pattern, suggestion in LEAK_PATTERNS if kind == issue.get("sub_type")), None)
    if not pattern or not re.search(pattern, search, re.I):
        raise ValueError("Unknown editorial cleanup contract")
    if any(re.search(pattern, text, re.I) for text in catalog.documents.values()):
        raise ValueError("Possible legitimate source terminology; requires source review")
    if edit.get("source_ref"):
        catalog.validate_quote(edit)
        return
    if issue.get("sub_type") == "internal-source":
        synthetic = any(re.fullmatch(re.escape(form).replace(r"\{slide_id\}", r"\d+") + r"\.?", search, re.I)
                        for form in SYNTHETIC_SOURCE_FORMS)
        if replacement or not synthetic:
            raise ValueError("Only the diagnosed synthetic attribution may be removed without a replacement citation")
    elif not re.fullmatch(pattern, search, re.I) or replacement not in {"Evidence", "Context", "Supporting evidence", "Details", ""}:
        raise ValueError("Editorial cleanup cannot remove surrounding facts or introduce new claims")


def apply_proposal(original, proposal, issues, catalog, allow_layout=True):
    if proposal.get("tool") != "apply_edits":
        raise ValueError("Expected apply_edits proposal")
    edits = proposal.get("edits")
    if not isinstance(edits, list) or not 1 <= len(edits) <= 8:
        raise ValueError("Supply one to eight issue-scoped content edits")
    issue_map = {issue["issue_id"]: issue for issue in issues}
    current = original
    removed, added = Counter(), Counter()
    for edit in edits:
        if edit.get("issue_id") not in issue_map:
            raise ValueError("Edit is not bound to an actionable issue")
        issue = issue_map[edit["issue_id"]]
        search, replacement = edit.get("search"), edit.get("replace")
        if not isinstance(search, str) or not isinstance(replacement, str) or not search or current.count(search) != 1:
            raise ValueError("Content edit must have one unique exact match in CURRENT HTML")
        body = re.search(r"<body\b[^>]*>(.*)</body\s*>", current, re.I | re.S)
        if not body or search not in body.group(1):
            raise ValueError("Content edit must target the slide body")
        start = current.index(search)
        if not BodySpans(current).allows(start, start + len(search)):
            raise ValueError("Content edits cannot target attributes, comments or code")
        before, after = Fragment(search), Fragment(replacement)
        operation = edit.get("operation", "replace")
        if issue["issue_type"] == "implementation_language":
            if operation != "replace":
                raise ValueError("Editorial cleanup is replacement-only")
            validate_editorial(edit, issue, catalog)
        else:
            catalog.validate_quote(edit)
        if operation == "replace":
            if before.tags != after.tags or not normalized(" ".join(before.text)):
                raise ValueError("Replacement must preserve markup and target visible text")
            removed.update(tokens(" ".join(before.text)))
            current = current.replace(search, replacement, 1)
        elif operation == "insert_after":
            if not issue["issue_type"].startswith("missing_") or not re.search(r"</(?:p|li|tr)>\s*$", search, re.I):
                raise ValueError("Insertions require a missing-content issue and a closed paragraph, list item or row")
            if not after.tags or any(attrs for tag, attrs in after.tags):
                raise ValueError("Inserted evidence must use plain semantic markup without attributes")
            current = current.replace(search, search + replacement, 1)
        else:
            raise ValueError("Unknown content operation")
        added.update(tokens(" ".join(after.text)))
    semantic_base = current
    css_edits = proposal.get("css_edits", [])
    if not isinstance(css_edits, list) or len(css_edits) > 8 or (css_edits and not allow_layout):
        raise ValueError("Layout edits are disabled or exceed the local patch budget")
    for edit in css_edits:
        search, replacement = edit.get("search"), edit.get("replace")
        if not isinstance(search, str) or not search or not isinstance(replacement, str) or re.search(r"[<>]|url\s*\(|@import", replacement, re.I):
            raise ValueError("CSS edits cannot inject HTML or resource requests")
        matches = [match for match in re.finditer(r"<style\b[^>]*>(.*?)</style\s*>", current, re.I | re.S)
                   if match.group(1).count(search)]
        if len(matches) != 1 or matches[0].group(1).count(search) != 1:
            raise ValueError("CSS edit must match once inside an existing style block")
        match = matches[0]
        current = current[:match.start(1)] + match.group(1).replace(search, replacement, 1) + current[match.end(1):]
    guard = validate_repair(semantic_base, current)
    if not guard.accepted:
        raise ValueError("Content/layout guard: " + "; ".join(guard.reasons))
    return {"html": current, "semantic_base": semantic_base, "guard": guard,
            "removed_tokens": dict(removed), "added_tokens": dict(added), "proposal": proposal}


def rendered_edit_matches(before, after, contract):
    before_tokens = tokens(" ".join(item.get("text_content", "") for item in before["objects"]))
    after_tokens = tokens(" ".join(item.get("text_content", "") for item in after["objects"]))
    expected = before_tokens.copy()
    expected.subtract(contract["removed_tokens"])
    if any(count < 0 for count in expected.values()):
        return False
    expected.update(contract["added_tokens"])
    return +expected == after_tokens


def content_coverage_gate(report, slide_id):
    content = report["routes"]["content"]
    records = [record for record in content["probes"] if slide_id in record.get("scope_slide_ids", [])]
    from .evaluation.coordinator import DEFAULT_PROBES

    expected = set(DEFAULT_PROBES) | {"content.editorial_copy"}
    if len(records) != len(expected) or {record["probe_id"] for record in records} != expected:
        return False, "Full configured content probe coverage is required for content edits"
    for record in records:
        if (record["probe_id"] in {"C01", "C05"} and record["status"] == "skipped"
                and record.get("reason") == "Full-deck probe requires every blueprint slide"):
            continue
        if record["status"] not in {"passed", "failed"}:
            return False, "Content evaluation incomplete or unavailable"
    return True, "All applicable content probes completed"


def scoped_content_findings(report, slide_id=None):
    return [issue for issue in report["routes"]["content"].get("issues", [])
            if slide_id is None or not issue.get("affected_slides") or slide_id in issue["affected_slides"]]


def content_gate(report, slide_id):
    complete, reason = content_coverage_gate(report, slide_id)
    if not complete:
        return False, reason
    pending = scoped_content_findings(report, slide_id)
    if pending:
        return False, "Content findings remain: " + json.dumps(pending, ensure_ascii=False)
    return True, "All applicable content probes accept this page; skipped deck coverage remains incomplete"


def new_content_findings(before, after, slide_id=None):
    def counts(report):
        return Counter(content_finding_key(issue) for issue in scoped_content_findings(report, slide_id))

    return bool(counts(after) - counts(before))


def content_finding_key(issue):
    evidence = issue.get("evidence") or {}
    detail = issue.get("fix_detail") or {}
    refs = tuple(sorted(evidence.get("object_refs") or [])) if isinstance(evidence, dict) else ()
    source_refs = tuple(sorted(evidence.get("source_refs") or [])) if isinstance(evidence, dict) else ()
    observed = evidence.get("observed_text", "") if isinstance(evidence, dict) else ""
    target = refs or normalized(observed or detail.get("target_location", "")).casefold()
    expected = normalized(detail.get("correct_content", "")).casefold()
    source = source_refs or normalized(detail.get("source_ref", "")).casefold()
    fallback = "" if target else normalized(evidence.get("description", "") if isinstance(evidence, dict) else evidence).casefold()
    return (issue.get("probe_id") or issue.get("rubric_id"), issue.get("issue_type"),
            tuple(sorted(issue.get("affected_slides") or [])), target, source, expected, fallback)
