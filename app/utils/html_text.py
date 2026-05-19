"""Extract visible text and title from slide HTML using BeautifulSoup."""

from __future__ import annotations

from bs4 import BeautifulSoup

_TITLE_TAGS = {"h1", "h2"}
_TITLE_CLASSES = {"title", "slide-title", "main-title", "heading"}


def extract_title_and_body(html: str) -> tuple[str, str]:
    """Return (title, body_text) from slide HTML.

    Title detection priority:
      1. <h1> or <h2> tag
      2. Any element whose CSS class intersects _TITLE_CLASSES
      3. First visible text fragment (fallback)

    Body is all remaining visible text joined by newlines.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-visible elements
    for tag in soup.find_all(["style", "script"]):
        tag.decompose()

    title_el = None

    # Priority 1: h1 / h2
    for tag_name in ("h1", "h2"):
        title_el = soup.find(tag_name)
        if title_el:
            break

    # Priority 2: element with title-like class
    if not title_el:
        for el in soup.find_all(True, class_=True):
            classes = {c.lower() for c in el.get("class", [])}
            if classes & _TITLE_CLASSES:
                title_el = el
                break

    title = ""
    if title_el:
        title = title_el.get_text(separator=" ", strip=True)
        title_el.decompose()  # remove so it doesn't appear in body

    body = soup.get_text(separator="\n", strip=True)

    # Fallback: use first line of body as title
    if not title and body:
        lines = [l for l in body.split("\n") if l.strip()]
        if lines:
            title = lines[0][:100]
            body = "\n".join(lines[1:])

    return title, body
