import json
import re
import wave
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from bs4 import BeautifulSoup
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo"
VIDEO = ROOT / "redeck-video"


def test_readme_and_website_share_the_paper_url():
    paper_url = "https://arxiv.org/abs/2609.00194"
    readme = (ROOT / "README.md").read_text()
    assert re.search(r"\[!\[Paper\]\([^\n]+?\)\]\(" + re.escape(paper_url) + r"\)", readme)
    homepage = BeautifulSoup((DEMO / "index.html").read_text(), "html.parser")
    paper_links = [link for link in homepage.find_all("a") if link.get_text(strip=True) == "Paper"]
    assert len(paper_links) == 1 and paper_links[0]["href"] == paper_url
    technical = BeautifulSoup((DEMO / "tech.html").read_text(), "html.parser")
    assert "url={" + paper_url + "}" in technical.select_one(".citation-box").get_text()


@pytest.mark.parametrize("name", ["index.html", "tech.html", "team.html", "video.html"])
def test_website_local_resources_and_anchors_exist(name):
    page = DEMO / name
    soup = BeautifulSoup(page.read_text(), "html.parser")
    for node in soup.find_all(True):
        for attribute in ("href", "src", "poster"):
            reference = node.get(attribute)
            if not reference:
                continue
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc:
                continue
            target = page.parent / unquote(parsed.path) if parsed.path else page
            assert target.is_file(), (name, reference)
            if parsed.fragment and target.suffix == ".html":
                destination = BeautifulSoup(target.read_text(), "html.parser")
                assert destination.find(id=unquote(parsed.fragment)), (name, reference)


def test_repair_examples_preserve_assets_and_manual_edit_disclosures():
    inventory = (DEMO / "repair_pairs/README.md").read_text()
    rows = re.findall(r"^\| \d+ \| ([^|]+) \|.*\| ([^|]+) \|$", inventory, re.MULTILINE)
    expected = {name.strip() for name, _ in rows}
    manual = {name.strip() for name, note in rows if "✓" in note}
    soup = BeautifulSoup((DEMO / "index.html").read_text(), "html.parser")
    after = soup.select("a.repair-shot.after")
    assert len(expected) == len(after) == 14
    assert {Path(link["href"]).stem for link in after} == expected
    assert {Path(link["href"]).stem for link in after if "manual post-edit" in link.get_text()} == manual
    for name in expected:
        for phase in ("before", "after"):
            assert (DEMO / f"repair_pairs/{phase}/html/{name}.html").is_file()
            for image in (DEMO / f"repair_pairs/{phase}/png/{name}.png", DEMO / f"demo-pairs/{phase}/{name}.png"):
                with Image.open(image) as opened:
                    opened.verify()


def test_video_narration_and_trajectory_sources_exist():
    cues = json.loads((VIDEO / "narration/v6-cues.json").read_text())
    assert cues and len({cue["id"] for cue in cues}) == len(cues)
    for cue in cues:
        assert cue["start"] < cue["end"]
        with wave.open(str(VIDEO / f"public/narration-v6/{cue['id']}.wav")) as audio:
            assert audio.getnframes() > 0
    for source in (VIDEO / "src").rglob("*.tsx"):
        text = source.read_text()
        for reference in re.findall(r'"((?:trajectory|crops|branding|paper-assets)/[^"$]+\.(?:png|svg))"', text):
            assert (VIDEO / "public" / reference).is_file(), reference
        for name, count in re.findall(r'makeRunFrames\("([^"]+)", makeActions\((\d+)', text):
            assert (VIDEO / f"public/trajectory/{name}_run_before.png").is_file()
            for index in range(int(count)):
                assert (VIDEO / f"public/trajectory/{name}_run_step_{index:02d}.png").is_file()


def test_showcase_projects_media_licenses_and_deployment_remain_present():
    required = (
        "demo/assets/redeck-demo.mp4", "demo/assets/redeck-demo-poster.png",
        "redeck-video/package.json", "redeck-video/package-lock.json", "redeck-video/src/Root.tsx",
        "redeck-video/public/audio/inspired-redeck-81s.mp3", "redeck-video/public/audio/INSPIRED_LICENSE.md",
        "assets/redeck_pipeline.pdf", "assets/redeck_pipeline.png",
        ".github/workflows/deploy-demo-pages.yml",
    )
    for name in required:
        assert (ROOT / name).is_file() and (ROOT / name).stat().st_size > 0, name
    assert "path: demo" in (ROOT / ".github/workflows/deploy-demo-pages.yml").read_text()
