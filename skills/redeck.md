---
name: redeck
description: Generate and repair HTML presentation slides with render-grounded spatial verification. Use when creating slides from papers/documents or fixing layout issues in existing HTML slides.
---

# ReDeck: Render-Grounded Slide Generation & Repair

Generate professional HTML slides and ensure they are free of spatial defects using a Playwright-based spatial oracle that gives **pixel-precise layout feedback**.

## When to Use

- User asks to **create slides/deck** from a paper, document, or any content
- User asks to **fix/repair HTML slides** with layout problems
- User asks to **check slide quality** or detect spatial issues

## Prerequisites & Setup

```bash
pip install playwright && playwright install chromium
```

On first use, create the verify_layout tool by running the setup command in the **Embedded Script** section below.

---

## Slide Design

**Design boldly — verify_layout is your safety net.** Don't settle for plain bullet lists. The whole point of having a spatial oracle is that you can attempt ambitious layouts and fix issues if they arise, rather than playing it safe.

Prefer rich layouts: two-column comparisons, metric cards with big numbers, architecture diagrams with flow arrows, timelines, tables with highlighted rows, code blocks with annotations. If a naive Claude Code would just write bullets, you should do better — that's the value of this skill.

### Hard Constraints (the only things you can't break)

- **Viewport**: 1280×720 px. Body: `width: 1280px; height: 720px; overflow: hidden;`
- **Units**: All sizing in `px` — no em, rem, % for layout-critical properties
- **Safe margins**: 40px from all edges → usable area 1200×640 px
- **CSS reset**: `* { margin: 0; padding: 0; box-sizing: border-box; }`
- **Self-contained**: All CSS in `<style>` tag, no external stylesheets
- **Font minimums**: Body text ≥ 14px, headings ≥ 22px
- **After generating EACH slide**: run verify_layout — if issues appear, fix them. That's the loop. Don't avoid complex designs to dodge issues.

---

## Full Workflow

### Generating a Deck

1. **Plan**: Decide slide count and one main proposition per slide
2. **Generate**: Write each slide as a complete self-contained HTML file
3. **Verify each slide**: After writing each HTML file, run:
   ```bash
   python ~/.cache/redeck/verify_layout.py slide_XX.html
   ```
4. **Fix immediately**: If issues found, edit and re-verify before moving to next slide
5. **Final batch check**: After all slides done:
   ```bash
   python ~/.cache/redeck/verify_layout.py --dir ./slides/
   ```
6. **Deliver**: HTML files (open in browser, print to PDF)

### Fixing Existing Slides

1. Run verify_layout on the slide(s) to see current issues
2. Read the `📐 LAYOUT ANCHOR` section to understand element positions
3. Fix issues following the Repair Strategy below
4. Verify after EVERY edit
5. Repeat until 0 issues

---

## Repair Strategy

### Diagnosis First

Before editing, ALWAYS read the `📐 LAYOUT ANCHOR` from verify_layout output. It shows every element's exact `(x, y) width×height` in px. Plan edits mathematically from this data — never guess pixel positions.

### Fix Priority

1. **Root-cause space conflicts** — If total content height > 680px, you must compress first (shrink figures, reduce padding, tighten gaps) before adjusting positions
2. **Overlap** — Fix by adjusting `top` values after resolving space
3. **Text overflow** — Reduce font or increase container
4. **OOB / Clipping** — Usually resolves as side effect of fixing overlaps
5. **Low contrast** — Fix last; pure color changes don't cause regressions

### Repair Patterns

**OVERLAP (elements collide):**
- Read layout anchor → calculate: element B should start at A.top + A.height + gap (8-16px)
- When 5+ overlaps exist, do a **full reflow**: recalculate ALL top positions in one edit
- Never push one element down without checking if it then overlaps something below

**TEXT OVERFLOW (scrollHeight > clientHeight):**
- Escalation ladder:
  1. Increase container height (if space available)
  2. Reduce font-size by 1-2px (minimum 14px for body)
  3. Reduce padding (16px → 10px)
  4. Condense text (remove filler phrases, keep technical specifics)
  5. Restructure layout (two-column → single, remove a section)
