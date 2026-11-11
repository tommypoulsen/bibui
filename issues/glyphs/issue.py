"""Pictures and numbers for the bibui glyph issue: today's hinting and mask gamma
against light hinting and Chromium's gamma, as bibui's Glyphs would draw them."""
import sys
import freetype as ft, numpy as np, uharfbuzz as hb
from PIL import Image, ImageDraw
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

VAR, OUT = sys.argv[1], sys.argv[2]
PX = 14
DARK_BG, DARK_FG = (0x1E, 0x1F, 0x22), (0xD4, 0xD6, 0xDA)
LIGHT_BG, LIGHT_FG = (0xFF, 0xFF, 0xFF), (0x1E, 0x1F, 0x22)
TEXT = "A fenced mermaid block is drawn as its diagram. Put the caret in it to edit its source."
NORMAL = ft.FT_LOAD_FORCE_AUTOHINT | ft.FT_LOAD_NO_BITMAP | ft.FT_LOAD_TARGET_NORMAL
LIGHT = ft.FT_LOAD_FORCE_AUTOHINT | ft.FT_LOAD_NO_BITMAP | ft.FT_LOAD_TARGET_LIGHT
NOHINT = ft.FT_LOAD_NO_HINTING | ft.FT_LOAD_NO_BITMAP

SRGB = (lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4,
        lambda v: v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)
G12 = (lambda v: v ** 1.2, lambda v: v ** (1 / 1.2))


def lut(fg, curve, contrast):
    """Skia's SkMaskGamma table for a foreground, as Bibui.Glyphs builds it."""
    to_l, from_l = curve
    lum = (fg[0] * 54 + fg[1] * 183 + fg[2] * 19) >> 8
    i = lum >> 5
    src = (i << 5 | i << 2 | i >> 1) / 255
    dst = 1 - src
    lin_src, lin_dst = to_l(src), to_l(dst)
    adj = contrast * lin_dst
    t = np.zeros(256, dtype=np.uint8)
    for k in range(256):
        a = k / 255
        a = a + (1 - a) * adj * a
        if abs(src - dst) < 1 / 256:
            t[k] = round(255 * a); continue
        r = (from_l(lin_src * a + (1 - a) * lin_dst) - dst) / (src - dst)
        t[k] = min(255, max(0, round(255 * r)))
    return t


VARIANTS = [
    ("A  today: full hinting, sRGB gamma, contrast 0.5", NORMAL, (SRGB, 128 / 255)),
    ("B  light hinting (vertical only), gamma as today", LIGHT, (SRGB, 128 / 255)),
    ("C  full hinting, gamma 1.2, contrast 0.2 (Chromium on Linux)", NORMAL, (G12, 0.2)),
    ("D  light hinting, gamma 1.2, contrast 0.2", LIGHT, (G12, 0.2)),
]

inst = instancer.instantiateVariableFont(TTFont(VAR), {"wght": 400, "opsz": 14})
path = f"{OUT}/Inter-400.ttf"
inst.save(path)
face = ft.Face(path); face.set_char_size(PX * 64, 0, 72, 72)

blob = hb.Blob.from_file_path(path); hbf = hb.Font(hb.Face(blob)); scale = PX / hbf.face.upem
buf = hb.Buffer(); buf.add_str(TEXT); buf.guess_segment_properties()
hb.shape(hbf, buf, {"kern": True, "liga": True})
glyphs, x = [], 0.0
for info, pos, ch in zip(buf.glyph_infos, buf.glyph_positions, TEXT):
    glyphs.append((info.codepoint, x + pos.x_offset * scale, ch)); x += pos.x_advance * scale


def masks(flags, table):
    """Each glyph's coverage after the gamma table, and where its left column lands."""
    out = []
    for gid, gx, ch in glyphs:
        q = np.floor((gx + 0.125) * 4) / 4; ix = int(np.floor(q))
        face.set_transform(ft.Matrix(0x10000, 0, 0, 0x10000), ft.Vector(int((q - ix) * 64), 0))
        face.load_glyph(gid, flags); slot = face.glyph; slot.render(ft.FT_RENDER_MODE_NORMAL); bm = slot.bitmap
        cov = (np.array(bm.buffer, dtype=np.uint8).reshape(bm.rows, bm.pitch)[:, : bm.width]
               if bm.width and bm.rows else np.zeros((0, 0), np.uint8))
        out.append((ch, ix + slot.bitmap_left, slot.bitmap_top, table[cov] if cov.size else cov))
    return out


