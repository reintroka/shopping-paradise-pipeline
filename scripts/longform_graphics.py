"""쇼핑의천국 롱폼(3일치 다이제스트) 전용 카드: 인트로 / 챕터 디바이더 / 딥다이브
전환 / 딥다이브 강조자막 / 아웃트로.

2026-09-01 v2: 최초 버전은 숏츠와 같은 세로(1080x1920) 캔버스를 그대로 재사용했는데,
사용자가 실제 렌더링본을 보고 "롱폼인데 숏폼(세로)으로 만들면 어떡하나"고 지적 —
"롱폼"은 가로(1920x1080) 형태여야 자연스럽다는 뜻. 카드는 가로 전용으로 새로
설계하고(LW,LH=1920,1080 — 숏츠가 쓰는 build_graphics.W,H=1080,1920과는 별개 상수),
세로로 촬영된 원본 숏츠 클립은 블러 배경+가운데 배치(필러박스)로 가로 캔버스 안에
자연스럽게 앉힌다(pillarbox_filter_complex, compile_longform.py에서 클립/딥다이브
배경 양쪽에 재사용).

새 화풍을 만들지 않고 build_graphics.py의 골드 럭셔리 팔레트·폰트·로고/타이틀블록/
스텝뱃지 생성 함수는 그대로 재사용해 숏츠와 시각적으로 통일한다 — 다만 배경(글로우+
파티클+비네트)은 세로 전용 치수(W,H)가 하드코딩돼있어 그대로 재사용할 수 없어 가로
치수에 맞게 새로 인라인 구현했다(_landscape_canvas).
"""
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import build_graphics as bg

LW, LH = 1920, 1080  # 롱폼 전용 가로 캔버스
CREAM, GOLD, GOLD_DEEP, GOLD_LIGHT, CHARCOAL = bg.CREAM, bg.GOLD, bg.GOLD_DEEP, bg.GOLD_LIGHT, bg.CHARCOAL
EMPHASIS_GOLD = (255, 214, 140, 255)  # 딥다이브 자막 강조색 (cta_button 글로우와 동일 톤)
GOLD_HEX = "0xA87C3A"  # ffmpeg drawbox용 — GOLD=(168,124,58)의 16진 표기

# 세로 원본(1080x1920, 9:16)을 가로 캔버스 안에 앉힐 때의 전경(필러박스) 치수
PILLARBOX_FG_H = 1000
PILLARBOX_FG_W = 562  # round(1000 * 1080/1920) → libx264용 짝수로 반올림
PILLARBOX_FG_X = (LW - PILLARBOX_FG_W) // 2
PILLARBOX_FG_Y = (LH - PILLARBOX_FG_H) // 2


def pillarbox_filter_complex(border: bool = True) -> str:
    """세로 소스([0:v], 비디오/스틸이미지 공용)를 가로 캔버스에 블러 배경+가운데
    배치(필러박스)+골드 테두리로 합성하는 ffmpeg filter_complex 조각. compile_longform.py가
    원본 숏츠 클립 pillarbox와 딥다이브 배경 스틸 pillarbox 양쪽에 그대로 재사용한다."""
    parts = [
        f"[0:v]scale={LW}:{LH}:force_original_aspect_ratio=increase,crop={LW}:{LH},"
        f"gblur=sigma=25,eq=brightness=-0.08[bg];",
        f"[0:v]scale={PILLARBOX_FG_W}:{PILLARBOX_FG_H}[fg];",
        f"[bg][fg]overlay={PILLARBOX_FG_X}:{PILLARBOX_FG_Y}[comp];",
    ]
    if border:
        parts.append(
            f"[comp]drawbox=x={PILLARBOX_FG_X - 4}:y={PILLARBOX_FG_Y - 4}:"
            f"w={PILLARBOX_FG_W + 8}:h={PILLARBOX_FG_H + 8}:color={GOLD_HEX}:t=4[vout]"
        )
    else:
        parts.append("[comp]copy[vout]")
    return "".join(parts)


