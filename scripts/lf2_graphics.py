"""새 롱폼(같은 종류 비교형) 화면 그래픽 + 구간 렌더 + 썸네일(B안 'A vs B').

2026-10-06 로컬 시안(_실험/쇼핑_CC/lf2_compose.py, lf2_thumb.py)을 사용자 승인 후 운영으로 옮김.
레이아웃 원칙: 두 줄 자막(아래 약 840px부터)과 겹치지 않도록 모든 카드는 y≤830 안에 둔다.
"""
import subprocess
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FD = HERE.parent / "assets" / "fonts"
W, H, FPS = 1920, 1080, 30
GOLD = (236, 192, 96)
CREAM = (255, 248, 236)
INK = (20, 16, 14)
MUTE = (200, 188, 170)
YEL = (255, 209, 46)
RED = (232, 52, 52)


def F(w, s):
    return ImageFont.truetype(str(FD / f"Pretendard-{w}.otf"), s)


def run(cmd):
    subprocess.run(cmd, check=True)


def new(size=(W, H)):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def save(im, path: Path):
    im.save(path)
    return path


def fit_text(text, weight, size, max_w, min_size=24):
    while size > min_size and F(weight, size).getlength(text) > max_w:
        size -= 2
    return F(weight, size)


# ------------------------------------------------------------ 기본 층
def caption(text):
    im = new()
    f = F("Bold", 44)
    lines = [text]
    if f.getlength(text) > 1500:
        ws = text.split(" ")
        best = min(range(1, len(ws)), key=lambda k: abs(len(" ".join(ws[:k])) - len(" ".join(ws[k:]))))
        lines = [" ".join(ws[:best]), " ".join(ws[best:])]
    h = 70 * len(lines) + 30
    d = ImageDraw.Draw(im)
    tw = max(f.getlength(ln) for ln in lines)
    d.rounded_rectangle([W / 2 - tw / 2 - 40, H - 70 - h, W / 2 + tw / 2 + 40, H - 70], radius=24, fill=(*INK, 200))
    for i, ln in enumerate(lines):
        d.text((W / 2, H - 70 - h + 50 + i * 70), ln, font=f, fill=(*CREAM, 255), anchor="mm")
    return im


def left_shade(strength=225):
    g = Image.new("L", (W, 1))
    for x in range(W):
        g.putpixel((x, 0), int(strength * max(0.0, 1 - x / (W * 0.62)) ** 1.3))
    im = Image.new("RGBA", (W, H), (*INK, 0))
    im.putalpha(g.resize((W, H)))
    return im


def header(text_right):
    im = new()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([60, 46, 300, 104], radius=29, fill=(*GOLD, 255))
    d.text((180, 75), "쇼핑의 천국", font=F("ExtraBold", 32), fill=(*INK, 255), anchor="mm")
    d.text((320, 75), text_right, font=F("SemiBold", 28), fill=(*CREAM, 230), anchor="lm")
    d.text((W - 60, 75), "AI 활용 콘텐츠 · 쿠팡 파트너스 활동", font=F("Medium", 24), fill=(*MUTE, 220), anchor="rm")
    return im


def title_block(kicker, title, sub=None, y=380, max_w=1050):
    im = new()
    d = ImageDraw.Draw(im)
    d.text((120, y), kicker, font=F("Bold", 34), fill=(*GOLD, 255), anchor="lm")
    d.text((116, y + 90), title, font=fit_text(title, "Black", 92, max_w), fill=(*CREAM, 255), anchor="lm")
    if sub:
        d.text((120, y + 180), sub, font=fit_text(sub, "SemiBold", 40, max_w), fill=(*MUTE, 255), anchor="lm")
    return im


def bullet(i, text, y, color=GOLD, max_w=1000):
    im = new()
    d = ImageDraw.Draw(im)
    d.ellipse([120, y - 30, 180, y + 30], fill=(*color, 255))
    d.text((150, y - 2), str(i), font=F("Black", 36), fill=(*INK, 255), anchor="mm")
    d.text((210, y), text, font=fit_text(text, "Bold", 48, max_w), fill=(*CREAM, 255), anchor="lm")
    return im


def for_whom(text, y=715):
    im = new()
    d = ImageDraw.Draw(im)
    f = fit_text(text, "Bold", 38, 760)
    w = f.getlength(text) + 230
    d.rounded_rectangle([120, y - 42, 120 + w, y + 42], radius=42, fill=(*GOLD, 255))
    d.text((150, y), "이런 분께", font=F("Black", 30), fill=(*INK, 255), anchor="lm")
    d.text((320, y), text, font=f, fill=(*INK, 255), anchor="lm")
    return im


