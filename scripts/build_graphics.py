# -*- coding: utf-8 -*-
"""쇼핑의천국 골드 럭셔리 디자인 시스템 v2 (2026-08-27, 로컬 세션에서 확정된 v15 이식).

로컬 세션에서 크래시줌+플래시 컷, 골드 포일 타이틀(Noto Serif KR), 유리질감
스펙카드+아이콘, 스텝배지, 제품 그림자+리플렉션, 비네트, AI고지 태그, CTA
펄스버튼, 세이프존 자막 배치까지 확정한 디자인(project memory
`project_shoppingparadise_youtube.md` 2026-08-27 항목 참고)을 그대로 재현.
기존 v1(2026-08-26, hook_title 리본+단순 카드)에서 교체됨.

사용법: 다른 스크립트에서 build_all(**kwargs) 호출.
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
FONT_SERIF = ASSETS / "fonts" / "NotoSerifKR-VF.ttf"
LOGO_PATH = ASSETS / "logo" / "channel_logo.png"

W, H = 1080, 1920
CREAM = (246, 239, 226, 255)
GOLD = (168, 124, 58, 255)
GOLD_DEEP = (140, 100, 45, 255)
GOLD_LIGHT = (205, 168, 108, 255)
CHARCOAL = (40, 34, 27, 255)

# 레이아웃 좌표 (세이프존 확보된 배치 그대로 이식)
LOGO_XY = (40, 50)
AI_TAG_XY = (40, 210)
TITLE_XY = (90, 264)
CARD_X = 104
CAPTION_X = 80
CTA_CAPTION_Y = 1400
CTA_BUTTON_Y = 1500

ICON_ORDER = ["cpu", "storage", "display"]


def sfont(size, weight="Regular"):
    f = ImageFont.truetype(str(FONT_SERIF), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def draw_tracked(draw_target, xy, text, fnt, fill, tracking, stroke_width=0, stroke_fill=None):
    x, y = xy
    for ch in text:
        draw_target.text((x, y), ch, font=fnt, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        x += draw_target.textlength(ch, font=fnt) + tracking
    return x


def tracked_width(text, fnt, tracking):
    tmp = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(tmp)
    return sum(d0.textlength(c, font=fnt) + tracking for c in text) - tracking


# ---------- 아이콘 ----------
def icon_cpu(size=64, color=GOLD_DEEP):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = size * 0.22
    d.rounded_rectangle([m, m, size - m, size - m], radius=4, outline=color, width=4)
    inner = size * 0.34
    d.rectangle([inner, inner, size - inner, size - inner], outline=color, width=3)
    pin_len = size * 0.12
    for i in range(3):
        t = m + (size - 2 * m) * (i + 0.5) / 3
        d.line([(t, m - pin_len), (t, m)], fill=color, width=3)
        d.line([(t, size - m), (t, size - m + pin_len)], fill=color, width=3)
        d.line([(m - pin_len, t), (m, t)], fill=color, width=3)
        d.line([(size - m, t), (size - m + pin_len, t)], fill=color, width=3)
    return im


def icon_storage(size=64, color=GOLD_DEEP):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = size * 0.74
    h = size * 0.22
    x0 = (size - w) / 2
    gap = size * 0.1
    y1 = size * 0.22
    y2 = y1 + h + gap
    for y in (y1, y2):
        d.rounded_rectangle([x0, y, x0 + w, y + h], radius=6, outline=color, width=4)
        d.ellipse([x0 + w * 0.62, y + h * 0.32, x0 + w * 0.62 + h * 0.36, y + h * 0.68], fill=color)
    return im


def icon_display(size=64, color=GOLD_DEEP):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = size * 0.78
    h = size * 0.52
    x0 = (size - w) / 2
    y0 = size * 0.14
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=5, outline=color, width=4)
    cx = size / 2
    d.line([(cx, y0 + h), (cx, y0 + h + size * 0.14)], fill=color, width=4)
    sw = size * 0.26
    d.line([(cx - sw / 2, y0 + h + size * 0.14), (cx + sw / 2, y0 + h + size * 0.14)], fill=color, width=4)
    return im


ICONS = {"cpu": icon_cpu, "storage": icon_storage, "display": icon_display}


def build_bg(out_dir: Path, seed=11):
    import random
    random.seed(seed)
    bg = Image.new("RGBA", (W, H), CREAM)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W / 2 - 460, 500, W / 2 + 460, 1400], fill=(255, 244, 214, 90))
    bg = Image.alpha_composite(bg, glow.filter(ImageFilter.GaussianBlur(160)))
    particles = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(particles)
    for _ in range(45):
        x, y = random.randint(0, W), random.randint(0, H)
        r = random.uniform(1.2, 2.6)
        pd.ellipse([x - r, y - r, x + r, y + r], fill=(*GOLD_LIGHT[:3], random.randint(30, 80)))
    bg = Image.alpha_composite(bg, particles.filter(ImageFilter.GaussianBlur(0.5)))
    d = ImageDraw.Draw(bg)
    d.line([(90, 120), (990, 120)], fill=(*GOLD[:3], 90), width=2)
    d.line([(90, 1878), (990, 1878)], fill=(*GOLD[:3], 90), width=2)
    bg.save(out_dir / "bg_bright.png")


def build_vignette(out_dir: Path):
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse([-160, -280, W + 160, H + 280], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(180))
    inv = Image.eval(mask, lambda v: 255 - v).point(lambda v: int(v * 0.75))
    vignette = Image.new("RGBA", (W, H), (8, 6, 4, 255))
    vignette.putalpha(inv)
    vignette.save(out_dir / "vignette.png")


def build_flash(out_dir: Path):
    Image.new("RGBA", (W, H), (255, 250, 240, 215)).save(out_dir / "flash_white.png")


def build_ai_tag(out_dir: Path, text="AI 활용 제작 콘텐츠"):
    f = sfont(24, "Medium")
    tw = tracked_width(text, f, 0)
    w, h = int(tw + 40), 40
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=10, fill=(20, 16, 12, 150))
    d.text((20, 9), text, font=f, fill=(230, 220, 200, 235))
    im.save(out_dir / "ai_tag.png")


def build_logo_xl(out_dir: Path):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    w, h = logo.size
    new_w = 520
    new_h = int(h * new_w / w)
    logo.resize((new_w, new_h), Image.LANCZOS).save(out_dir / "logo_xl.png")


def build_title_block(out_dir: Path, name_text: str, price_text: str):
    title_w, title_h = 900, 190
    title = Image.new("RGBA", (title_w, title_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(title)
    d.rounded_rectangle([60, 10, title_w - 60, title_h - 40], radius=14, outline=GOLD, width=2)
    d.rounded_rectangle([66, 16, title_w - 66, title_h - 46], radius=11, outline=GOLD, width=1)

    f1 = sfont(52, "Bold")
    tracking = 10
    tracked_w = tracked_width(name_text, f1, tracking)
    name_x = (title_w - tracked_w) / 2
    name_y = 30

    shadow = Image.new("RGBA", (title_w, title_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    draw_tracked(sd, (name_x, name_y + 4), name_text, f1, (30, 20, 8, 130), tracking)
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    title.alpha_composite(shadow)

    base = Image.new("RGBA", (title_w, title_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    draw_tracked(bd, (name_x, name_y), name_text, f1, (96, 66, 24, 255), tracking, stroke_width=3, stroke_fill=(96, 66, 24, 255))
    title.alpha_composite(base)

    mask = Image.new("L", (title_w, title_h), 0)
    md = ImageDraw.Draw(mask)
    draw_tracked(md, (name_x, name_y), name_text, f1, 255, tracking)

    stops = [
        (0.0, (250, 232, 176)),
        (0.35, (214, 168, 92)),
        (0.55, (178, 130, 46)),
        (0.75, (222, 182, 108)),
        (1.0, (168, 124, 58)),
    ]
    arr = np.zeros((title_h, title_w, 3), dtype=np.uint8)
    for y in range(title_h):
        t = y / title_h
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                fr = (t - t0) / (t1 - t0) if t1 > t0 else 0
                arr[y, :, :] = tuple(int(c0[k] + (c1[k] - c0[k]) * fr) for k in range(3))
                break
    grad = Image.fromarray(arr, "RGB").convert("RGBA")
    gradient_text = Image.composite(grad, Image.new("RGBA", (title_w, title_h), (0, 0, 0, 0)), mask)
    title.alpha_composite(gradient_text)

    highlight = Image.new("RGBA", (title_w, title_h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    draw_tracked(hd, (name_x, name_y - 1), name_text, f1, (255, 250, 225, 90), tracking)
    hmask = Image.new("L", (title_w, title_h), 0)
    ImageDraw.Draw(hmask).rectangle([0, 0, title_w, name_y + 20], fill=255)
    highlight = Image.composite(highlight, Image.new("RGBA", (title_w, title_h), (0, 0, 0, 0)), hmask)
    title.alpha_composite(highlight)

    d2 = ImageDraw.Draw(title)
    line_y = name_y + 30
    d2.line([(name_x - 46, line_y), (name_x - 14, line_y)], fill=(*GOLD[:3], 200), width=2)
    d2.line([(name_x + tracked_w + 14, line_y), (name_x + tracked_w + 46, line_y)], fill=(*GOLD[:3], 200), width=2)
    d2.regular_polygon((name_x - 54, line_y, 5), n_sides=4, rotation=45, fill=(*GOLD[:3], 220))
    d2.regular_polygon((name_x + tracked_w + 54, line_y, 5), n_sides=4, rotation=45, fill=(*GOLD[:3], 220))

    f2 = sfont(32, "Medium")
    w2 = tracked_width(price_text, f2, 0)
    d2.text(((title_w - w2) / 2, 106), price_text, font=f2, fill=CHARCOAL)
    d2.regular_polygon((title_w / 2 - w2 / 2 - 24, 122, 6), n_sides=4, rotation=45, fill=GOLD)
    d2.regular_polygon((title_w / 2 + w2 / 2 + 24, 122, 6), n_sides=4, rotation=45, fill=GOLD)

    title.save(out_dir / "title_block.png")


def build_glass_card(out_dir: Path, idx: int, label: str, value: str):
    icon_key = ICON_ORDER[(idx - 1) % len(ICON_ORDER)]
    card_w, card_h, r = 800, 210, 22
    pad = 40
    canvas = Image.new("RGBA", (card_w + pad * 2, card_h + pad * 2), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=r, fill=(30, 22, 12, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(shadow, (pad, pad + 10))

    panel = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=r, fill=(255, 251, 244, 150))
    canvas.alpha_composite(panel, (pad, pad))

    sheen = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).rounded_rectangle([0, 0, card_w - 1, int(card_h * 0.5)], radius=r, fill=(255, 255, 255, 55))
    sheen = sheen.filter(ImageFilter.GaussianBlur(10))
    sheen_mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(sheen_mask).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=r, fill=255)
    canvas.alpha_composite(Image.composite(sheen, Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0)), sheen_mask), (pad, pad))

    border = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=r, outline=(*GOLD[:3], 210), width=2)
    canvas.alpha_composite(border, (pad, pad))

    icon = ICONS[icon_key](size=72)
    canvas.alpha_composite(icon, (pad + 20, pad + int(card_h / 2 - 36)))
    dd = ImageDraw.Draw(canvas)
    dd.text((pad + 108, pad + 30), label, font=sfont(34, "SemiBold"), fill=GOLD_DEEP)
    dd.text((pad + 108, pad + 98), value, font=sfont(40, "Regular"), fill=CHARCOAL)
    canvas.save(out_dir / f"gold_card{idx}.png")


def build_step_badge(out_dir: Path, n: int, size=176):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([8, 8, size - 8, size - 8], outline=GOLD, width=4)
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)))
    d.ellipse([8, 8, size - 8, size - 8], fill=(20, 16, 12, 235), outline=GOLD, width=4)
    d.ellipse([16, 16, size - 16, size - 16], outline=GOLD, width=1)
    f = sfont(78, "SemiBold")
    text = f"{n:02d}"
    tw = d.textlength(text, font=f)
    d.text(((size - tw) / 2, size / 2 - 54), text, font=f, fill=GOLD_LIGHT)
    im.save(out_dir / f"step_badge{n}.png")


def build_caption(out_dir: Path, name: str, text: str, max_width=920, font_size=38, min_font_size=22):
    """자막은 항상 한 줄로만 렌더링한다 (2026-08-27, 2~3줄로 늘어나는 게 지저분하다는
    피드백으로 줄바꿈 대신 폰트 크기를 줄여서 한 줄에 맞추는 방식으로 변경)."""
    tmp = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(tmp)
    size = font_size
    f = sfont(size, "SemiBold")
    while d0.textlength(text, font=f) > max_width - 60 and size > min_font_size:
        size -= 2
        f = sfont(size, "SemiBold")

    line_h = int(size * 1.3)
    pad = 20
    h = line_h + pad * 2
    w = max_width
    pill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=18, fill=(18, 14, 10, 175))
    d.rounded_rectangle([0, 0, w - 1, 2], radius=0, fill=(*GOLD_LIGHT[:3], 200))
    lw = d0.textlength(text, font=f)
    d.text(((w - lw) / 2, pad), text, font=f, fill=(250, 246, 238, 255))
    pill.save(out_dir / f"caption_{name}.png")


def build_cta_button(out_dir: Path, text="지금 링크 확인 ▶"):
    w, h = 560, 108
    btn = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(btn)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle([8, 8, w - 8, h - 8], radius=(h - 16) // 2, fill=(255, 214, 140, 120))
    btn.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
    d.rounded_rectangle([8, 8, w - 8, h - 8], radius=(h - 16) // 2, fill=(214, 168, 92, 255), outline=(255, 240, 210, 255), width=2)
    f = sfont(38, "SemiBold")
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, (h - 46) / 2), text, font=f, fill=(35, 26, 14, 255))
    btn.save(out_dir / "cta_button.png")


def build_product_assets(out_dir: Path, product_image_path: Path, frame_w=600):
    prod = Image.open(product_image_path).convert("RGBA")
    frame_h = frame_w
    radius, border = int(frame_w * 0.047), 5
    pw, ph = prod.size
    scale = max(frame_w / pw, frame_h / ph)
    nw, nh = int(pw * scale), int(ph * scale)
    prod_r = prod.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - frame_w) // 2, (nh - frame_h) // 2
    prod_c = prod_r.crop((left, top, left + frame_w, top + frame_h))
    mask = Image.new("L", (frame_w, frame_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, frame_w - 1, frame_h - 1], radius=radius, fill=255)
    framed = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    framed.paste(prod_c, (0, 0), mask)

    pad = int(frame_w * 0.05)
    canvas = Image.new("RGBA", (frame_w + pad * 2, frame_h + pad * 2), (0, 0, 0, 0))
    ring = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle([0, 0, frame_w - 1, frame_h - 1], radius=radius, outline=GOLD, width=border)
    canvas.alpha_composite(ring.filter(ImageFilter.GaussianBlur(6)), (pad, pad))
    canvas.alpha_composite(framed, (pad, pad))
    ImageDraw.Draw(canvas).rounded_rectangle([pad, pad, pad + frame_w - 1, pad + frame_h - 1], radius=radius, outline=GOLD, width=border)
    canvas.save(out_dir / "product_framed.png")

    fw, fh = canvas.size
    shadow_canvas = Image.new("RGBA", (fw + 70, 120), (0, 0, 0, 0))
    ImageDraw.Draw(shadow_canvas).ellipse([45, 12, fw + 25, 100], fill=(20, 14, 8, 150))
    shadow_canvas = shadow_canvas.filter(ImageFilter.GaussianBlur(22))
    shadow_canvas.save(out_dir / "product_shadow.png")

    # 2026-08-27: 카드와 간격이 좁아서(10px) 리플렉션의 둥근 모서리가 마치 카드
    # 조각이 튀어나온 것처럼 보인다는 피드백 — 훨씬 짧고 옅게, 가우시안 블러로
    # 윤곽선 자체를 흐려서 "형태가 있는 조각"이 아니라 은은한 광택 정도로만 보이게 함.
    refl_h = max(20, int(fh * 0.035))
    reflection = ImageOps.flip(canvas).convert("RGBA").crop((0, 0, fw, refl_h))
    grad = Image.new("L", (fw, refl_h), 0)
    gd = ImageDraw.Draw(grad)
    for y in range(refl_h):
        gd.line([(0, y), (fw, y)], fill=int(40 * (1 - y / refl_h)))
    r, g, b, a0 = reflection.split()
    a_arr = (np.asarray(a0).astype(float) * (np.asarray(grad).astype(float) / 255.0)).astype("uint8")
    reflection.putalpha(Image.fromarray(a_arr, mode="L"))
    reflection = reflection.filter(ImageFilter.GaussianBlur(4))
    reflection.save(out_dir / "product_reflection.png")

    return canvas.size


def build_all(out_dir: Path, product_name: str, price: str, product_image_path: Path,
              spec1, spec2, spec3, hook_speech: str, cta_speech: str,
              cta_text: str = "지금 링크 확인 ▶"):
    out_dir.mkdir(parents=True, exist_ok=True)
    build_bg(out_dir)
    build_vignette(out_dir)
    build_flash(out_dir)
    build_ai_tag(out_dir)
    build_logo_xl(out_dir)
    build_title_block(out_dir, product_name, price)
    canvas_size = build_product_assets(out_dir, product_image_path)
    for i, (label, value) in enumerate((spec1, spec2, spec3), start=1):
        build_glass_card(out_dir, i, label, value)
        build_step_badge(out_dir, i)
        build_caption(out_dir, f"beat{i}", value)
    build_caption(out_dir, "hook", hook_speech)
    build_caption(out_dir, "cta", cta_speech)
    build_cta_button(out_dir, cta_text)
    print(f"[build_graphics] 전체 그래픽 생성 완료: {out_dir} (product canvas {canvas_size})")
    return canvas_size