def _landscape_canvas(seed: int) -> Image.Image:
    """가로형(1920x1080) 골드 럭셔리 배경 — build_graphics.build_bg/build_vignette의
    글로우+파티클+실선+비네트 로직을 가로 치수에 맞게 인라인 재현(파일 I/O 없이 바로
    메모리에서 합성, 그 함수들은 세로 치수가 하드코딩돼있어 그대로 재사용 불가)."""
    random.seed(seed)
    canvas = Image.new("RGBA", (LW, LH), CREAM)

    glow = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [LW / 2 - 620, LH / 2 - 320, LW / 2 + 620, LH / 2 + 320], fill=(255, 244, 214, 90),
    )
    canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(160)))

    particles = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))
    pd = ImageDraw.Draw(particles)
    for _ in range(70):
        x, y = random.randint(0, LW), random.randint(0, LH)
        r = random.uniform(1.2, 2.6)
        pd.ellipse([x - r, y - r, x + r, y + r], fill=(*GOLD_LIGHT[:3], random.randint(30, 80)))
    canvas = Image.alpha_composite(canvas, particles.filter(ImageFilter.GaussianBlur(0.5)))

    d = ImageDraw.Draw(canvas)
    d.line([(90, 90), (LW - 90, 90)], fill=(*GOLD[:3], 90), width=2)
    d.line([(90, LH - 90), (LW - 90, LH - 90)], fill=(*GOLD[:3], 90), width=2)

    mask = Image.new("L", (LW, LH), 0)
    ImageDraw.Draw(mask).ellipse([-260, -260, LW + 260, LH + 260], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(160))
    inv = Image.eval(mask, lambda v: 255 - v).point(lambda v: int(v * 0.55))
    vignette = Image.new("RGBA", (LW, LH), (8, 6, 4, 255))
    vignette.putalpha(inv)
    canvas = Image.alpha_composite(canvas, vignette)
    return canvas