def check_chip(text, y=800):
    im = new()
    d = ImageDraw.Draw(im)
    f = fit_text(text, "SemiBold", 30, 840)
    w = f.getlength(text) + 150
    d.rounded_rectangle([120, y - 32, 120 + w, y + 32], radius=32, fill=(*INK, 220), outline=(240, 120, 90, 255), width=3)
    d.text((148, y), "체크", font=F("Black", 28), fill=(240, 140, 110, 255), anchor="lm")
    d.text((240, y), text, font=f, fill=(*CREAM, 255), anchor="lm")
    return im


def rank_badge(n, total):
    im = new()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([1260, 120, 1500, 172], radius=26, fill=(*INK, 230), outline=(*GOLD, 255), width=3)
    d.text((1380, 146), f"추천 {n} / {total}", font=F("Black", 30), fill=(*GOLD, 255), anchor="mm")
    return im


def product_card(photo: Path, name: str, price: int):
    S = 520
    im = new()
    x0, y0 = 1260, 190
    sh = new()
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + 20, x0 + S, y0 + S + 170 + 20], radius=36, fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(24)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0, x0 + S, y0 + S + 170], radius=36, fill=(255, 255, 255, 255))
    ph = Image.open(photo).convert("RGB")
    ph.thumbnail((S - 60, S - 60), Image.LANCZOS)
    im.paste(ph, (int(x0 + (S - ph.width) / 2), int(y0 + 30 + (S - 60 - ph.height) / 2)))
    d.rounded_rectangle([x0, y0 + S, x0 + S, y0 + S + 170], radius=36, fill=(*INK, 255))
    d.rectangle([x0, y0 + S, x0 + S, y0 + S + 40], fill=(*INK, 255))
    d.text((x0 + S / 2, y0 + S + 52), name, font=fit_text(name, "Bold", 30, S - 40), fill=(*CREAM, 255), anchor="mm")
    d.text((x0 + S / 2, y0 + S + 116), f"{price:,}원대", font=F("Black", 50), fill=(*GOLD, 255), anchor="mm")
    return im


def toc(items):
    im = new()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([1240, 300, 1800, 300 + 90 * len(items) + 80], radius=30, fill=(*INK, 215), outline=(*GOLD, 200), width=2)
    d.text((1290, 350), "오늘의 순서", font=F("Black", 36), fill=(*GOLD, 255), anchor="lm")
    for k, t in enumerate(items):
        d.text((1290, 430 + k * 90), f"{k + 1}", font=F("Black", 40), fill=(*GOLD, 255), anchor="lm")
        d.text((1340, 430 + k * 90), t, font=fit_text(t, "Bold", 36, 420), fill=(*CREAM, 255), anchor="lm")
    return im


def compare_table(title, rows):
    """rows: [(제품 짧은 이름, 가격, 특징, 이런 분께)] 최대 6줄."""
    im = new()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([90, 140, W - 90, 820], radius=36, fill=(*INK, 232), outline=(*GOLD, 200), width=2)
    d.text((W / 2, 200), title, font=fit_text(title, "Black", 52, 1500), fill=(*CREAM, 255), anchor="mm")
    cols = [("제품", 150), ("가격대", 690), ("특징", 950), ("이런 분께", 1400)]
    for c, x in cols:
        d.text((x, 285), c, font=F("Black", 34), fill=(*GOLD, 255), anchor="lm")
    for i, (short, price, tag, who) in enumerate(rows):
        y = 350 + i * 76
        d.line([(130, y - 38), (W - 130, y - 38)], fill=(255, 255, 255, 45), width=1)
        d.text((150, y), short, font=fit_text(short, "Bold", 36, 520), fill=(*CREAM, 255), anchor="lm")
        d.text((690, y), f"{price:,}원", font=F("Bold", 36), fill=(*GOLD, 255), anchor="lm")
        d.text((950, y), tag, font=fit_text(tag, "Bold", 36, 420), fill=(*CREAM, 255), anchor="lm")
        d.text((1400, y), who, font=fit_text(who, "SemiBold", 32, 380), fill=(*MUTE, 255), anchor="lm")
    return im


