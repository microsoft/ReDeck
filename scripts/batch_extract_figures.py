"""Batch extract figures for all cases missing them."""
import json
import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(message)s")

from app.modules.figure_extractor import FigureExtractor

cases_dir = Path("cases")
extracted = 0
errors = 0

for case_dir in sorted(cases_dir.glob("db_*")):
    source_pack = case_dir / "source_pack"
    pdf = source_pack / "paper.pdf"
    if not pdf.exists():
        continue
    
    # Skip if already extracted
    figs_dir = source_pack / "figures"
    ss_dir = source_pack / "screenshots"
    if ss_dir.exists() and len(list(ss_dir.glob("*.png"))) > 0:
        continue
    
    try:
        # Clean old dirs
        for d in ["figures", "tables", "screenshots"]:
            p = source_pack / d
            if p.exists():
                shutil.rmtree(p)
        
        extractor = FigureExtractor(source_pack)
        figures, tables, screenshots = extractor.extract(pdf)
        
        # Update source_store.json assets
        ss_path = source_pack / "source_store.json"
        if ss_path.exists():
            ss = json.loads(ss_path.read_text())
            all_refs = []
            for f in figures + screenshots:
                all_refs.append({
                    "figure_id": f.figure_id, "source_file": f.source_file,
                    "image_path": str(f.image_path), "caption": f.caption,
                    "description": f.description, "page_number": f.page_number,
                    "width": f.width, "height": f.height, "figure_type": f.figure_type,
                })
            ss["assets"] = all_refs
            ss_path.write_text(json.dumps(ss, indent=2, ensure_ascii=False))
        
        extracted += 1
        print(f"{case_dir.name}: {len(figures)} figs, {len(tables)} tbls, {len(screenshots)} ss")
    except Exception as e:
        errors += 1
        print(f"{case_dir.name}: ERROR {e}")

print(f"\nDone: {extracted} extracted, {errors} errors")