def _place_logo_landscape(canvas: Image.Image, out_dir: Path, target_w: int = 300, top: int = 60) -> int:
    bg.build_logo_xl(out_dir)
    logo = Image.open(out_dir / "logo_xl.png").convert("RGBA")
    scale = target_w / logo.width
    logo_s = logo.resize((target_w, max(1, int(logo.height * scale))), Image.LANCZOS)
    canvas.alpha_composite(logo_s, ((LW - logo_s.width) // 2, top))
    return top + logo_s.height


def _gold_headline_line(text: str, font, tracking: int = 0) -> Image.Image:
    """build_graphics.build_title_block의 이름 그라데이션(밝은 크림→딥골드) + 그림자 +
    상단 하이라이트 기법을 임의 한 줄 텍스트에 재사용 가능하게 일반화한 것(박스 테두리/
    가격줄은 뺌). 인트로/아웃트로 카드가 지금까지 플랫 CHARCOAL 단색 텍스트만 쓰고
    있었는데, 디바이더 카드(build_title_block)와 같은 톤의 고급스러운 헤드라인으로
    맞춰서 카드 간 퀄리티 격차를 없앤다. 2026-09-01 사용자 지적: "인트로 카드섹션
    디자인도 좀 고퀄리티로"."""
    tmp = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(tmp)
    tw = int(bg.tracked_width(text, font, tracking)) + 24
    th = font.size + 44
    layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    bg.draw_tracked(ImageDraw.Draw(shadow), (12, 16), text, font, (30, 20, 8, 130), tracking)
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4)))

    base = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    bg.draw_tracked(ImageDraw.Draw(base), (12, 12), text, font, (96, 66, 24, 255), tracking,
                     stroke_width=2, stroke_fill=(96, 66, 24, 255))
    layer.alpha_composite(base)

    mask = Image.new("L", (tw, th), 0)
    bg.draw_tracked(ImageDraw.Draw(mask), (12, 12), text, font, 255, tracking)

    stops = [
        (0.0, (250, 232, 176)),
        (0.35, (214, 168, 92)),
        (0.55, (178, 130, 46)),
        (0.75, (222, 182, 108)),
        (1.0, (168, 124, 58)),
    ]
    arr = np.zeros((th, tw, 3), dtype=np.uint8)
    for yy in range(th):
        t = yy / th
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                fr = (t - t0) / (t1 - t0) if t1 > t0 else 0
                arr[yy, :, :] = tuple(int(c0[k] + (c1[k] - c0[k]) * fr) for k in range(3))
                break
    grad = Image.fromarray(arr, "RGB").convert("RGBA")
    layer.alpha_composite(Image.composite(grad, Image.new("RGBA", (tw, th), (0, 0, 0, 0)), mask))

    highlight = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    bg.draw_tracked(ImageDraw.Draw(highlight), (12, 11), text, font, (255, 250, 225, 90), tracking)
    hmask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(hmask).rectangle([0, 0, tw, th // 2], fill=255)
    layer.alpha_composite(Image.composite(highlight, Image.new("RGBA", (tw, th), (0, 0, 0, 0)), hmask))

    return layer


def build_intro_card(out_dir: Path, vol: int, count: int) -> Path:
    """2026-09-01 재설계: 기존엔 로고부터 아래로 순서대로 쌓기만 해서 콘텐츠가 위쪽에
    쏠리고 캔버스 하단이 텅 비어 보였다(사용자 지적: "위로 치우쳐 있나.. 가운데
    위치해야지"). 모든 블록의 높이를 먼저 계산해 전체 높이를 구한 뒤, 캔버스(1080px)
    안에서 세로로 정확히 중앙에 오도록 시작 y를 역산한다. 타이틀도 플랫 텍스트 대신
    골드 그라데이션 헤드라인(_gold_headline_line)으로 격상."""
    canvas = _landscape_canvas(seed=vol * 13 + 1)
    d = ImageDraw.Draw(canvas)

    bg.build_logo_xl(out_dir)
    logo = Image.open(out_dir / "logo_xl.png").convert("RGBA")
    logo_w = 300
    logo_s = logo.resize((logo_w, max(1, int(logo.height * logo_w / logo.width))), Image.LANCZOS)

    f_eyebrow = bg.sfont(28, "Medium")
    f_title = bg.sfont(60, "Bold")
    f_sub = bg.sfont(26, "Regular")

    eyebrow = f"VOL.{vol}"
    title_lines = ["이번 주 인기템", f"모음 · 아이템 {count}개"]
    sub = "쇼핑의천국이 엄선한 오늘의 추천템, 한 번에 몰아보기"

    headlines = [_gold_headline_line(line, f_title, tracking=2) for line in title_lines]

    GAP_LOGO_EYEBROW = 30
    EYEBROW_H = 40
    GAP_EYEBROW_TITLE = 18
    GAP_TITLE_LINES = -14  # 그라데이션 헤드라인 레이어 자체 여백(th=font+44)을 보정
    GAP_TITLE_SUB = 26
    SUB_H = 34
    GAP_SUB_DIVIDER = 38

    total_h = (
        logo_s.height + GAP_LOGO_EYEBROW + EYEBROW_H + GAP_EYEBROW_TITLE
        + sum(h.height for h in headlines) + GAP_TITLE_LINES * (len(headlines) - 1)
        + GAP_TITLE_SUB + SUB_H + GAP_SUB_DIVIDER + 2
    )
    y = (LH - total_h) // 2

    canvas.alpha_composite(logo_s, ((LW - logo_s.width) // 2, y))
    y += logo_s.height + GAP_LOGO_EYEBROW

    ew = bg.tracked_width(eyebrow, f_eyebrow, 8)
    bg.draw_tracked(d, ((LW - ew) / 2, y), eyebrow, f_eyebrow, GOLD_DEEP, 8)
    tick_y = y + 14
    d.regular_polygon((LW / 2 - ew / 2 - 26, tick_y, 5), n_sides=4, rotation=45, fill=(*GOLD[:3], 220))
    d.regular_polygon((LW / 2 + ew / 2 + 26, tick_y, 5), n_sides=4, rotation=45, fill=(*GOLD[:3], 220))
    y += EYEBROW_H + GAP_EYEBROW_TITLE

    for headline in headlines:
        canvas.alpha_composite(headline, ((LW - headline.width) // 2, y))
        y += headline.height + GAP_TITLE_LINES
    y += GAP_TITLE_SUB

    sw = d.textlength(sub, font=f_sub)
    d.text(((LW - sw) / 2, y), sub, font=f_sub, fill=GOLD_DEEP)
    y += SUB_H + GAP_SUB_DIVIDER

    d.line([(LW / 2 - 220, y), (LW / 2 + 220, y)], fill=(*GOLD[:3], 200), width=2)
    d.regular_polygon((LW / 2, y, 6), n_sides=4, rotation=45, fill=GOLD)

    out_path = out_dir / "intro_card.png"
    canvas.convert("RGB").save(out_path)
    return out_path


def build_chapter_divider(out_dir: Path, idx: int, total: int, product_name: str, price_text: str) -> Path:
    canvas = _landscape_canvas(seed=idx * 29 + 3)

    bg.build_step_badge(out_dir, idx, size=150)
    badge = Image.open(out_dir / f"step_badge{idx}.png").convert("RGBA")
    badge_top = 100
    canvas.alpha_composite(badge, ((LW - badge.width) // 2, badge_top))

    bg.build_title_block(out_dir, product_name, price_text)
    title = Image.open(out_dir / "title_block.png").convert("RGBA")
    title_top = badge_top + badge.height + 20
    canvas.alpha_composite(title, ((LW - title.width) // 2, title_top))

    d = ImageDraw.Draw(canvas)
    f_eyebrow = bg.sfont(26, "Medium")
    eyebrow = f"ITEM {idx} / {total}"
    ew = bg.tracked_width(eyebrow, f_eyebrow, 6)
    y = title_top + title.height + 10
    bg.draw_tracked(d, ((LW - ew) / 2, y), eyebrow, f_eyebrow, GOLD_DEEP, 6)

    out_path = out_dir / f"divider_{idx}.png"
    canvas.convert("RGB").save(out_path)
    return out_path


def build_deepdive_transition(out_dir: Path, idx: int) -> Path:
    canvas = _landscape_canvas(seed=idx * 41 + 5)
    d = ImageDraw.Draw(canvas)
    f = bg.sfont(52, "Bold")
    lines = ["한 걸음 더", "깊이 살펴볼까요?"]
    line_h = 70
    y = (LH - len(lines) * line_h) // 2
    for line in lines:
        lw = d.textlength(line, font=f)
        d.text(((LW - lw) / 2, y), line, font=f, fill=CHARCOAL)
        y += line_h
    out_path = out_dir / f"deepdive_transition_{idx}.png"
    canvas.convert("RGB").save(out_path)
    return out_path


def build_outro_card(out_dir: Path) -> Path:
    """인트로와 동일하게 세로 중앙정렬 + 골드 그라데이션 헤드라인으로 재설계."""
    canvas = _landscape_canvas(seed=97)
    d = ImageDraw.Draw(canvas)

    bg.build_logo_xl(out_dir)
    logo = Image.open(out_dir / "logo_xl.png").convert("RGBA")
    logo_w = 280
    logo_s = logo.resize((logo_w, max(1, int(logo.height * logo_w / logo.width))), Image.LANCZOS)

    f_title = bg.sfont(50, "Bold")
    f_sub = bg.sfont(26, "Regular")
    title_lines = ["오늘 소개한 아이템들,", "프로필 링크에서 만나보세요"]
    sub = "다음 다이제스트도 놓치지 마세요 · 구독하고 알림 켜기"

    headlines = [_gold_headline_line(line, f_title, tracking=1) for line in title_lines]

    GAP_LOGO_TITLE = 44
    GAP_TITLE_LINES = -10
    GAP_TITLE_SUB = 30
    SUB_H = 34

    total_h = (
        logo_s.height + GAP_LOGO_TITLE
        + sum(h.height for h in headlines) + GAP_TITLE_LINES * (len(headlines) - 1)
        + GAP_TITLE_SUB + SUB_H
    )
    y = (LH - total_h) // 2

    canvas.alpha_composite(logo_s, ((LW - logo_s.width) // 2, y))
    y += logo_s.height + GAP_LOGO_TITLE

    for headline in headlines:
        canvas.alpha_composite(headline, ((LW - headline.width) // 2, y))
        y += headline.height + GAP_TITLE_LINES
    y += GAP_TITLE_SUB

    sw = d.textlength(sub, font=f_sub)
    d.text(((LW - sw) / 2, y), sub, font=f_sub, fill=GOLD_DEEP)

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


def split_narration_pages(text: str, max_chars: int = 42) -> list:
    """딥다이브 나레이션(20~30초, 110~160자)을 문장 단위로 쪼개 화면 전환용 페이지
    목록을 만든다. 2026-09-01 사용자 지적: "긴 대사를 한 화면으로 보여주나" — 기존엔
    나레이션 전체를 캡션 이미지 1장으로 만들어 처음부터 끝까지 고정 표시했다. 문장
    종결 어미(다/요/죠 + .!?) 기준으로 나누고, 문장 하나가 너무 길면 쉼표 기준으로 더
    쪼개고, 너무 짧은 문장은 다음 문장과 합쳐 자연스러운 길이의 페이지로 만든다."""
    import re
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if not sentences:
        return [text.strip()] if text.strip() else [""]

    expanded = []
    for s in sentences:
        if len(s) <= max_chars:
            expanded.append(s)
            continue
        parts, buf = s.split(", "), ""
        for p in parts:
            trial = f"{buf}, {p}" if buf else p
            if len(trial) <= max_chars or not buf:
                buf = trial
            else:
                expanded.append(buf)
                buf = p
        if buf:
            expanded.append(buf)

    pages, buf = [], ""
    for s in expanded:
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= max_chars:
            buf = f"{buf} {s}"
        else:
            pages.append(buf)
            buf = s
    if buf:
        pages.append(buf)
    return pages


def allocate_page_durations(pages: list, total_duration: float, min_dur: float = 1.6) -> list:
    """페이지별 표시 시간을 글자 수 비례로 배분(단어 단위 STT 정렬이 없으므로 문자 수를
    근사 지표로 사용) — 합이 정확히 total_duration이 되도록 마지막에 정규화한다."""
    total_chars = sum(len(p) for p in pages) or 1
    raw = [max(min_dur, total_duration * len(p) / total_chars) for p in pages]
    scale = total_duration / sum(raw) if sum(raw) > 0 else 1.0
    return [d * scale for d in raw]


def build_deepdive_caption(out_dir: Path, idx, text: str, emphasis_words: list,
                            max_width: int = 1500, font_size: int = 42, min_font_size: int = 28,
                            max_lines: int = 2) -> Path:
    """딥다이브 나레이션 자막 — 강조단어만 골드 하이라이트색+살짝 크게 (다른 채널들의
    한줄 강조자막 패턴과 같은 정신, 이 채널의 캡션 pill 스타일로 재현). 가로 캔버스라
    세로판보다 폭을 넉넉히 쓰고 줄 수는 2줄로 줄임."""
    tmp = Image.new("RGBA", (10, 10))
    d0 = ImageDraw.Draw(tmp)
    inner_w = max_width - 70

    # 2026-09-01: emphasis_words는 Gemini가 "짧은 구"로 뽑아주기 때문에("저소음 모터"처럼
    # 공백 포함) 원래 코드(ew in word, 자막은 공백 기준으로 단어 분리됨)로는 절대 매치가
    # 안 돼 하이라이트가 항상 죽어있었다 — 구를 개별 단어로 쪼갠 토큰 집합으로 비교.
    emphasis_tokens = {tok for ew in emphasis_words if ew for tok in ew.split(" ") if tok}

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
            is_em = any(tok in word for tok in emphasis_tokens)
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
