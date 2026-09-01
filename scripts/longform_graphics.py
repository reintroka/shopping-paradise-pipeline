"""쇼핑의천국 롱폼(3일치 다이제스트) 전용 카드: 인트로 / 챕터 디바이더 / 딥다이브
전환 / 딥다이브 강조자막 / 아웃트로.

새 화풍을 만들지 않고 build_graphics.py의 골드 럭셔리 팔레트·폰트·배경/비네트/
로고/타이틀블록/스텝뱃지 생성 함수를 그대로 재사용해 숏츠와 시각적으로 통일한다
(2026-09-01, 다른 13개 채널의 리캡 롱폼 카드 패턴을 이 채널에 이식).
"""
from pathlib import Path

from PIL import Image, ImageDraw

import build_graphics as bg

W, H = bg.W, bg.H
CREAM, GOLD, GOLD_DEEP, GOLD_LIGHT, CHARCOAL = bg.CREAM, bg.GOLD, bg.GOLD_DEEP, bg.GOLD_LIGHT, bg.CHARCOAL
EMPHASIS_GOLD = (255, 214, 140, 255)  # cta_button.py 글로우와 동일 톤 — 딥다이브 자막 강조색


def _base_canvas(out_dir: Path, seed: int) -> Image.Image:
    bg.build_bg(out_dir, seed=seed)
    bg.build_vignette(out_dir)
    base = Image.open(out_dir / "bg_bright.png").convert("RGBA")
    vign = Image.open(out_dir / "vignette.png").convert("RGBA")
    return Image.alpha_composite(base, vign)


