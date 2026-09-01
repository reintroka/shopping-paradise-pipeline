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


def build_intro_card(out_dir: Path, vol: int, count: int) -> Path:
    canvas = _landscape_canvas(seed=vol * 13 + 1)
    y = _place_logo_landscape(canvas, out_dir, target_w=300, top=60) + 24

    d = ImageDraw.Draw(canvas)
    f_eyebrow = bg.sfont(28, "Medium")
    eyebrow = f"VOL.{vol}"
    ew = bg.tracked_width(eyebrow, f_eyebrow, 8)
    bg.draw_tracked(d, ((LW - ew) / 2, y), eyebrow, f_eyebrow, GOLD_DEEP, 8)
    y += 50

    f_title = bg.sfont(58, "Bold")
    for line in ["이번 주 인기템", f"모음 · 아이템 {count}개"]:
        lw = d.textlength(line, font=f_title)
        d.text(((LW - lw) / 2, y), line, font=f_title, fill=CHARCOAL)
        y += 76
    y += 10

    f_sub = bg.sfont(26, "Regular")
    sub = "쇼핑의천국이 엄선한 오늘의 추천템, 한 번에 몰아보기"
    sw = d.textlength(sub, font=f_sub)
    d.text(((LW - sw) / 2, y), sub, font=f_sub, fill=GOLD_DEEP)
    y += 46
    d.line([(LW / 2 - 220, y), (LW / 2 + 220, y)], fill=(*GOLD[:3], 200), width=2)

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
    canvas = _landscape_canvas(seed=97)
    y = _place_logo_landscape(canvas, out_dir, target_w=280, top=130) + 40

    d = ImageDraw.Draw(canvas)
    f_title = bg.sfont(50, "Bold")
    for line in ["오늘 소개한 아이템들,", "프로필 링크에서 만나보세요"]:
        lw = d.textlength(line, font=f_title)
        d.text(((LW - lw) / 2, y), line, font=f_title, fill=CHARCOAL)
        y += 68
    y += 20

    f_sub = bg.sfont(26, "Regular")
    sub = "다음 다이제스트도 놓치지 마세요 · 구독하고 알림 켜기"
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


def build_deepdive_caption(out_dir: Path, idx: int, text: str, emphasis_words: list,
                            max_width: int = 1500, font_size: int = 42, min_font_size: int = 28,
                            max_lines: int = 2) -> Path:
    """딥다이브 나레이션 자막 — 강조단어만 골드 하이라이트색+살짝 크게 (다른 채널들의
    한줄 강조자막 패턴과 같은 정신, 이 채널의 캡션 pill 스타일로 재현). 가로 캔버스라
    세로판보다 폭을 넉넉히 쓰고 줄 수는 2줄로 줄임."""
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
