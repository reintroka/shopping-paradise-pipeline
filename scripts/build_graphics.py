"""쇼핑의천국 골드 럭셔리 디자인 시스템 그래픽 생성기 (재사용 가능, 파라미터화 버전).

2026-08-26 세션에서 확정된 디자인(v10)을 이식: 크림 배경 + 골드 테두리 카드 +
원형 프레임 제품사진 + 골드 라벨 타이틀 + 다크골드 리본 훅 배지 + 밝은 골드 필 CTA 버튼.

클라우드 사이드박스(Ubuntu, Malgun Gothic 없음)용으로 Noto Sans KR 가변폰트 사용.

사용법:
    python build_graphics.py --out-dir ./work --product-name "LG 그램15" \
        --price "898,000원대" --spec1-title 성능 --spec1-body "..." ...
    (또는 다른 스크립트에서 build_all(**kwargs) 직접 호출)
"""
import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
FONT_PATH = HERE.parent / "assets" / "fonts" / "NotoSansKR-Regular.ttf"
LOGO_PATH = HERE.parent / "assets" / "logo" / "channel_logo.png"

CREAM = (246, 239, 226, 255)
GOLD = (168, 124, 58, 255)
GOLD_DEEP = (140, 100, 45, 255)
GOLD_LIGHT = (205, 168, 108, 255)
CHARCOAL = (40, 34, 27, 255)

random.seed()


def font(size, bold=False):
    f = ImageFont.truetype(str(FONT_PATH), size)
    f.set_variation_by_axes([700 if bold else 400])
    return f


def spaced_text(draw, xy, text, fnt, fill, tracking=8):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking


def build_bg_bright(out_dir: Path):
    W, H = 1080, 1920
    bg = Image.new("RGBA", (W, H), CREAM)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W / 2 - 460, 500, W / 2 + 460, 1400], fill=(255, 244, 214, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    bg = Image.alpha_composite(bg, glow)
    particles = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(particles)
    for _ in range(45):
        x = random.randint(0, W)
        y = random.randint(0, H)
        r = random.uniform(1.2, 2.6)
        a = random.randint(30, 80)
        pd.ellipse([x - r, y - r, x + r, y + r], fill=(*GOLD_LIGHT[:3], a))
    particles = particles.filter(ImageFilter.GaussianBlur(0.5))
    bg = Image.alpha_composite(bg, particles)
    path = out_dir / "bg_bright.png"
    bg.save(path)
    return path


def build_title_block(out_dir: Path, product_name: str, price: str):
    title_w, title_h = 900, 190
    title = Image.new("RGBA", (title_w, title_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(title)
    d.rounded_rectangle([60, 10, title_w - 60, title_h - 40], radius=14, outline=GOLD, width=2)
    d.rounded_rectangle([66, 16, title_w - 66, title_h - 46], radius=11, outline=GOLD, width=1)
    f1 = font(50, bold=True)
    f2 = font(34)
    tmp = Image.new("RGBA", (10, 10))
    td0 = ImageDraw.Draw(tmp)
    tracked_w = sum(td0.textlength(c, font=f1) + 8 for c in product_name) - 8
    spaced_text(d, ((title_w - tracked_w) / 2, 32), product_name, f1, CHARCOAL, tracking=8)
    w2 = td0.textlength(price, font=f2)
    d.text(((title_w - w2) / 2, 100), price, font=f2, fill=GOLD_DEEP)
    d.regular_polygon((title_w / 2 - w2 / 2 - 24, 118, 6), n_sides=4, rotation=45, fill=GOLD)
    d.regular_polygon((title_w / 2 + w2 / 2 + 24, 118, 6), n_sides=4, rotation=45, fill=GOLD)
    path = out_dir / "title_block.png"
    title.save(path)
    return path


def build_gold_card(out_dir: Path, idx: int, title_text: str, body_text: str):
    card_w, card_h, r = 800, 210, 22
    pad = 36
    canvas = Image.new("RGBA", (card_w + pad * 2, card_h + pad * 2), (0, 0, 0, 0))
    glow_b = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    gbd = ImageDraw.Draw(glow_b)
    gbd.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=r, outline=GOLD, width=2)
    glow_b = glow_b.filter(ImageFilter.GaussianBlur(6))
    canvas.alpha_composite(glow_b, (pad, pad))
    panel = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    pdw = ImageDraw.Draw(panel)
    pdw.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=r, fill=(252, 248, 239, 235))
    pdw.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=r, outline=GOLD, width=2)
    canvas.alpha_composite(panel, (pad, pad))
    dd = ImageDraw.Draw(canvas)
    dd.ellipse([pad + 34, pad + 46, pad + 46, pad + 58], fill=GOLD)
    ft = font(36, bold=True)
    fb = font(44)
    dd.text((pad + 60, pad + 32), title_text, font=ft, fill=GOLD_DEEP)
    dd.text((pad + 34, pad + 98), body_text, font=fb, fill=CHARCOAL)
    path = out_dir / f"gold_card{idx}.png"
    canvas.save(path)
    return path


