# -*- coding: utf-8 -*-
"""쓰레드(Threads) 카드뉴스(캐러셀) 3장 생성.

2026-09-18: 사용자가 직접 써보니 쓰레드는 영상 릴스보다 글/카드섹션 포스팅의
조회수가 더 잘 나온다는 피드백 — 기존 릴스와 별개로 같은 상품 데이터를 카드뉴스
형태로도 재발행하기로 함(같은 날 이미 선정된 상품이라 별도 상품 선정 로직 없음).

build_graphics.py의 골드 럭셔리 디자인 시스템(색상/폰트/줄바꿈 헬퍼)을 그대로
재사용하되, 세로 릴스(1080x1920)가 아니라 피드 캐러셀에 맞는 4:5(1080x1350)
캔버스로 새로 구성한다.

카드 구성:
  1. 훅 카드 — 상품 썸네일 + 후킹 문구(hook_speech)
  2. 스펙 카드 — spec1~3 title/body 3개
  3. CTA 카드 — 가격 + cta_speech + 프로필 링크 안내

사용법: build_all(out_dir, product_name, price, product_image_path,
                   spec1, spec2, spec3, hook_speech, cta_speech, rank=None)
  → out_dir/thread_card1.png, thread_card2.png, thread_card3.png 생성
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_graphics import (  # noqa: E402
    ASSETS, CHARCOAL, CREAM, GOLD, GOLD_DEEP, GOLD_LIGHT, LOGO_PATH,
    _wrap_lines, draw_tracked, sfont, tracked_width,
)

W, H = 1080, 1350
PAD = 72


def _base_canvas():
    bg = Image.new("RGBA", (W, H), CREAM)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.5 - 700, -500, W * 0.5 + 700, 700], fill=(*GOLD_LIGHT[:3], 40))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    bg.alpha_composite(glow)
    return bg


def _paste_logo(canvas):
    logo = Image.open(LOGO_PATH).convert("RGBA")
    new_w = 200
    new_h = int(logo.height * new_w / logo.width)
    logo = logo.resize((new_w, new_h), Image.LANCZOS)
    canvas.alpha_composite(logo, (PAD, 56))


def _rounded_panel(w, h, r, fill_alpha=150, border=True):
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=(30, 22, 12, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(shadow, (6, 10))
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=(255, 251, 244, fill_alpha))
    canvas.alpha_composite(panel)
    if border:
        border_im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(border_im).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, outline=(*GOLD[:3], 200), width=2)
        canvas.alpha_composite(border_im)
    return canvas


def build_hook_card(product_name, hook_speech, product_image_path, rank=None):
    canvas = _base_canvas()
    _paste_logo(canvas)

    if rank is not None:
        badge_font = sfont(30, "Bold")
        badge_text = f"No.{rank}"
        bw = int(tracked_width(badge_text, badge_font, 2)) + 36
        badge = _rounded_panel(bw, 56, 28)
        canvas.alpha_composite(badge, (W - PAD - bw, 60))
        bd = ImageDraw.Draw(canvas)
        draw_tracked(bd, (W - PAD - bw + 18, 76), badge_text, badge_font, GOLD_DEEP, 2)

    eyebrow_font = sfont(34, "Bold")
    d = ImageDraw.Draw(canvas)
    draw_tracked(d, (PAD, 180), "오늘의 추천템", eyebrow_font, GOLD_DEEP, 4)

    name_font = sfont(56, "Bold")
    name_lines = _wrap_lines(product_name, name_font, d, W - PAD * 2)
    y = 232
    for line in name_lines[:2]:
        d.text((PAD, y), line, font=name_font, fill=CHARCOAL)
        y += 68

    img = Image.open(product_image_path).convert("RGBA")
    img = ImageOps.contain(img, (700, 560))
    frame = _rounded_panel(img.width + 40, img.height + 40, 32, fill_alpha=200)
    fx = (W - frame.width) // 2
    fy = y + 30
    canvas.alpha_composite(frame, (fx, fy))
    canvas.alpha_composite(img, (fx + 20, fy + 20))

    hook_font = sfont(40, "Bold")
    hook_lines = _wrap_lines(hook_speech, hook_font, d, W - PAD * 2)
    hy = fy + frame.height + 50
    for line in hook_lines[:3]:
        d.text((PAD, hy), line, font=hook_font, fill=CHARCOAL)
        hy += 54

    return canvas


def build_spec_card(specs):
    canvas = _base_canvas()
    _paste_logo(canvas)
    d = ImageDraw.Draw(canvas)

    title_font = sfont(48, "Bold")
    draw_tracked(d, (PAD, 180), "핵심 스펙 3가지", title_font, GOLD_DEEP, 2)

    panel_h = 300
    gap = 30
    y = 280
    title_font2 = sfont(38, "Bold")
    body_font = sfont(32)
    for spec_title, spec_body in specs:
        panel_w = W - PAD * 2
        panel = _rounded_panel(panel_w, panel_h, 26)
        canvas.alpha_composite(panel, (PAD, y))
        pd = ImageDraw.Draw(canvas)
        pd.text((PAD + 36, y + 34), spec_title, font=title_font2, fill=GOLD_DEEP)
        body_lines = _wrap_lines(spec_body, body_font, pd, panel_w - 72)
        by = y + 100
        for line in body_lines[:3]:
            pd.text((PAD + 36, by), line, font=body_font, fill=CHARCOAL)
            by += 44
        y += panel_h + gap

    return canvas


def build_cta_card(price, cta_speech):
    canvas = _base_canvas()
    _paste_logo(canvas)
    d = ImageDraw.Draw(canvas)

    price_font = sfont(88, "Bold")
    price_text = price
    pw = tracked_width(price_text, price_font, 0)
    draw_tracked(d, ((W - pw) / 2, 380), price_text, price_font, GOLD_DEEP, 0)

    cta_font = sfont(42, "Bold")
    cta_lines = _wrap_lines(cta_speech, cta_font, d, W - PAD * 2)
    cy = 540
    for line in cta_lines[:4]:
        lw = d.textlength(line, font=cta_font)
        d.text(((W - lw) / 2, cy), line, font=cta_font, fill=CHARCOAL)
        cy += 58

    btn_w, btn_h = 560, 110
    btn = _rounded_panel(btn_w, btn_h, 55, fill_alpha=230)
    bx, by = (W - btn_w) // 2, H - 260
    canvas.alpha_composite(btn, (bx, by))
    btn_font = sfont(38, "Bold")
    label = "프로필 링크에서 확인하기"
    lw = tracked_width(label, btn_font, 2)
    draw_tracked(d, ((W - lw) / 2, by + btn_h / 2 - 22), label, btn_font, GOLD_DEEP, 2)

    return canvas


def build_all(out_dir: Path, product_name: str, price: str, product_image_path: Path,
              spec1, spec2, spec3, hook_speech: str, cta_speech: str, rank=None):
    out_dir = Path(out_dir)
    build_hook_card(product_name, hook_speech, product_image_path, rank=rank).convert("RGB").save(
        out_dir / "thread_card1.png")
    build_spec_card([spec1, spec2, spec3]).convert("RGB").save(out_dir / "thread_card2.png")
    build_cta_card(price, cta_speech).convert("RGB").save(out_dir / "thread_card3.png")
    return [out_dir / "thread_card1.png", out_dir / "thread_card2.png", out_dir / "thread_card3.png"]
