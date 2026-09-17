# -*- coding: utf-8 -*-
"""쓰레드(Threads) 카드뉴스(캐러셀) 3장 생성.

2026-09-18: 사용자가 직접 써보니 쓰레드는 영상 릴스보다 글/카드섹션 포스팅의
조회수가 더 잘 나온다는 피드백 — 기존 릴스와 별개로 같은 상품 데이터를 카드뉴스
형태로도 재발행하기로 함(같은 날 이미 선정된 상품이라 별도 상품 선정 로직 없음).

build_graphics.py의 골드 럭셔리 디자인 시스템(색상/폰트/줄바꿈 헬퍼)을 그대로
재사용하되, 세로 릴스(1080x1920)가 아니라 피드 캐러셀에 맞는 4:5(1080x1350)
캔버스로 새로 구성한다.

2026-09-18 디자인 v2(사용자 피드백 "디자인적으로 좀더 깔끔하게", "퀄리티 있게"):
  - 페이지 인디케이터(1/3~3/3)로 캐러셀임을 한눈에 알 수 있게
  - 상품명은 build_graphics.py의 세이프존 로직처럼 폭에 안 맞으면 폰트를
    줄여가며 맞추고, 그래도 안 맞으면 말줄임 — 중간에 뚝 잘리지 않게
  - 스펙 카드는 본문 줄 수에 맞춰 패널 높이를 동적으로 계산해 붙여서(고정
    300px 대신) 예전처럼 패널 안이 휑하게 비지 않음, 번호 배지(01/02/03) 추가
  - CTA 카드는 상품 썸네일 원형 배지 + 골드 디바이더로 가운데가 비어 보이지
    않게 채움

카드 구성:
  1. 훅 카드 — 상품 썸네일 + 후킹 문구(hook_speech)
  2. 스펙 카드 — spec1~3 title/body 3개
  3. CTA 카드 — 가격 + cta_speech + 프로필 링크 안내

사용법: build_all(out_dir, product_name, price, product_image_path,
                   spec1, spec2, spec3, hook_speech, cta_speech, rank=None)
  → out_dir/thread_card1.png, thread_card2.png, thread_card3.png 생성
  (product_name은 잘리지 않은 원문을 넘기는 걸 권장 — 카드 안에서 알아서
  폭에 맞게 줄이거나 말줄임 처리한다)
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


def _page_dots(canvas, index, total=3):
    """캐러셀 진행도(●○○ 형태)를 로고 옆 오른쪽 위에 표시 — 스와이프해서 더
    볼 내용이 있다는 걸 한눈에 알 수 있게(2026-09-18 디자인 개선)."""
    d = ImageDraw.Draw(canvas)
    r, gap = 8, 22
    total_w = (total - 1) * gap
    x0 = W - PAD - total_w
    y = 92
    for i in range(total):
        x = x0 + i * gap
        if i == index:
            d.ellipse([x - r, y - r, x + r, y + r], fill=(*GOLD_DEEP[:3], 255))
        else:
            d.ellipse([x - r, y - r, x + r, y + r], outline=(*GOLD[:3], 180), width=2)


def _rounded_panel(w, h, r, fill_alpha=235, border=True):
    """크림색 라운드 패널(배지/스펙 카드/CTA 버튼에 공용으로 사용).

    2026-09-18 버그 수정: 예전엔 그림자를 패널과 같은 크기로 그린 뒤 (6,10)만큼
    오프셋해서 붙였는데, 캔버스 크기가 그림자보다 크지 않아 블러 번짐이 캔버스
    경계에서 그대로 잘렸다 — 그 결과 패널의 둥근 모서리 바깥으로 그림자(어두운
    색)가 각지게 삐져나온 것처럼 보였다("배경이 삐져나온다" 피드백, No.2 배지/
    스펙 패널/CTA 버튼 전부 이 함수를 공용으로 써서 셋 다 같은 문제였음).
    오프셋 없이 패널보다 작게(inset) 그림자를 그려 블러가 퍼져도 항상 패널
    안쪽에서만 보이게 바꾸고, 채우기도 더 불투명하게 올려 배경이 비쳐 보이는
    것도 줄였다.
    """
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    inset = 12
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [inset, inset, w - 1 - inset, h - 1 - inset], radius=max(4, r - inset), fill=(30, 22, 12, 100))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas.alpha_composite(shadow)
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=(255, 251, 244, fill_alpha))
    canvas.alpha_composite(panel)
    if border:
        border_im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(border_im).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, outline=(*GOLD[:3], 200), width=2)
        canvas.alpha_composite(border_im)
    return canvas


def _fit_title(text, draw, max_w, start_size=58, min_size=36, weight="Bold", max_lines=2):
    """build_graphics.py의 상품명 세이프존 로직(폭 안 맞으면 폰트를 줄여가며
    맞추고 그래도 안 되면 말줄임)을 카드용으로 확장 — 1줄이 아니라 최대
    max_lines줄까지 줄바꿈을 허용한 뒤에도 안 맞으면 마지막 줄을 말줄임한다."""
    size = start_size
    while size >= min_size:
        font = sfont(size, weight)
        lines = _wrap_lines(text, font, draw, max_w)
        if len(lines) <= max_lines:
            return lines, font
        size -= 2
    font = sfont(min_size, weight)
    lines = _wrap_lines(text, font, draw, max_w)[:max_lines]
    last = lines[-1]
    while tracked_width(last + "…", font, 0) > max_w and len(last) > 1:
        last = last[:-1]
    lines[-1] = last.rstrip() + "…"
    return lines, font


def _circle_thumb(image_path, diameter):
    img = Image.open(image_path).convert("RGBA")
    img = ImageOps.fit(img, (diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, diameter - 1, diameter - 1], fill=255)
    ring = Image.new("RGBA", (diameter + 12, diameter + 12), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([0, 0, diameter + 11, diameter + 11], outline=(*GOLD[:3], 220), width=4)
    out = Image.new("RGBA", (diameter + 12, diameter + 12), (0, 0, 0, 0))
    out.alpha_composite(Image.composite(img, Image.new("RGBA", img.size, (0, 0, 0, 0)), mask), (6, 6))
    out.alpha_composite(ring)
    return out


def build_hook_card(product_name, hook_speech, product_image_path, rank=None):
    canvas = _base_canvas()
    _paste_logo(canvas)
    _page_dots(canvas, 0)

    if rank is not None:
        badge_font = sfont(30, "Bold")
        badge_text = f"No.{rank}"
        bw = int(tracked_width(badge_text, badge_font, 2)) + 36
        badge = _rounded_panel(bw, 56, 28)
        canvas.alpha_composite(badge, (W - PAD - bw, 120))
        bd = ImageDraw.Draw(canvas)
        draw_tracked(bd, (W - PAD - bw + 18, 136), badge_text, badge_font, GOLD_DEEP, 2)

    eyebrow_font = sfont(34, "Bold")
    d = ImageDraw.Draw(canvas)
    draw_tracked(d, (PAD, 200), "오늘의 추천템", eyebrow_font, GOLD_DEEP, 4)

    name_lines, name_font = _fit_title(product_name, d, W - PAD * 2, start_size=58, min_size=38)
    line_h = int(name_font.size * 1.22)
    y = 254
    for line in name_lines:
        d.text((PAD, y), line, font=name_font, fill=CHARCOAL)
        y += line_h

    # 2026-09-18: 예전엔 상품사진을 ImageOps.contain으로 줄여 넣고 그 둘레에
    # 크림색 카드 패널을 덧대는 방식이었는데, 상품사진 자체의 흰 스튜디오
    # 배경이 사각형 그대로 도드라져서 카드 배경(크림)과 이중 테두리처럼 겹쳐
    # 보였다("배경이 삐져나온다" 피드백). build_graphics.py의 릴스 상품컷과
    # 동일하게 crop-to-fill(딱 맞게 꽉 채워 자르기) + 라운드 코너 + 금테를
    # 사진 가장자리에 바로 둘러서 이중 프레임 없이 한 장의 카드처럼 보이게 함.
    frame_w, frame_h = 660, 520
    img = ImageOps.fit(Image.open(product_image_path).convert("RGBA"), (frame_w, frame_h), Image.LANCZOS)
    mask = Image.new("L", (frame_w, frame_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, frame_w - 1, frame_h - 1], radius=32, fill=255)
    framed = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    framed.paste(img, (0, 0), mask)
    ImageDraw.Draw(framed).rounded_rectangle([0, 0, frame_w - 1, frame_h - 1], radius=32, outline=(*GOLD[:3], 230), width=4)

    fy = y + 34
    fx = (W - frame_w) // 2

    shadow = Image.new("RGBA", (frame_w + 80, 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([40, 10, frame_w + 40, 50], fill=(60, 44, 24, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    canvas.alpha_composite(shadow, (fx - 40, fy + frame_h - 26))
    canvas.alpha_composite(framed, (fx, fy))

    quote_y = fy + frame_h + 46
    hook_font = sfont(38, "Bold")
    hook_lines = _wrap_lines(hook_speech, hook_font, d, W - PAD * 2 - 44)
    quote_h = 40 + len(hook_lines[:3]) * 50
    quote_panel_w = W - PAD * 2
    accent = Image.new("RGBA", (8, quote_h), (*GOLD[:3], 255))
    canvas.paste(accent, (PAD, quote_y), accent)
    hy = quote_y + 6
    for line in hook_lines[:3]:
        d.text((PAD + 34, hy), line, font=hook_font, fill=CHARCOAL)
        hy += 50

    return canvas


def build_spec_card(specs):
    canvas = _base_canvas()
    _paste_logo(canvas)
    _page_dots(canvas, 1)
    d = ImageDraw.Draw(canvas)

    title_font = sfont(48, "Bold")
    draw_tracked(d, (PAD, 200), "핵심 스펙 3가지", title_font, GOLD_DEEP, 2)

    panel_w = W - PAD * 2
    badge_d = 60
    title_font2 = sfont(36, "Bold")
    body_font = sfont(32)
    inner_pad = 36
    text_x = PAD + inner_pad + badge_d + 22

    # 본문 줄 수에 맞춰 패널 높이를 먼저 계산(2026-09-18: 예전엔 고정 300px라
    # 짧은 스펙 문구일 때 패널 아래쪽이 텅 비어 보였음).
    laid_out = []
    total_h = 0
    for spec_title, spec_body in specs:
        body_lines = _wrap_lines(spec_body, body_font, d, panel_w - (text_x - PAD) - inner_pad)[:2]
        panel_h = inner_pad + 54 + len(body_lines) * 44 + inner_pad
        panel_h = max(panel_h, 172)
        laid_out.append((spec_title, body_lines, panel_h))
        total_h += panel_h
    gap = 28
    total_h += gap * (len(laid_out) - 1)

    # 고정 top(제목 바로 아래 여백)에서 시작 — 남은 공간을 다 채우려고 화면
    # 중앙까지 내리면 제목과 첫 패널 사이가 지나치게 벌어져 보였다(2026-09-18).
    # 스펙 문구가 길어 총 높이가 넘칠 때만 아래쪽 안전선(H-90)에 맞춰 끌어올린다.
    avail_top, avail_bottom = 330, H - 90
    y = min(avail_top, avail_bottom - total_h)

    for i, (spec_title, body_lines, panel_h) in enumerate(laid_out):
        panel = _rounded_panel(panel_w, panel_h, 26)
        canvas.alpha_composite(panel, (PAD, y))
        pd = ImageDraw.Draw(canvas)

        badge_x, badge_y = PAD + inner_pad, y + (panel_h - badge_d) // 2
        pd.ellipse([badge_x, badge_y, badge_x + badge_d, badge_y + badge_d], fill=(*GOLD_DEEP[:3], 255))
        num_font = sfont(28, "Bold")
        num_text = f"0{i + 1}"
        nw = pd.textlength(num_text, font=num_font)
        pd.text((badge_x + (badge_d - nw) / 2, badge_y + badge_d / 2 - 19), num_text, font=num_font, fill=CREAM)

        ty = y + inner_pad
        pd.text((text_x, ty), spec_title, font=title_font2, fill=GOLD_DEEP)
        by = ty + 54
        for line in body_lines:
            pd.text((text_x, by), line, font=body_font, fill=CHARCOAL)
            by += 44

        y += panel_h + gap

    return canvas


def build_cta_card(price, cta_speech, product_image_path=None):
    canvas = _base_canvas()
    _paste_logo(canvas)
    _page_dots(canvas, 2)
    d = ImageDraw.Draw(canvas)

    center_y = 300
    if product_image_path is not None:
        thumb = _circle_thumb(product_image_path, 168)
        canvas.alpha_composite(thumb, ((W - thumb.width) // 2, center_y))
        center_y += thumb.height + 40

    price_font = sfont(86, "Bold")
    pw = tracked_width(price, price_font, 0)
    draw_tracked(d, ((W - pw) / 2, center_y), price, price_font, GOLD_DEEP, 0)
    center_y += 118

    divider_w = 120
    d.line([(W - divider_w) / 2, center_y, (W + divider_w) / 2, center_y], fill=(*GOLD[:3], 220), width=3)
    center_y += 46

    cta_font = sfont(42, "Bold")
    cta_lines = _wrap_lines(cta_speech, cta_font, d, W - PAD * 2)
    for line in cta_lines[:4]:
        lw = d.textlength(line, font=cta_font)
        d.text(((W - lw) / 2, center_y), line, font=cta_font, fill=CHARCOAL)
        center_y += 58

    btn_w, btn_h = 580, 112
    btn = _rounded_panel(btn_w, btn_h, 56, fill_alpha=235)
    # cta_speech가 짧아 위 내용이 일찍 끝나면 버튼을 바로 아래로 끌어올려 붙인다
    # (고정 위치(H-250)만 쓰면 그 사이가 텅 비어 보였음, 2026-09-18) — 반대로
    # cta_speech가 길어 텍스트가 H-250 근처까지 내려오면 겹치지 않도록 H-250을
    # 넘어서까지 끌어올리지는 않는다(하단 여백선 역할).
    bx, by = (W - btn_w) // 2, min(center_y + 70, H - 250)
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
    build_cta_card(price, cta_speech, product_image_path).convert("RGB").save(out_dir / "thread_card3.png")
    return [out_dir / "thread_card1.png", out_dir / "thread_card2.png", out_dir / "thread_card3.png"]