def draw(canvas, ms, x0, baseline, fg):
    for _, left, top, a in ms:
        if not a.size: continue
        r = canvas[baseline - top: baseline - top + a.shape[0], x0 + left: x0 + left + a.shape[1]]
        al = a[: r.shape[0], : r.shape[1]].astype(np.float32)[..., None] / 255
        r[:] = r + (np.array(fg, np.float32) - r) * al


def gaps(ms):
    """For each pair of letters in a word: the clear columns between their ink (> 25 %), row by row, the least."""
    res = []
    for (c1, l1, t1, a1), (c2, l2, t2, a2) in zip(ms, ms[1:]):
        if not (c1.isalpha() and c2.isalpha()) or not a1.size or not a2.size: continue
        best = None
        top = max(t1, t2)
        for row in range(top, min(t1 - a1.shape[0], t2 - a2.shape[0]), -1):
            r1, r2 = t1 - row, t2 - row
            if not (0 <= r1 < a1.shape[0] and 0 <= r2 < a2.shape[0]): continue
            ink1 = np.nonzero(a1[r1] > 64)[0]; ink2 = np.nonzero(a2[r2] > 64)[0]
            if not ink1.size or not ink2.size: continue
            g = (l2 + ink2[0]) - (l1 + ink1[-1]) - 1
            best = g if best is None else min(best, g)
        if best is not None: res.append((c1 + c2, best))
    return res


def stem(flags, table):
    vals = []
    for sub in (0, 16, 32, 48):
        face.set_transform(ft.Matrix(0x10000, 0, 0, 0x10000), ft.Vector(sub, 0))
        face.load_char("l", flags); face.glyph.render(ft.FT_RENDER_MODE_NORMAL); bm = face.glyph.bitmap
        row = np.array(bm.buffer, dtype=np.uint8).reshape(bm.rows, bm.pitch)[bm.rows // 2, : bm.width]
        vals.append(table[row].astype(int).sum() / 255)
    return float(np.mean(vals))


ideal = {p: g for p, g in gaps(masks(NOHINT, np.arange(256, dtype=np.uint8)))}
lh, label_h, W = 22, 16, 640
for theme, bg, fg in (("dark", DARK_BG, DARK_FG), ("light", LIGHT_BG, LIGHT_FG)):
    block = label_h + lh + 8
    canvas = np.zeros((block * len(VARIANTS) + 6, W, 3), np.float32); canvas[:] = bg
    print(f"\n{theme}: variant | stem of 'l' as seen (px) | letter pairs touching (no clear column) | gap spread (std, px)")
    for v, (label, flags, (curve, contrast)) in enumerate(VARIANTS):
        table = lut(fg, curve, contrast)
        ms = masks(flags, table)
        draw(canvas, ms, 12, v * block + label_h + 16, fg)
        gs = gaps(ms)
        touching = [p for p, g in gs if g <= 0]
        print(f"{label[:1]} | {stem(flags, table):.2f} | {len(touching)} of {len(gs)}: {' '.join(touching)} | {np.std([g for _, g in gs]):.2f}")
    img = Image.fromarray(np.clip(np.rint(canvas), 0, 255).astype(np.uint8)); d = ImageDraw.Draw(img)
    for v, (label, *_r) in enumerate(VARIANTS):
        d.text((12, v * block + 3), label, fill=(0x79, 0xA2, 0xEF) if theme == "dark" else (0x1A, 0x5F, 0xD0))
    img.save(f"{OUT}/glyphs-{theme}-1x.png")
    img.crop((0, 0, 300, img.height)).resize((1200, img.height * 4), Image.NEAREST).save(f"{OUT}/glyphs-{theme}-zoom4x.png")