def build_product_framed(out_dir: Path, product_image_path: Path):
    prod = Image.open(product_image_path).convert("RGBA")
    frame_w, frame_h, radius, border = 780, 780, 36, 5
    pw, ph = prod.size
    scale = max(frame_w / pw, frame_h / ph)
    new_w, new_h = int(pw * scale), int(ph * scale)
    prod_resized = prod.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - frame_w) // 2
    top = (new_h - frame_h) // 2
    prod_cropped = prod_resized.crop((left, top, left + frame_w, top + frame_h))
    mask = Image.new("L", (frame_w, frame_h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, frame_w - 1, frame_h - 1], radius=radius, fill=255)
    framed = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    framed.paste(prod_cropped, (0, 0), mask)
    canvas = Image.new("RGBA", (frame_w + 80, frame_h + 80), (0, 0, 0, 0))
    glow_ring = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    gd2 = ImageDraw.Draw(glow_ring)
    gd2.rounded_rectangle([0, 0, frame_w - 1, frame_h - 1], radius=radius, outline=GOLD, width=border)
    glow_ring = glow_ring.filter(ImageFilter.GaussianBlur(8))
    canvas.alpha_composite(glow_ring, (40, 40))
    canvas.alpha_composite(framed, (40, 40))
    dd = ImageDraw.Draw(canvas)
    dd.rounded_rectangle([40, 40, 40 + frame_w - 1, 40 + frame_h - 1], radius=radius, outline=GOLD, width=border)
    path = out_dir / "product_framed.png"
    canvas.save(path)
    return path


def build_hook_title(out_dir: Path, line1: str, line2: str, w=1000):
    f = font(62, bold=True)
    tmp = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(tmp)
    w1_ = d0.textlength(line1, font=f)
    w2_ = d0.textlength(line2, font=f) if line2 else 0
    h = 230 if line2 else 130
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pad_x = (w - max(w1_, w2_) - 100) / 2
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pdw = ImageDraw.Draw(panel)
    pdw.rounded_rectangle([pad_x, 6, w - pad_x, h - 6], radius=16, fill=(20, 16, 12, 225), outline=GOLD, width=3)
    pdw.rounded_rectangle([pad_x + 6, 12, w - pad_x - 6, h - 12], radius=12, outline=GOLD, width=1)
    canvas = Image.alpha_composite(canvas, panel)
    d = ImageDraw.Draw(canvas)
    d.text(((w - w1_) / 2, 28), line1, font=f, fill=(250, 244, 232, 255))
    if line2:
        d.text(((w - w2_) / 2, 120), line2, font=f, fill=GOLD_LIGHT)
    path = out_dir / "hook_title.png"
    canvas.save(path)
    return path


def build_cta_banner(out_dir: Path, text: str = "지금 링크 확인 ▶"):
    w, h = 560, 108
    f = font(40, bold=True)
    banner = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle([4, 4, w - 5, h - 5], radius=h // 2, fill=(224, 178, 96, 160))
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    banner = Image.alpha_composite(banner, glow)
    bd = ImageDraw.Draw(banner)
    bd.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=(224, 178, 96, 255), outline=(255, 240, 210, 255), width=2)
    tw = bd.textlength(text, font=f)
    bd.text(((w - tw) / 2, (h - 52) / 2), text, font=f, fill=CHARCOAL)
    path = out_dir / "cta_banner.png"
    banner.save(path)
    return path


def build_caption(out_dir: Path, name: str, text: str, max_width=860):
    f = font(44, bold=True)
    tmp = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(tmp)
    words = text.split(" ")
    lines = []
    cur = ""
    for w_ in words:
        test = (cur + " " + w_).strip()
        if d0.textlength(test, font=f) > max_width - 60:
            lines.append(cur)
            cur = w_
        else:
            cur = test
    if cur:
        lines.append(cur)
    line_h = 60
    pad = 28
    h = line_h * len(lines) + pad * 2
    w = max_width
    pill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=26, fill=(20, 16, 12, 190))
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=f)
        d.text(((w - lw) / 2, pad + i * line_h), line, font=f, fill=(255, 255, 255, 255))
    path = out_dir / f"caption_{name}.png"
    pill.save(path)
    return path


def build_logo_xl(out_dir: Path):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    scale = 520 / logo.width
    logo_xl = logo.resize((520, int(logo.height * scale)), Image.LANCZOS)
    path = out_dir / "channel_logo_xl.png"
    logo_xl.save(path)
    return path


def build_all(out_dir: Path, product_name: str, price: str, product_image_path: Path,
              spec1, spec2, spec3, hook_line1: str, hook_line2: str,
              hook_speech: str = "", cta_speech: str = "", cta_text: str = "지금 링크 확인 ▶"):
    out_dir.mkdir(parents=True, exist_ok=True)
    build_bg_bright(out_dir)
    build_title_block(out_dir, product_name, price)
    build_gold_card(out_dir, 1, spec1[0], spec1[1])
    build_gold_card(out_dir, 2, spec2[0], spec2[1])
    build_gold_card(out_dir, 3, spec3[0], spec3[1])
    build_product_framed(out_dir, product_image_path)
    build_hook_title(out_dir, hook_line1, hook_line2)
    build_cta_banner(out_dir, cta_text)
    build_logo_xl(out_dir)
    if hook_speech:
        build_caption(out_dir, "hook", hook_speech)
    if cta_speech:
        build_caption(out_dir, "cta", cta_speech)
    print(f"[build_graphics] 전체 그래픽 생성 완료: {out_dir}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--product-image", required=True)
    p.add_argument("--spec1-title", required=True)
    p.add_argument("--spec1-body", required=True)
    p.add_argument("--spec2-title", required=True)
    p.add_argument("--spec2-body", required=True)
    p.add_argument("--spec3-title", required=True)
    p.add_argument("--spec3-body", required=True)
    p.add_argument("--hook-line1", required=True)
    p.add_argument("--hook-line2", required=True)
    p.add_argument("--cta-text", default="지금 링크 확인 ▶")
    args = p.parse_args()

    build_all(
        Path(args.out_dir),
        args.product_name,
        args.price,
        Path(args.product_image),
        (args.spec1_title, args.spec1_body),
        (args.spec2_title, args.spec2_body),
        (args.spec3_title, args.spec3_body),
        args.hook_line1,
        args.hook_line2,
        args.cta_text,
    )