- NEVER set `overflow:hidden` to "fix" overflow — that creates clipping

**OUT OF BOUNDS (past 1280×720 canvas):**
- If using `bottom: Xpx` positioning → switch to `top:` with calculated value
- If content too tall → compress elements above

**CLIPPING (overflow:hidden hides content):**
- Find parent with `overflow:hidden` → increase its height or reduce child content
- Body `overflow:hidden` is mandatory — fix by making content fit within 720px

**LOW CONTRAST (WCAG AA violation):**
- Body text (< 18pt): ratio ≥ 4.5:1
- Large text (≥ 18pt): ratio ≥ 3.0:1
- Fix: darken text color or lighten background. Never use light accent colors as text on white

### Key Repair Principles

1. **First do no harm** — A fix that creates a new issue is a net negative. Check verify_layout after EVERY edit.
2. **Scale edits to the problem** — 20px adjustment on 1280px canvas is invisible. If coverage is 40%, double container sizes, don't nudge 10px.
3. **Spatial compensation** — If you shrink/condense content, you MUST expand remaining elements to maintain visual density.
4. **Persistent issues = aggressive action** — If a defect persists after 2 attempts, take stronger action: remove an entire section, convert two-column to single-column, delete the less important element. A clean slide with less content is ALWAYS better than a cramped slide with clipped text.
5. **Content integrity** — When condensing, preserve: specific numbers, model/dataset names, algorithmic steps, equations. Remove: filler phrases ("Furthermore...", "In addition..."), redundant motivations, verbose paraphrases.
6. **Never re-introduce fixed defects** — After every edit, check verify_layout for regressions. If your fix re-introduced a previous issue, rollback.

---

## Edit-Verify Loop

**After EVERY CSS/HTML edit**, run:

```bash
python ~/.cache/redeck/verify_layout.py slide.html
```

Check the result:
- Issue count **decreased** → good, continue
- Issue count **increased** → regression, **revert the edit**
- Issue count **unchanged** → edit didn't help, try different approach

Continue until `✅ No spatial defects detected.`

---

## Embedded Script: verify_layout.py

Run this command to create the verification tool:

