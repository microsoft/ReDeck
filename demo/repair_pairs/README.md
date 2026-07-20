# ReDeck Demo Repair Pairs

14 before/after slide pairs demonstrating ReDeck's automated spatial-issue repair pipeline.

## Directory Structure

```
demo_pairs/
├── before/          # Defective slides (input to repair)
│   ├── html/        # Source HTML
│   └── png/         # Rendered 1280×720 @2x screenshots
├── after/           # Repaired slides (output of 4-turn repair)
│   ├── html/        # Repaired HTML
│   └── png/         # Rendered 1280×720 @2x screenshots
└── README.md
```

## Pair Inventory

| # | ID | Source | Before Issues | After Issues | Primary Defect Types | Manual Post-Edit |
|---|-----|--------|:---:|:---:|------|:---:|
| 1 | d171 | demo_200 (injected) | 129 | 0 | overlap(24), occlusion(55), overflow(18), OOB(17), clip(15) | ✓ SVG viewBox/font |
| 2 | d89 | demo_200 (injected) | 139 | 0 | overlap(60), clip(33), overflow(25), OOB(10), truncation(6) | — |
| 3 | d147 | demo_200 (injected) | 77 | 0 | overlap(30), clip(12), OOB(12), overflow(9), truncation(8) | ✓ clipPath width, SVG text color |
| 4 | d58 | demo_200 (injected) | 81 | 0 | overlap(31), OOB(15), overflow(11), clip(8), truncation(9) | — |
| 5 | d178 | demo_200 (injected) | 51 | 0 | overflow(17), OOB(13), clip(12), overlap(8) | ✓ metric spacing, m-note trimmed |
| 6 | d69 | demo_200 (injected) | 42 | 0 | overlap(16), clip(14), OOB(8), overflow(3) | — |
| 7 | d13 | demo_200 (injected) | 35 | 0 | OOB(13), overlap(11), clip(6), overflow(5) | ✓ rule hidden, line-height, border removed |
| 8 | d78 | demo_200 (injected) | 33 | 0 | overlap(14), OOB(5), clip(5), occlusion(5), overflow(3) | ✓ overflow-box reflowed into table-wrap |
| 9 | d94 | demo_200 (injected) | 26 | 0 | overlap(11), clip(8), OOB(3), overflow(2) | ✓ SVG label font-size 16→12 |
| 10 | d181 | demo_200 (injected) | 26 | 0 | clip(9), OOB(7), overlap(4), overflow(4) | — |
| 11 | d12 | demo_200 (injected) | 24 | 0 | OOB(7), clip(7), overlap(5), overflow(4) | ✓ KPI label contrast improved |
| 12 | d39 | demo_200 (injected) | 20 | 0 | OOB(6), clip(6), overflow(4), overlap(3) | — |
| 13 | d120 | demo_200 (injected) | 17 | 0 | overlap(8), clip(4), OOB(2), overflow(2) | ✓ floating-note border removed |
| 14 | p43 | v2.0_batch_palette (transfer) | 7 | 0 | overlap(7) | — |

**Total**: 707 issues detected before → 0 after repair.

## Source Datasets

### demo_200 (13 pairs: d12–d181)
- **Origin**: 200 HTML slides with programmatically injected spatial defects
- **Defect types**: overlap displacement, overflow:hidden truncation, font-size inflation, OOB positioning, low contrast, SVG clipping
- **Pipeline**: `repair_v3` config, 4 repair turns with GPT-4o
- **Before assets**: `runs/demo_200/repair_v3/turn_00/`
- **After assets**: `runs/demo_200/repair_v3/turn_04/`

### v2.0_batch_palette (1 pair: p43)
- **Origin**: 446 slides generated via image-seed → LLM style transfer pipeline
- **Original case**: `ACL_2024_RAGTruth_title_P01_coral_tide`
- **Defect source**: Natural generation artifacts (not injected)
- **Pipeline**: Same repair config, 4 turns
- **Before assets**: `runs/v2.0_batch_palette_repair/repair/turn_00/`
- **After assets**: `runs/v2.0_batch_palette_repair/repair/turn_04/`
- **Name mapping**: `runs/v2.0_batch_palette_repair/slide_name_mapping.txt`

## Manual Post-Edits

8 of 14 pairs received targeted manual CSS/HTML edits after automated repair to polish visual quality:

| Slide | Edits |
|-------|-------|
| d171 | SVG viewBox widened (370→460), font-size increased (8→13/15), green rect widened, subtitle trimmed |
| d147 | SVG clipPath width 210→300, `.mini.primary/.secondary` text color #FFFFFF→#34464A |
| d178 | metric-list gap 2→4px, padding 3→5px, m-note line-height 1.15→1.25, all m-note text trimmed to 1 line |
| d13 | `.rule` display:none, tbody line-height 1.05→1.2, table-wrap border-bottom removed |
| d78 | overflow-box moved from position:absolute into table-wrap flow, width 220→230, text trimmed |
| d94 | SVG label font-size 16→12px |
| d12 | kpi-foot color #D7CEC8→#7a706a, kpi-label color #6f6865→#4a4340 |
| d120 | floating-note border-top removed, top 628→636px |

## Viewing

Open `runs/selected_demo_pairs.html` in a browser for an interactive side-by-side comparison with comment/annotation support.
