"""Crop each numbered figure from the NCERT chapter PDFs (vector drawings + their labels), with its caption."""
# Run once from the repository root (needs PyMuPDF: pip install pymupdf). The figures are committed under
# data/book/, so the app and Docker image don't need PyMuPDF:  python scripts/extract_figures.py data/book/figures
import json, re, sys, warnings
warnings.filterwarnings("ignore")
import pymupdf as fitz

def clusters(rects, gap=8):
    rects = [fitz.Rect(r) for r in rects]
    merged = True
    while merged:
        merged = False
        out = []
        for r in rects:
            for o in out:
                g = fitz.Rect(o.x0 - gap, o.y0 - gap, o.x1 + gap, o.y1 + gap)
                if g.intersects(r):
                    o.include_rect(r); merged = True; break
            else:
                out.append(fitz.Rect(r))
        rects = out
    return rects

def figures(pdf, outdir, chap):
    d = fitz.open(pdf); res = []
    for pno, page in enumerate(d):
        W = page.rect.width
        blocks = page.get_text("blocks")
        caps = [b for b in blocks if re.match(r"\s*Fig(ure)?\s*\d+\.\d+", b[4]) and (b[2]-b[0]) < 400 and len(b[4]) < 260]
        if not caps: continue
        draws = []
        for dr in page.get_drawings():
            r = dr["rect"]
            if r.width > 0.8 * W or r.height > 0.8 * page.rect.height: continue
            if r.width > 300 and dr.get("fill") is not None: continue   # activity / box backgrounds
            if r.width < 0.5 and r.height < 0.5: continue
            draws.append(r)
        for img in page.get_image_info():
            r = fitz.Rect(img["bbox"])
            if r.width < 0.6 * W and r.width > 20: draws.append(r)
        cl = [c for c in clusters(draws) if c.width * c.height > 600]
        text_cols = [fitz.Rect(b[:4]) for b in blocks if len(b[4]) > 120]   # body text paragraphs
        for cap in caps:
            cr = fitz.Rect(cap[:4]); num = re.search(r"\d+\.\d+", cap[4]).group(0)
            def dist(c):
                dx = max(0, c.x0 - cr.x1, cr.x0 - c.x1); dy = max(0, c.y0 - cr.y1, cr.y0 - c.y1)
                return dx + dy
            cands = sorted(cl, key=dist)
            if not cands or dist(cands[0]) > 80: continue
            box = fitz.Rect(cands[0])
            grew = True
            while grew:
                grew = False
                for c in cl:
                    if c == box or box.contains(c): continue
                    g = fitz.Rect(box.x0 - 30, box.y0 - 30, box.x1 + 30, box.y1 + 30)
                    if g.intersects(c) and not any(t.intersects(c) and t.width > 200 for t in text_cols):
                        box.include_rect(c); grew = True
            for b in blocks:   # labels inside / touching the figure
                br = fitz.Rect(b[:4])
                if len(b[4].strip()) < 25 and fitz.Rect(box.x0 - 12, box.y0 - 12, box.x1 + 12, box.y1 + 12).intersects(br):
                    box.include_rect(br)
            box.include_rect(cr)
            box = fitz.Rect(box.x0 - 6, box.y0 - 6, box.x1 + 6, box.y1 + 6) & page.rect
            caption = re.sub(r"(Figure\s+\d+\.\d+\s*)+", "", cap[4].replace("\n", " ")).strip()
            nxt = blocks[blocks.index(cap) + 1][4].strip() if blocks.index(cap) + 1 < len(blocks) else ""
            if caption and caption.endswith(("of", "by", "with")) and nxt and len(nxt) < 80 and not re.match(r"\d+\.\d", nxt):
                caption += " " + nxt  # a caption that runs onto a second line
            name = f"fig_{num.replace('.', '_')}.png"
            if any(r["figure"] == num for r in res): continue
            page.get_pixmap(clip=box, dpi=170).save(f"{outdir}/{name}")
            res.append({"figure": num, "chapter": chap, "page": pno + 1, "caption": caption, "file": name,
                        "size": [round(box.width), round(box.height)]})
    return res

if __name__ == "__main__":
    out = sys.argv[1]; allf = []
    for pdf, ch in [("data/ch9-Light–Reflection-and-Refraction.pdf", "9"), ("data/ch10-The-Human-Eye-and-the-Colourful-World .pdf", "10"), ("data/ch11-Electricity.pdf", "11")]:
        allf += figures(pdf, out, ch)
    for f in allf:
        f.pop("size", None)
    json.dump(allf, open(f"{out}/../figures.json", "w"), indent=1, ensure_ascii=False)
    print(len(allf), [f["figure"] for f in allf])