```bash
mkdir -p ~/.cache/redeck && cat > ~/.cache/redeck/verify_layout.py << 'SCRIPT_EOF'
#!/usr/bin/env python3
"""ReDeck verify_layout — spatial defect detector for HTML slides (1280x720)."""
import sys, os, json, argparse, tempfile
from dataclasses import dataclass, field
from pathlib import Path

VIEWPORT_W, VIEWPORT_H = 1280, 720
DEVICE_SCALE = 2
SLIDE_W_IN, SLIDE_H_IN = 13.333, 7.5
PX2IN_X, PX2IN_Y = SLIDE_W_IN / VIEWPORT_W, SLIDE_H_IN / VIEWPORT_H

@dataclass
class Block:
    block_id: str; tag: str; css_selector: str = ""
    shape_type: str = "textbox"
    x: float = 0; y: float = 0; w: float = 0; h: float = 0
    bbox_px: tuple = (0,0,0,0)
    text: str = ""; text_chars: int = 0
    font_size_px: float = 16; font_size_pt: float = 12
    is_overflowing: bool = False
    overflow_bottom_px: int = 0; overflow_right_px: int = 0
    client_w_px: int = 0; client_h_px: int = 0
    scroll_w_px: int = 0; scroll_h_px: int = 0
    contrast_ratio: float = 0.0; fg_color: str = ""; bg_color: str = ""
    is_clipped: bool = False; clipped_bottom_px: int = 0
    img_broken: bool = False; img_src: str = ""
    z_index: int = 0; dom_path: str = ""
    _visual_bounds: tuple = None

JS_EXTRACT = r"""() => {
    const bodyOvf = document.body.style.overflow;
    const htmlOvf = document.documentElement.style.overflow;
    if (window.getComputedStyle(document.body).overflow === 'hidden' || window.getComputedStyle(document.documentElement).overflow === 'hidden') {
        document.body.style.overflow = 'visible';
        document.documentElement.style.overflow = 'visible';
    }
    function parseColor(str) { const m = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/); return m ? {r:+m[1],g:+m[2],b:+m[3]} : null; }
    function luminance(c) { const s=[c.r/255,c.g/255,c.b/255]; const l=s.map(v=>v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)); return 0.2126*l[0]+0.7152*l[1]+0.0722*l[2]; }
    function contrastRatio(fg,bg) { const L1=Math.max(luminance(fg),luminance(bg)),L2=Math.min(luminance(fg),luminance(bg)); return (L1+0.05)/(L2+0.05); }
    function getEffectiveBg(el) {
        const tag=el.tagName.toLowerCase();
        if (tag==='th'||tag==='td') { let a=el.parentElement; while(a&&a!==document.body){const t=a.tagName.toLowerCase();if(['tr','thead','tbody','tfoot','table'].includes(t)){const s=window.getComputedStyle(a);const bg=s.backgroundColor;if(bg&&bg!=='rgba(0, 0, 0, 0)'&&bg!=='transparent')return parseColor(bg);}if(t==='table')break;a=a.parentElement;}}
        const rect=el.getBoundingClientRect();const cx=rect.left+rect.width/2,cy=rect.top+rect.height/2;
        try{const stack=document.elementsFromPoint(cx,cy);const si=stack.indexOf(el);for(let i=(si>=0?si+1:0);i<stack.length;i++){const n=stack[i];if(n===document.documentElement)continue;const bg=window.getComputedStyle(n).backgroundColor;if(bg&&bg!=='rgba(0, 0, 0, 0)'&&bg!=='transparent')return parseColor(bg);}}catch(e){}
        let n=el.parentElement;while(n&&n!==document.documentElement){const bg=window.getComputedStyle(n).backgroundColor;if(bg&&bg!=='rgba(0, 0, 0, 0)'&&bg!=='transparent')return parseColor(bg);n=n.parentElement;}
        return {r:255,g:255,b:255};
    }
    const results=[];
    for(const el of document.body.querySelectorAll('*')){
        const tag=el.tagName.toLowerCase();
        if(['html','body','head','style','script','meta','link','br'].includes(tag))continue;
        const rect=el.getBoundingClientRect();if(rect.width<3||rect.height<3)continue;
        const style=window.getComputedStyle(el);if(style.display==='none'||style.visibility==='hidden'||parseFloat(style.opacity)===0)continue;
        let directText='';for(const n of el.childNodes){if(n.nodeType===3)directText+=n.textContent;}directText=directText.trim();
        const isImg=tag==='img';const isCont=['div','section','main','article','header','footer','nav'].includes(tag);const isStruct=['ul','ol','li','table','tbody','thead','tfoot','tr','td','th','dl','dt','dd','figure','figcaption'].includes(tag);
        if((isCont||isStruct)&&!directText&&!isImg)continue;
        let shapeType='textbox';if(isImg)shapeType='picture';else if(tag==='table')shapeType='table';else if(tag==='svg'||el.closest('svg'))shapeType='chart';else if(['h1','h2'].includes(tag))shapeType='title';
        let isOverflowing=el.scrollHeight>el.clientHeight+2||el.scrollWidth>el.clientWidth+2;
        let overflowRight=Math.max(0,el.scrollWidth-el.clientWidth),overflowBottom=Math.max(0,el.scrollHeight-el.clientHeight);
        const ovfStyle=style.overflow+' '+style.overflowX+' '+style.overflowY;const hasHidden=ovfStyle.includes('hidden');
        if(!isOverflowing&&!hasHidden&&el.children.length>0){const pr=el.getBoundingClientRect();let vr=0,vb=0;for(const c of el.children){const cr=c.getBoundingClientRect();if(cr.width>0&&cr.height>0){vr=Math.max(vr,cr.right-pr.right);vb=Math.max(vb,cr.bottom-pr.bottom);}}if(vr>2||vb>2){isOverflowing=true;overflowRight=Math.max(overflowRight,Math.round(vr));overflowBottom=Math.max(overflowBottom,Math.round(vb));}}
        const isClipped=hasHidden&&(el.scrollHeight>el.clientHeight+2||el.scrollWidth>el.clientWidth+2);const clippedBottom=isClipped?Math.max(0,el.scrollHeight-el.clientHeight):0;
        let contrastVal=0,fgColor='',bgColor='';
        if(directText.length>0&&!isImg){const fg=parseColor(style.color);const bg=getEffectiveBg(el);if(fg&&bg){contrastVal=Math.round(contrastRatio(fg,bg)*100)/100;fgColor=style.color;bgColor=`rgb(${bg.r},${bg.g},${bg.b})`;}}
        let imgBroken=false,imgSrc='';if(isImg){imgSrc=el.src||el.getAttribute('src')||'';imgBroken=el.complete&&el.naturalWidth===0&&imgSrc.length>0;}
        let vLeft=rect.x,vTop=rect.y,vRight=rect.right,vBottom=rect.bottom;
        for(const d of el.querySelectorAll('*')){const cr=d.getBoundingClientRect();if(cr.width>0&&cr.height>0){vLeft=Math.min(vLeft,cr.x);vTop=Math.min(vTop,cr.y);vRight=Math.max(vRight,cr.right);vBottom=Math.max(vBottom,cr.bottom);}}
        let ancestorClipBottom=0,ancestorClipRight=0;let anc=el.parentElement;
        while(anc&&anc!==document.body){const as=window.getComputedStyle(anc);const ao=(as.overflow+' '+as.overflowY).toLowerCase();const hop=ao.includes('hidden')||ao.includes('scroll')||ao.includes('auto');const ap=as.position;const heh=as.height&&as.height!=='auto'&&as.height!=='';const ip=ap==='absolute'||ap==='relative'||ap==='fixed';if(hop||(ip&&heh)){const ar=anc.getBoundingClientRect();const cb=Math.max(0,rect.bottom-ar.bottom);const cr2=Math.max(0,rect.right-ar.right);if(cb>2)ancestorClipBottom=Math.max(ancestorClipBottom,Math.round(cb));if(cr2>2)ancestorClipRight=Math.max(ancestorClipRight,Math.round(cr2));}anc=anc.parentElement;}
        let domPath=[];let pe=el;while(pe&&pe!==document.body){const pt=pe.tagName.toLowerCase();const pi=Array.from(pe.parentElement?.children||[]).indexOf(pe);domPath.unshift(pt+'['+pi+']');pe=pe.parentElement;}
        results.push({tag,id:el.id||'',classes:el.className||'',shapeType,text:directText.substring(0,500),bbox:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},visualRect:{x:vLeft,y:vTop,width:vRight-vLeft,height:vBottom-vTop},fontSize:parseFloat(style.fontSize)||16,isOverflowing,overflowRight,overflowBottom,clientWidth:el.clientWidth,clientHeight:el.clientHeight,scrollWidth:el.scrollWidth,scrollHeight:el.scrollHeight,isClipped:isClipped||ancestorClipBottom>2,clippedBottom:Math.max(clippedBottom,ancestorClipBottom),ancestorClipBottom,ancestorClipRight,contrastRatio:contrastVal,fgColor,bgColor,isImg,imgBroken,imgSrc,zIndex:parseInt(style.zIndex)||0,domPath:domPath.join('/')});
    }
    const exceedances=[];
    for(const el of document.body.querySelectorAll('*')){const st=window.getComputedStyle(el);if(st.display==='none'||st.visibility==='hidden')continue;if(parseFloat(st.opacity)===0)continue;const r=el.getBoundingClientRect();if(r.width<3||r.height<3)continue;const exR=Math.round(Math.max(0,r.right-1280)),exB=Math.round(Math.max(0,r.bottom-720));if(exR>5||exB>5){let label=el.id||'';if(!label&&el.className)label=typeof el.className==='string'?el.className.split(' ')[0]:'';exceedances.push({tag:el.tagName.toLowerCase(),label:label.substring(0,80),right:Math.round(r.right),bottom:Math.round(r.bottom),exRight:exR,exBottom:exB,x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)});}}
    document.body.style.overflow=bodyOvf;document.documentElement.style.overflow=htmlOvf;
    return {elements:results,viewportExceedances:exceedances};
}"""

def extract(html_path):
    import re
    from playwright.sync_api import sync_playwright
    html_code = Path(html_path).read_text(encoding="utf-8")
    base_dir = str(Path(html_path).resolve().parent)
    def _resolve(m):
        prefix,src,suffix=m.group(1),m.group(2),m.group(3)
        if src.startswith(('file://','http://','https://','data:','/')): return m.group(0)
        ap=os.path.join(base_dir,src)
        return f'{prefix}file://{ap}{suffix}' if os.path.exists(ap) else m.group(0)
    html_code=re.sub(r'(<img\s[^>]*src=["\'])([^"\']+)(["\'])',_resolve,html_code)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={"width":VIEWPORT_W,"height":VIEWPORT_H},device_scale_factor=DEVICE_SCALE)
        with tempfile.NamedTemporaryFile(mode="w",suffix=".html",delete=False,encoding="utf-8") as f: f.write(html_code); tmp=f.name
        try: page.goto(f"file://{tmp}",wait_until="networkidle"); page.wait_for_timeout(200); data=page.evaluate(JS_EXTRACT)
        finally: os.unlink(tmp)
        page.close(); browser.close()
    elements=data.get("elements",[]) if isinstance(data,dict) else data
    exceedances=data.get("viewportExceedances",[]) if isinstance(data,dict) else []
    return _build(elements,exceedances)

def _build(elements,exceedances):
    blocks=[]
    for el in elements:
        bb=el["bbox"];x=bb["x"]*PX2IN_X;y=bb["y"]*PX2IN_Y;w=bb["width"]*PX2IN_X;h=bb["height"]*PX2IN_Y
        if x+w<0 or y+h<0 or x>SLIDE_W_IN or y>SLIDE_H_IN: continue
        text=el.get("text","");eid=el.get("id","");ecls=el.get("classes","");etag=el.get("tag","div")
        css_sel=f"#{eid}" if eid else (f".{ecls.split()[0]}" if ecls and isinstance(ecls,str) and ecls.strip() else etag)
        vis=el.get("visualRect");vb=None
        if vis: vb=(round(vis["x"]*PX2IN_X,2),round(vis["y"]*PX2IN_Y,2),round(vis["width"]*PX2IN_X,2),round(vis["height"]*PX2IN_Y,2))
        b=Block(block_id=f"blk_{len(blocks)+1:02d}",tag=etag,css_selector=css_sel,shape_type=el.get("shapeType","textbox"),x=round(x,2),y=round(y,2),w=round(w,2),h=round(h,2),bbox_px=(round(bb["x"]),round(bb["y"]),round(bb["width"]),round(bb["height"])),text=text,text_chars=len(text),font_size_px=el.get("fontSize",16),font_size_pt=el.get("fontSize",16)*0.75,is_overflowing=el.get("isOverflowing",False),overflow_bottom_px=round(el.get("overflowBottom",0)),overflow_right_px=round(el.get("overflowRight",0)),client_w_px=el.get("clientWidth",0),client_h_px=el.get("clientHeight",0),scroll_w_px=el.get("scrollWidth",0),scroll_h_px=el.get("scrollHeight",0),contrast_ratio=el.get("contrastRatio",0.0),fg_color=el.get("fgColor",""),bg_color=el.get("bgColor",""),is_clipped=el.get("isClipped",False) or el.get("ancestorClipBottom",0)>2,clipped_bottom_px=max(round(el.get("clippedBottom",0)),round(el.get("ancestorClipBottom",0))),img_broken=el.get("imgBroken",False),img_src=el.get("imgSrc",""),z_index=el.get("zIndex",0),dom_path=el.get("domPath",""))
        b._visual_bounds=vb;blocks.append(b)
    overlap_pairs=_detect_overlaps(blocks)
    overflow_ids=[b.block_id for b in blocks if b.is_overflowing and (b.overflow_bottom_px>8 or b.overflow_right_px>8)]
    SM=30*PX2IN_Y;oob_ids=[]
    for b in blocks:
        vx,vy,vw,vh=b._visual_bounds if b._visual_bounds else (b.x,b.y,b.w,b.h)
        if vx<-0.03 or vy<-0.03 or vx+vw>SLIDE_W_IN+0.03 or vy+vh>SLIDE_H_IN+0.03: oob_ids.append(b.block_id)
        elif b.text_chars>10 and vy+vh>SLIDE_H_IN-SM and b.shape_type not in ("picture","chart"): oob_ids.append(b.block_id)
    oob_set=set(oob_ids)
    for exc in exceedances:
        ex,ey,ew,eh=exc["x"],exc["y"],exc["w"],exc["h"];best=None;ba=float("inf")
        for b in blocks:
            bx,by,bw,bh=b.bbox_px;il,it=max(bx,ex),max(by,ey);ir,ib=min(bx+bw,ex+ew),min(by+bh,ey+eh)
            if ir>il and ib>it:
                inter=(ir-il)*(ib-it)
                if inter/max(ew*eh,1)>0.3 and bw*bh<ba: ba=bw*bh;best=b
        if best and best.block_id not in oob_set: oob_ids.append(best.block_id);oob_set.add(best.block_id)
    low_contrast_ids=[b.block_id for b in blocks if b.contrast_ratio>0 and b.text_chars>3 and b.contrast_ratio<(3.0 if b.font_size_pt>=18 else 4.5)]
    clipped_ids=[b.block_id for b in blocks if b.is_clipped]
    broken_img_ids=[b.block_id for b in blocks if b.img_broken]
    occlusion_pairs=_detect_occlusions(blocks)
    unmatched=[e for e in exceedances if not any(True for b in blocks if b.block_id in oob_set)]
    return {"blocks":blocks,"overlap_pairs":overlap_pairs,"overflow_ids":overflow_ids,"oob_ids":oob_ids,"low_contrast_ids":low_contrast_ids,"clipped_ids":clipped_ids,"broken_img_ids":broken_img_ids,"occlusion_pairs":occlusion_pairs,"viewport_exceedances":[]}

def _vis(b): return b._visual_bounds if b._visual_bounds else (b.x,b.y,b.w,b.h)
def _detect_overlaps(blocks):
    overlaps=[]
    for i in range(len(blocks)):
        for j in range(i+1,len(blocks)):
            a,b=blocks[i],blocks[j];ax,ay,aw,ah=_vis(a);bx,by,bw,bh=_vis(b)
            if aw*ah<0.1 or bw*bh<0.1: continue
            if a.shape_type=="chart" and b.shape_type=="chart" and a.text_chars<3 and b.text_chars<3: continue
            ac=a.x<=b.x and a.y<=b.y and a.x+a.w>=b.x+b.w-0.05 and a.y+a.h>=b.y+b.h-0.05
            bc=b.x<=a.x and b.y<=a.y and b.x+b.w>=a.x+a.w-0.05 and b.y+b.h>=a.y+a.h-0.05
            if ac or bc: continue
            xo=max(0,min(ax+aw,bx+bw)-max(ax,bx));yo=max(0,min(ay+ah,by+bh)-max(ay,by));inter=xo*yo
            if inter>0.05:
                ratio=inter/max(min(aw*ah,bw*bh),0.01)
                if ratio>0.05: overlaps.append((a.block_id,b.block_id,round(ratio,3)))
    return overlaps

def _detect_occlusions(blocks):
    INLINE={"span","strong","em","b","i","a","code","small","sub","sup","mark","abbr","cite","q","label"}
    occ=[]
    for i in range(len(blocks)):
        for j in range(len(blocks)):
            if i==j: continue
            f,b=blocks[i],blocks[j]
            if f.dom_path and b.dom_path:
                if b.dom_path.startswith(f.dom_path+"/") or f.dom_path.startswith(b.dom_path+"/"): continue
                fp="/".join(f.dom_path.split("/")[:-1]);bp="/".join(b.dom_path.split("/")[:-1])
                if fp and fp==bp and f.tag in INLINE and b.tag in INLINE: continue
            if f.z_index<b.z_index: continue
            if f.z_index==b.z_index and i<j: continue
            if b.text_chars<5 and b.shape_type!="picture": continue
            if f.x<=b.x and f.y<=b.y and f.x+f.w>=b.x+b.w-0.05 and f.y+f.h>=b.y+b.h-0.05:
                if f.w*f.h>0.5: occ.append((f.block_id,b.block_id))
    return occ

def _preview(b):
    t=b.text[:50];return (t+"..." if len(b.text)>50 else t) if t else b.tag

def format_report(state):
    blocks=state["blocks"];lines=[f"SLIDE — {len(blocks)} elements | canvas {VIEWPORT_W}x{VIEWPORT_H} px"]
    violations=[];warnings=[]
    for a_id,b_id,ratio in state["overlap_pairs"]:
        a=next((b for b in blocks if b.block_id==a_id),None);bl=next((b for b in blocks if b.block_id==b_id),None)
        if a and bl:
            ax,ay,aw,ah=a.bbox_px;bx,by,bw,bh=bl.bbox_px
            violations.append(f'❌ OVERLAP: "{_preview(a)}" ↔ "{_preview(bl)}"\n   A: ({ax},{ay},{aw}x{ah}) px   B: ({bx},{by},{bw}x{bh}) px\n   intersection: {max(0,min(ax+aw,bx+bw)-max(ax,bx))}x{max(0,min(ay+ah,by+bh)-max(ay,by))} px')
    for bid in state["oob_ids"]:
        blk=next((b for b in blocks if b.block_id==bid),None)
        if blk:
            bx,by,bw,bh=blk.bbox_px;exc=[]
            if bx+bw>VIEWPORT_W:exc.append(f"right edge {bx+bw}px > {VIEWPORT_W}px")
            if by+bh>VIEWPORT_H:exc.append(f"bottom edge {by+bh}px > {VIEWPORT_H}px")
            if bx<0:exc.append(f"left edge {bx}px < 0")
            if by<0:exc.append(f"top edge {by}px < 0")
            if not exc:exc.append(f"bottom edge {by+bh}px in safety zone (>{VIEWPORT_H-30}px)")
            violations.append(f'❌ OUT OF BOUNDS: "{_preview(blk)}"\n   bbox: ({bx},{by},{bw}x{bh}) px\n   {"; ".join(exc)}')
    for bid in state["overflow_ids"]:
        blk=next((b for b in blocks if b.block_id==bid),None)
        if blk:
            bx,by,bw,bh=blk.bbox_px;ov,oh=blk.overflow_bottom_px,blk.overflow_right_px
            if max(ov,oh)<=8: warnings.append(f'⚠️ MINOR OVERFLOW: "{_preview(blk)}" — {max(ov,oh)}px');continue
            violations.append(f'❌ TEXT OVERFLOW: "{_preview(blk)}"\n   scrollH: {blk.scroll_h_px}px | clientH: {blk.client_h_px}px | overflow: {ov}px vertical\n   font-size: {blk.font_size_px}px | bbox: ({bx},{by},{bw}x{bh}) px')
    for bid in state["low_contrast_ids"]:
        blk=next((b for b in blocks if b.block_id==bid),None)
        if blk:
            th=3.0 if blk.font_size_pt>=18 else 4.5
            violations.append(f'❌ LOW CONTRAST: "{_preview(blk)}"\n   ratio: {blk.contrast_ratio:.1f}:1 (min: {th:.1f}:1 for {blk.font_size_px:.0f}px)\n   fg: {blk.fg_color} | bg: {blk.bg_color}')
    for bid in state["clipped_ids"]:
        blk=next((b for b in blocks if b.block_id==bid),None)
        if blk and blk.clipped_bottom_px>5:
            violations.append(f'❌ CLIPPED: "{_preview(blk)}"\n   {blk.clipped_bottom_px}px hidden by overflow:hidden')
    for bid in state["broken_img_ids"]:
        blk=next((b for b in blocks if b.block_id==bid),None)
        if blk: violations.append(f"❌ BROKEN IMAGE: src={blk.img_src or 'unknown'}")
    for fi,bi in state["occlusion_pairs"]:
        f=next((b for b in blocks if b.block_id==fi),None);bk=next((b for b in blocks if b.block_id==bi),None)
        if f and bk: violations.append(f'❌ OCCLUDED: "{_preview(bk)}" hidden behind "{_preview(f)}"')
    # Tight adjacency
    sb=sorted(blocks,key=lambda b:(b.y,b.x))
    for i in range(len(sb)-1):
        a=sb[i]
        if a.text_chars<10:continue
        for j in range(i+1,min(i+3,len(sb))):
            bk=sb[j]
            if bk.text_chars<10:continue
            ac2=a.x<=bk.x and a.y<=bk.y and a.x+a.w>=bk.x+bk.w-0.05 and a.y+a.h>=bk.y+bk.h-0.05
            bc2=bk.x<=a.x and bk.y<=a.y and bk.x+bk.w>=a.x+a.w-0.05 and bk.y+bk.h>=a.y+a.h-0.05
            if ac2 or bc2:continue
            if min(a.x+a.w,bk.x+bk.w)-max(a.x,bk.x)>=0.5:
                gap=bk.y-(a.y+a.h)
                if gap<-0.05 and abs(gap)>=0.15:
                    ax2,ay2,aw2,ah2=a.bbox_px;bx2,by2,bw2,bh2=bk.bbox_px
                    violations.append(f'❌ OVERLAP: "{_preview(a)}" ↔ "{_preview(bk)}"\n   A: ({ax2},{ay2},{aw2}x{ah2}) px   B: ({bx2},{by2},{bw2}x{bh2}) px\n   vertical overlap: {abs(by2-(ay2+ah2))}px')
            break
    if violations: lines.append(f"\n🚨 ISSUES TO FIX ({len(violations)}):");lines.extend(violations)
    if warnings: lines.append(f"\n⚠️ WARNINGS ({len(warnings)}):");lines.extend(warnings)
    if not violations and not warnings: lines.append("\n✅ No spatial defects detected.")
    sig=[b for b in blocks if b.w>0.4 and b.h>0.15 and (b.text_chars>5 or b.shape_type in ("picture","chart","table"))]
    if sig:
        sig.sort(key=lambda b:(round(b.y,1),b.x));lines.append(f"\n📐 LAYOUT ANCHOR ({len(sig)} elements):")
        for blk in sig:
            bx,by,bw,bh=blk.bbox_px;pv=blk.text[:50]+("..." if len(blk.text)>50 else "")
            ft=f" font:{blk.font_size_px:.0f}px" if blk.font_size_px>0 else ""
            lines.append(f'  {blk.tag} {blk.css_selector}: ({bx},{by}) {bw}x{bh}px{ft}  "{pv}"')
    return "\n".join(lines)

def main():
    ap=argparse.ArgumentParser(description="ReDeck verify_layout");ap.add_argument("file",nargs="?");ap.add_argument("--dir")
    args=ap.parse_args();files=[]
    if args.dir: files=sorted(Path(args.dir).glob("*.html"))
    elif args.file: files=[Path(args.file)]
    else: ap.print_help();sys.exit(1)
    if not files: print("No HTML files found.",file=sys.stderr);sys.exit(1)
    total=0
    for f in files:
        state=extract(str(f));n=len(state["overlap_pairs"])+len(state["overflow_ids"])+len(state["oob_ids"])+len(state["clipped_ids"])+len(state["low_contrast_ids"])+len(state["broken_img_ids"])+len(state["occlusion_pairs"])
        total+=n
        if len(files)>1: print(f"\n{'='*60}\nFILE: {f.name}\n{'='*60}")
        print(format_report(state))
    if len(files)>1: print(f"\n{'='*60}\nTOTAL: {len(files)} slides, {total} issues")

if __name__=="__main__": main()
SCRIPT_EOF
```