def situ_card(k, head, body):
    im = new()
    d = ImageDraw.Draw(im)
    x, y = 150 + (k % 2) * 830, 400 + (k // 2) * 220
    d.rounded_rectangle([x, y, x + 790, y + 200], radius=30, fill=(*INK, 220), outline=(*GOLD, 255), width=3)
    d.text((x + 40, y + 50), head, font=fit_text(head, "Black", 44, 700), fill=(*GOLD, 255), anchor="lm")
    for j, ln in enumerate(body[:2]):
        d.text((x + 40, y + 112 + j * 48), ln, font=fit_text(ln, "Bold", 36, 710), fill=(*CREAM, 255), anchor="lm")
    return im


# ------------------------------------------------------------ 구간 렌더(배경 먼저 → 그래픽 얹기, 긴 구간 메모리 폭주 방지)
def render_segment(bg_sources, wav, dur, times, layers, out: Path, work: Path, tag: str, shade=True, blur=False):
    """bg_sources: 배경 영상 경로(여러 개면 나눠 이어 붙임) 또는 ("image", 경로) 튜플(천천히 확대되는 사진 배경).
    layers: [(png, 시작초)], times: [(시작, 끝, 자막문장)]."""
    n = len(bg_sources)
    per = dur / n
    parts = []
    for i, src in enumerate(bg_sources):
        pp = work / f"{tag}_bg{i}.mp4"
        if isinstance(src, tuple):
            frames = int((per + 0.05) * FPS)
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(src[1]), "-t", f"{per + 0.05:.2f}", "-vf",
                 f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},gblur=sigma=18,"
                 f"zoompan=z='1+0.08*on/{frames}':d=1:s={W}x{H}:fps={FPS},format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(pp)])
        else:
            run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{per + 0.05:.2f}", "-an", "-vf",
                 f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(pp)])
        parts.append(pp)
    lst = work / f"{tag}_bg.txt"
    lst.write_text("".join(f"file '{q.name}'\n" for q in parts))
    bg = work / f"{tag}_bg.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(bg)])
    look = "eq=saturation=0.9:brightness=-0.05" + (",gblur=sigma=12" if blur else "")
    ins, fc = ["-i", str(bg)], f"[0:v]{look},format=rgba[bg];"
    pngs = []
    if shade:
        pngs.append((save(left_shade(), work / f"{tag}_shade.png"), 0.0, dur))
    pngs += [(p, st, dur) for p, st in layers]
    for k, (st, en, ln) in enumerate(times):
        pngs.append((save(caption(ln), work / f"{tag}_cap{k}.png"), st, en + 0.3))
    cur = "bg"
    for j, (p, st, en) in enumerate(pngs):
        ins += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.2f}", "-i", str(p)]
        fc += f"[{cur}][{1 + j}:v]overlay=0:0:enable='between(t,{st:.2f},{en:.2f})'[l{j}];"
        cur = f"l{j}"
    fc += f"[{cur}]format=yuv420p[o]"
    run(["ffmpeg", "-y", "-v", "error", *ins, "-i", str(wav), "-filter_complex", fc, "-map", "[o]", "-map", f"{1 + len(pngs)}:a",
         "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         str(out)])
    return out


# ------------------------------------------------------------ 상품 누끼(배경 제거)
def cutout(photo: Path, out: Path) -> Path:
    """rembg(isnet)가 있으면 그걸로, 없으면 가장자리에서 이어진 밝은 단색 배경을 지운다.
    rembg는 지운 픽셀 색을 검게 만들므로 원본 색에 마스크만 씌우고, 반사 때문에 생긴 안쪽 구멍은 메운다."""
    src = Image.open(photo).convert("RGB")
    mask = None
    try:
        from rembg import new_session, remove
        mask = remove(src, session=new_session("isnet-general-use"), post_process_mask=True, only_mask=True).convert("L")
    except Exception as e:  # noqa: BLE001
        print(f"[lf2] rembg 사용 불가 → 단색 배경 제거로 대체: {e}")
    if mask is None:
        mask = _flood_mask(src)
    _fill_holes(mask)
    o = src.convert("RGBA")
    o.putalpha(mask)
    o = o.crop(o.getbbox() or (0, 0, o.width, o.height))
    o.save(out)
    return out


def _flood_mask(im, tol=26):
    w, h = im.size
    px = im.load()
    seed = px[0, 0]
    bg = bytearray(w * h)
    dq = deque([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)])
    while dq:
        x, y = dq.popleft()
        i = y * w + x
        if bg[i]:
            continue
        r, g, b = px[x, y]
        if abs(r - seed[0]) + abs(g - seed[1]) + abs(b - seed[2]) > tol * 3:
            continue
        bg[i] = 1
        if x > 0: dq.append((x - 1, y))  # noqa: E701
        if x < w - 1: dq.append((x + 1, y))  # noqa: E701
        if y > 0: dq.append((x, y - 1))  # noqa: E701
        if y < h - 1: dq.append((x, y + 1))  # noqa: E701
    m = Image.frombytes("L", (w, h), bytes(0 if v else 255 for v in bg))
    return m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))