def build_intro_card(out_dir: Path, vol: int, count: int) -> Path:
    canvas = _base_canvas(out_dir, seed=vol * 13 + 1)
    bg.build_logo_xl(out_dir)
    logo = Image.open(out_dir / "logo_xl.png").convert("RGBA")
    canvas.alpha_composite(logo, ((W - logo.width) // 2, 300))

    d = ImageDraw.Draw(canvas)
    f_eyebrow = bg.sfont(34, "Medium")
    eyebrow = f"VOL.{vol}"
    ew = bg.tracked_width(eyebrow, f_eyebrow, 8)
    bg.draw_tracked(d, ((W - ew) / 2, 620), eyebrow, f_eyebrow, GOLD_DEEP, 8)

    f_title = bg.sfont(72, "Bold")
    lines = ["이번 주 인기템", f"모음 · 아이템 {count}개"]
    y = 700
    for line in lines:
        lw = d.textlength(line, font=f_title)
        d.text(((W - lw) / 2, y), line, font=f_title, fill=CHARCOAL)
        y += 96

    f_sub = bg.sfont(30, "Regular")
    sub = "쇼핑의천국이 엄선한 오늘의 추천템, 한 번에 몰아보기"
    sw = d.textlength(sub, font=f_sub)
    d.text(((W - sw) / 2, y + 30), sub, font=f_sub, fill=GOLD_DEEP)
    d.line([(W / 2 - 220, y + 100), (W / 2 + 220, y + 100)], fill=(*GOLD[:3], 200), width=2)

    out_path = out_dir / "intro_card.png"
    canvas.convert("RGB").save(out_path)
    return out_path


def build_chapter_divider(out_dir: Path, idx: int, total: int, product_name: str, price_text: str) -> Path:
    canvas = _base_canvas(out_dir, seed=idx * 29 + 3)

    bg.build_step_badge(out_dir, idx, size=200)
    badge = Image.open(out_dir / f"step_badge{idx}.png").convert("RGBA")
    canvas.alpha_composite(badge, ((W - badge.width) // 2, 470))

    bg.build_title_block(out_dir, product_name, price_text)
    title = Image.open(out_dir / "title_block.png").convert("RGBA")
    canvas.alpha_composite(title, ((W - title.width) // 2, 760))

    d = ImageDraw.Draw(canvas)
    f_eyebrow = bg.sfont(30, "Medium")
    eyebrow = f"ITEM {idx} / {total}"
    ew = bg.tracked_width(eyebrow, f_eyebrow, 6)
    bg.draw_tracked(d, ((W - ew) / 2, 1000), eyebrow, f_eyebrow, GOLD_DEEP, 6)

    out_path = out_dir / f"divider_{idx}.png"
    canvas.convert("RGB").save(out_path)
    return out_path


def build_deepdive_transition(out_dir: Path, idx: int) -> Path:
    canvas = _base_canvas(out_dir, seed=idx * 41 + 5)
    d = ImageDraw.Draw(canvas)
    f = bg.sfont(56, "Bold")
    lines = ["한 걸음 더", "깊이 살펴볼까요?"]
    y = 820
    for line in lines:
        lw = d.textlength(line, font=f)
        d.text(((W - lw) / 2, y), line, font=f, fill=CHARCOAL)
        y += 76
    out_path = out_dir / f"deepdive_transition_{idx}.png"
    canvas.convert("RGB").save(out_path)
    return out_path


def build_outro_card(out_dir: Path) -> Path:
    canvas = _base_canvas(out_dir, seed=97)
    bg.build_logo_xl(out_dir)
    logo = Image.open(out_dir / "logo_xl.png").convert("RGBA")
    canvas.alpha_composite(logo, ((W - logo.width) // 2, 560))

    d = ImageDraw.Draw(canvas)
    f_title = bg.sfont(58, "Bold")
    lines = ["오늘 소개한 아이템들,", "프로필 링크에서 만나보세요"]
    y = 860
    for line in lines:
        lw = d.textlength(line, font=f_title)
        d.text(((W - lw) / 2, y), line, font=f_title, fill=CHARCOAL)
        y += 78

    f_sub = bg.sfont(30, "Regular")
    sub = "다음 다이제스트도 놓치지 마세요 · 구독하고 알림 켜기"
    sw = d.textlength(sub, font=f_sub)
    d.text(((W - sw) / 2, y + 40), sub, font=f_sub, fill=GOLD_DEEP)

    out_path = out_dir / "outro_card.png"
    canvas.convert("RGB").save(out_path)
    return out_path


def _wrap_lines(text, font, draw, max_w):
    words = text.split(" ")
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def build_deepdive_caption(out_dir: Path, idx: int, text: str, emphasis_words: list,
                            max_width: int = 940, font_size: int = 40, min_font_size: int = 26,
                            max_lines: int = 3) -> Path:
    """딥다이브 나레이션 자막 — 강조단어만 골드 하이라이트색+살짝 크게 (다른 채널들의
    한줄 강조자막 패턴과 같은 정신, 이 채널의 캡션 pill 스타일로 재현)."""
    tmp = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(tmp)
    inner_w = max_width - 70

    size = font_size
    f = bg.sfont(size, "SemiBold")
    lines = _wrap_lines(text, f, d0, inner_w)
    while len(lines) > max_lines and size > min_font_size:
        size -= 2
        f = bg.sfont(size, "SemiBold")
        lines = _wrap_lines(text, f, d0, inner_w)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1:])]

    line_h = int(size * 1.35)
    pad = 26
    h = line_h * len(lines) + pad * 2
    w = max_width
    pill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=22, fill=(18, 14, 10, 190))
    d.rounded_rectangle([0, 0, w - 1, 3], radius=0, fill=(*GOLD_LIGHT[:3], 210))

    f_em = bg.sfont(size + 4, "Bold")
    for i, line in enumerate(lines):
        y = pad + i * line_h
        parts = []
        total_w = 0.0
        for word in line.split(" "):
            is_em = any(ew and ew in word for ew in emphasis_words)
            wf = f_em if is_em else f
            ww = d0.textlength(word + " ", font=wf)
            parts.append((word, wf, is_em))
            total_w += ww
        x = (w - total_w) / 2
        for word, wf, is_em in parts:
            color = EMPHASIS_GOLD if is_em else (250, 246, 238, 255)
            yy = y + (line_h - size) / 2 - (4 if is_em else 0)
            d.text((x, yy), word, font=wf, fill=color)
            x += d0.textlength(word + " ", font=wf)

    out_path = out_dir / f"deepdive_caption_{idx}.png"
    pill.save(out_path)
    return out_path