def _fill_holes(mask):
    w, h = mask.size
    px = mask.load()
    seen = bytearray(w * h)
    dq = deque([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)])
    while dq:
        x, y = dq.popleft()
        k = y * w + x
        if seen[k] or px[x, y] > 128:
            continue
        seen[k] = 1
        if x > 0: dq.append((x - 1, y))  # noqa: E701
        if x < w - 1: dq.append((x + 1, y))  # noqa: E701
        if y > 0: dq.append((x, y - 1))  # noqa: E701
        if y < h - 1: dq.append((x, y + 1))  # noqa: E701
    for y in range(h):
        for x in range(w):
            if px[x, y] <= 128 and not seen[y * w + x]:
                px[x, y] = 255


# ------------------------------------------------------------ 썸네일 B안: 'A vs B' (2026-10-06 사용자 선택)
TW, TH = 1280, 720


def _cover(im, w, h):
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s + 0.5), int(im.height * s + 0.5)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def _fit(im, w, h):
    s = min(w / im.width, h / im.height)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)


def _shadow_paste(base, im, xy, blur=18, off=(10, 16), alpha=150, rot=0):
    if rot:
        im = im.rotate(rot, expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", (im.width + 80, im.height + 80), (0, 0, 0, 0))
    blk = Image.new("RGBA", im.size, (0, 0, 0, 255))
    blk.putalpha(im.split()[3].point(lambda v: v * alpha // 255))
    sh.alpha_composite(blk, (40, 40))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)), (xy[0] - 40 + off[0], xy[1] - 40 + off[1]))
    base.alpha_composite(im, xy)


def _chip(base, x, y, s, font, h=54, pad=26):
    w = int(font.getlength(s)) + pad * 2
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle([x + 4, y + 6, x + w + 4, y + h + 6], radius=h // 2, fill=(0, 0, 0, 110))
    base.alpha_composite(lay.filter(ImageFilter.GaussianBlur(5)))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(255, 255, 255, 255))
    d.text((x + w / 2, y + h / 2 + 1), s, font=font, fill=(*INK, 255), anchor="mm")
    return w


def thumbnail_vs(left_bg: Image.Image, right_bg: Image.Image, left_cut: Path, right_cut: Path,
                 left_label: str, right_label: str, question: str, chips: list, out: Path) -> Path:
    base = Image.new("RGBA", (TW, TH))
    base.paste(_cover(left_bg.convert("RGB"), TW // 2, TH), (0, 0))
    base.paste(_cover(right_bg.convert("RGB"), TW // 2, TH), (TW // 2, 0))
    base.alpha_composite(Image.new("RGBA", (TW, TH), (*INK, 95)))
    g = Image.new("L", (1, TH))
    for y in range(TH):
        g.putpixel((0, y), int(230 * max(0.0, (y - (TH - 220)) / 220)))
    band = Image.new("RGBA", (TW, TH), (*INK, 0))
    band.putalpha(g.resize((TW, TH)))
    base.alpha_composite(band)
    d = ImageDraw.Draw(base)
    d.polygon([(TW // 2 - 30, 0), (TW // 2 + 12, 0), (TW // 2 + 30, TH), (TW // 2 - 12, TH)], fill=(*YEL, 255))
    lc = _fit(Image.open(left_cut).convert("RGBA"), 500, 380)
    rc = _fit(Image.open(right_cut).convert("RGBA"), 500, 380)
    _shadow_paste(base, lc, (TW // 4 - lc.width // 2, 140 + (380 - lc.height) // 2), rot=6)
    _shadow_paste(base, rc, (TW * 3 // 4 - rc.width // 2, 140 + (380 - rc.height) // 2))
    d = ImageDraw.Draw(base)
    for lab, cx in ((left_label, TW // 4), (right_label, TW * 3 // 4)):
        d.text((cx, 70), lab, font=fit_text(lab, "Black", 84, 560), fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(*INK, 255), anchor="mm")
    vs = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vs)
    vd.ellipse([8, 8, 192, 192], fill=(*RED, 255), outline=(255, 255, 255, 255), width=8)
    vd.text((100, 98), "VS", font=F("Black", 84), fill=(255, 255, 255, 255), anchor="mm")
    _shadow_paste(base, vs, (TW // 2 - 100, 250), blur=12, alpha=160)
    d = ImageDraw.Draw(base)
    d.text((TW // 2, 560), question, font=fit_text(question, "Black", 80, 1180), fill=(*YEL, 255), stroke_width=7, stroke_fill=(*INK, 255), anchor="mm")
    font = F("ExtraBold", 28)
    widths = [int(font.getlength(c)) + 52 for c in chips]
    x = (TW - sum(widths) - 18 * (len(chips) - 1)) // 2
    for c, w in zip(chips, widths):
        _chip(base, x, 630, c, font)
        x += w + 18
    base.convert("RGB").save(out, quality=92)
    return out
