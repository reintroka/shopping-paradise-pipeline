"""쇼츠 화면을 '정지 상품 사진' 대신 '실제 사용 장면' 스톡 영상으로 채운다 (2026-10-06 도입).

배경: 최근 쇼츠 조회수 중간값이 약 70회 — 베이지 배경에 상품 사진이 15초 동안 멈춰 있어서
첫 1~2초에 넘겨지는 것으로 판단. 사용자가 시안(_실험/쇼핑_CC/compose.py)을 보고 도입을 결정.
연예인·리뷰어 CC 영상은 초상권·표시광고 문제로 쓰지 않고, 사람/브랜드가 두드러지지 않는
Pexels 스톡 영상(상업 이용 무료, 출처 표기 불필요)만 쓴다.

흐름:
  prepare()  — Gemini가 장면 검색어를 정하고 → Pexels 세로 영상 검색 → 제목(slug) 금칙어 거르기
               → Gemini가 후보 썸네일을 직접 보고 맞는 장면 하나를 고르거나 전부 반려
               (시안 때 에어프라이어에 기름 튀김기, 차량 청소에 BMW 로고, 바디슈트 차림이 섞여
               나와 사람이 손으로 뺐던 문제를 자동화) → 다운로드 → work_dir/usage_broll.json.
  render_hook() / render_middle() — assemble_video.py가 usage_broll.json이 있을 때만 부른다.
어느 단계든 실패하면 usage_broll.json을 만들지 않거나 assemble_video가 예외를 잡아 기존 화면
(정지 상품 사진)으로 돌아가므로 발행 자체는 막히지 않는다.

필요한 환경변수: PEXELS_API_KEY, GEMINI_API_KEY (없으면 기존 화면).
"""
import base64
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE.parent / "assets" / "fonts"
W, H, FPS = 1080, 1920, 25
GOLD = (240, 196, 98)
CREAM = (255, 248, 236)
INK = (22, 18, 16)
UA = {"User-Agent": "Mozilla/5.0"}
INFO_NAME = "usage_broll.json"
GEMINI_MODEL = "gemini-flash-lite-latest"
# 영상 제목(slug)에 이런 말이 있으면 썸네일을 보기도 전에 뺀다(Gemini 판정의 1차 안전망).
BLOCK = re.compile(r"bikini|lingerie|bodysuit|underwear|swimsuit|swimwear|\bbra\b|sexy|nude|naked|topless|shirtless|"
                   r"cigarette|smok|vape|blood|weapon|gun|logo|brand", re.I)
# 상품 카드·패널·PiP 위치(시안과 같은 배치).
CLIP_H = 1250
CARD_Y = 760
PIP_W, PIP_H, PIP_X, PIP_Y = 340, 604, W - 340 - 56, 1170
RANK_ANCHOR = (930, 150)


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / f"Pretendard-{weight}.otf"), size)


def _get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _gemini(parts: list) -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
           f"?key={os.environ['GEMINI_API_KEY']}")
    body = json.dumps({"contents": [{"parts": parts}],
                       "generationConfig": {"responseMimeType": "application/json"}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:  # noqa: BLE001 — 일시 오류(503 등)는 재시도
            last = e
    raise RuntimeError(f"Gemini 실패: {last}")


def _queries(product_name: str, keyword: str, specs: list, hook: str) -> dict:
    prompt = f"""You pick stock-video search queries for a Korean shopping short (vertical video).
Product: {product_name}
Category keyword: {keyword}
Hook line (Korean): {hook}
Feature beats (Korean title / body):
1. {specs[0][0]} / {specs[0][1]}
2. {specs[1][0]} / {specs[1][1]}
3. {specs[2][0]} / {specs[2][1]}

For the hook and for each beat, give 2 alternative English Pexels search queries (2-4 words each) that find a
REAL-LIFE USAGE SCENE of this kind of product or the everyday situation it solves (e.g. "washing hair shower",
"cooking pasta pan", "packing lunch containers"). Rules: no brand names, no celebrities, no text/graphics,
the product type must match exactly (an air fryer is not a deep fryer). Prefer hands/close-ups over faces.
Return JSON only: {{"hook": ["", ""], "beats": [["", ""], ["", ""], ["", ""]]}}"""
    data = json.loads(_gemini([{"text": prompt}]))
    return {"hook": list(data["hook"])[:2], "beats": [list(b)[:2] for b in data["beats"]][:3]}


def _pick_file(video: dict) -> str | None:
    files = [f for f in video.get("video_files", []) if f.get("width") and f.get("height")
             and f["height"] > f["width"] and f["width"] >= 720 and f.get("file_type") == "video/mp4"]
    if not files:
        return None
    files.sort(key=lambda f: (abs(f["width"] - 1080), f["width"]))
    return files[0]["link"]


def _candidates(query: str, used: set) -> list:
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "portrait", "size": "medium", "per_page": 12})
    data = json.loads(_get(url, {"Authorization": os.environ["PEXELS_API_KEY"]}))
    out = []
    for v in data.get("videos", []):
        if v["id"] in used or v.get("duration", 0) < 5 or BLOCK.search(v.get("url", "")):
            continue
        link = _pick_file(v)
        if link and v.get("image"):
            out.append({"id": v["id"], "link": link, "image": v["image"], "url": v["url"], "duration": v["duration"]})
        if len(out) == 6:
            break
    return out


def _vision_pick(cands: list, scene: str, product_name: str) -> int:
    """후보 썸네일을 Gemini에게 직접 보여 주고 맞는 장면 하나의 번호(없으면 -1)를 받는다."""
    parts = [{"text": f"""These are {len(cands)} thumbnails (index 0..{len(cands) - 1}) of stock videos for a Korean
shopping short that sells: {product_name}. Wanted scene: "{scene}".
Pick the ONE thumbnail that best shows that scene and fits an ad for this exact product type.
Reject any thumbnail that shows: a clearly different kind of product, a visible brand logo or readable brand name,
revealing clothing (swimwear, underwear, bodysuit), alcohol or smoking, a child as the main subject, text overlays.
Return JSON only: {{"pick": <index or -1>, "why": "<short reason>"}}"""}]
    for c in cands:
        try:
            img = _get(c["image"] + ("&" if "?" in c["image"] else "?") + "auto=compress&w=360")
        except Exception:  # noqa: BLE001 — 썸네일 하나 실패는 빈 칸으로
            img = b""
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})
    data = json.loads(_gemini(parts))
    pick = int(data.get("pick", -1))
    print(f"[usage_broll] '{scene}' 후보 {len(cands)}개 → {pick} ({data.get('why', '')})")
    return pick if 0 <= pick < len(cands) else -1


def _find_clip(queries: list, product_name: str, used: set, out: Path) -> dict | None:
    for q in queries:
        try:
            cands = _candidates(q, used)
            if not cands:
                continue
            k = _vision_pick(cands, q, product_name)
            if k < 0:
                continue
            c = cands[k]
            for _ in range(3):
                try:
                    out.write_bytes(_get(c["link"], timeout=120))
                    break
                except Exception:  # noqa: BLE001
                    continue
            if out.exists() and out.stat().st_size > 50_000:
                used.add(c["id"])
                return {"path": out.name, "pexels": c["url"], "query": q, "duration": c["duration"]}
        except Exception as e:  # noqa: BLE001 — 검색어 하나 실패는 다음 검색어로
            print(f"[usage_broll] '{q}' 실패: {e}")
    return None


def prepare(work_dir: Path, product: dict, script_data: dict) -> tuple[bool, str]:
    """사용 장면 클립 4개(훅 + 기능 3개)를 준비한다. 서로 다른 클립이 2개 미만이면 쓰지 않는다."""
    (work_dir / INFO_NAME).unlink(missing_ok=True)
    if not os.environ.get("PEXELS_API_KEY"):
        return False, "PEXELS_API_KEY 없음 — 기존 화면"
    name = product.get("productName", "")
    specs = [(script_data[f"spec{i}_title"], script_data[f"spec{i}_body"]) for i in (1, 2, 3)]
    q = _queries(name, product.get("keyword", ""), specs, script_data.get("hook_speech", ""))
    used: set = set()
    slots = [_find_clip(q["hook"], name, used, work_dir / "broll_hook.mp4")]
    for i, qs in enumerate(q["beats"]):
        slots.append(_find_clip(qs, name, used, work_dir / f"broll_{i + 1}.mp4"))
    found = [s for s in slots if s]
    if len(found) < 2:
        return False, f"맞는 장면 {len(found)}개뿐 — 기존 화면"
    # 빈 칸은 찾은 클립을 다른 구간(뒤쪽)으로 돌려 쓴다
    for k, s in enumerate(slots):
        if not s:
            src = found[k % len(found)]
            slots[k] = {**src, "offset": min(4.0, max(0.0, src["duration"] - 6))}
    info = {
        "slots": slots,
        "name": name,
        "price": f"{product['productPrice']:,}원대",
        "hook_lines": [script_data.get("hook_title_line1", ""), script_data.get("hook_title_line2", "")],
        "specs": specs,
    }
    (work_dir / INFO_NAME).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, f"사용 장면 {len(found)}/4개 (" + ", ".join(s["query"] for s in found) + ")"


def load(work_dir: Path) -> dict | None:
    p = work_dir / INFO_NAME
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------- 그래픽

def _fit(text: str, weight: str, size: int, max_w: int, min_size: int = 30) -> ImageFont.FreeTypeFont:
    f = _font(weight, size)
    while f.getlength(text) > max_w and size > min_size:
        size -= 2
        f = _font(weight, size)
    return f


def _hook_text_png(lines: list, path: Path, y0: int = 700) -> None:
    """훅 큰 문구: 흰 글자+짙은 외곽선, 둘째 줄은 금색. 문구 뒤로 어두운 띠."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band = Image.new("L", (1, H))
    for y in range(H):
        band.putpixel((0, y), int(170 * max(0.0, 1 - abs(y - (y0 + 110)) / 430)))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    shade.putalpha(band.resize((W, H)))
    im.alpha_composite(shade)
    d = ImageDraw.Draw(im)
    lines = [ln for ln in lines if ln.strip()]
    for k, ln in enumerate(lines):
        f = _fit(ln, "Black", 118, W - 120, 60)
        col = GOLD if k == len(lines) - 1 and len(lines) > 1 else CREAM
        d.text((W / 2, y0 + k * 150), ln, font=f, fill=(*col, 255), anchor="mt", stroke_width=8, stroke_fill=(*INK, 255))
    im.save(path)


def _top_shade_png(path: Path) -> None:
    """위쪽 로고·배지가 밝은 영상 위에서도 보이도록 옅은 그라데이션."""
    im = Image.new("RGBA", (W, 300), (0, 0, 0, 255))
    g = Image.new("L", (1, 300))
    for y in range(300):
        g.putpixel((0, y), int(140 * (1 - y / 300)))
    im.putalpha(g.resize((W, 300)))
    im.save(path)


def _pip_assets(work_dir: Path) -> None:
    m = Image.new("L", (PIP_W, PIP_H), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, PIP_W - 1, PIP_H - 1], radius=36, fill=255)
    m.save(work_dir / "ub_pip_mask.png")
    fr = Image.new("RGBA", (PIP_W + 16, PIP_H + 16), (0, 0, 0, 0))
    sh = Image.new("RGBA", fr.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([4, 10, PIP_W + 12, PIP_H + 14], radius=42, fill=(0, 0, 0, 150))
    fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(fr).rounded_rectangle([0, 0, PIP_W + 15, PIP_H + 15], radius=44, fill=(*GOLD, 255))
    fr.save(work_dir / "ub_pip_frame.png")


def _product_card_png(photo: Path, name: str, price: str, path: Path) -> None:
    S, pad = 560, 40
    im = Image.new("RGBA", (S + pad * 2, S + 150 + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 18, pad + S, pad + S + 168], radius=40, fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([pad, pad, pad + S, pad + S + 150], radius=40, fill=(255, 255, 255, 255))
    ph = Image.open(photo).convert("RGB")
    ph.thumbnail((S - 60, S - 60), Image.LANCZOS)
    im.paste(ph, (pad + (S - ph.width) // 2, pad + 30 + (S - 60 - ph.height) // 2))
    d.rounded_rectangle([pad, pad + S, pad + S, pad + S + 150], radius=40, fill=(*INK, 255))
    d.rectangle([pad, pad + S, pad + S, pad + S + 40], fill=(*INK, 255))
    f = _font("Bold", 32)
    while f.getlength(name) > S - 60 and len(name) > 4:
        name = name[:-1]
    d.text((pad + S / 2, pad + S + 48), name, font=f, fill=(*CREAM, 255), anchor="mm")
    d.text((pad + S / 2, pad + S + 104), price, font=_font("Black", 44), fill=(*GOLD, 255), anchor="mm")
    im.save(path)


def _beat_panel_png(i: int, title: str, body: str, path: Path) -> None:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = Image.new("L", (1, H))
    for y in range(H):
        g.putpixel((0, y), 0 if y < 900 else int(255 * min(1.0, (y - 900) / 260)))
    bg = Image.new("RGBA", (W, H), (*INK, 255))
    bg.putalpha(g.resize((W, H)))
    im.alpha_composite(bg)
    d = ImageDraw.Draw(im)
    d.ellipse([90, 1590, 210, 1710], fill=(*GOLD, 255))
    d.text((150, 1648), f"{i + 1:02d}", font=_font("Black", 54), fill=(*INK, 255), anchor="mm")
    d.text((240, 1618), title, font=_fit(title, "Black", 82, W - 300, 44), fill=(*CREAM, 255), anchor="lm")
    d.text((242, 1700), body, font=_fit(body, "SemiBold", 44, W - 300, 28), fill=(225, 214, 196, 255), anchor="lm")
    im.save(path)


# ---------------------------------------------------------------- 렌더

def _run(cmd: list) -> None:
    print("+", " ".join(cmd[:6]), "...")
    subprocess.run(cmd, check=True)


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _header(cmd: list, lines: list, prev: str, work_dir: Path, idx: int) -> tuple[str, int]:
    """위 그라데이션 + 로고 + AI 고지 + (있으면) 검색번호 배지 펄스."""
    import assemble_video as AV
    _top_shade_png(work_dir / "ub_top.png")
    for name in ("ub_top.png", "logo_xl.png", "ai_tag.png"):
        cmd += ["-loop", "1", "-i", str(work_dir / name)]
    lines.append(f"[{prev}][{idx}:v]overlay=0:0:shortest=1[h1];")
    lines.append(f"[h1][{idx + 1}:v]overlay={AV.LOGO_XY[0]}:{AV.LOGO_XY[1]}:shortest=1[h2];")
    lines.append(f"[h2][{idx + 2}:v]overlay={AV.AI_TAG_XY[0]}:{AV.AI_TAG_XY[1]}:shortest=1[h3];")
    idx += 3
    prev = "h3"
    badge = AV._rank_badge_path(work_dir)
    if badge:
        cmd += ["-loop", "1", "-i", str(badge)]
        lines += [ln.strip() for ln in AV._rank_badge_pulse_lines(prev, idx, "h4", RANK_ANCHOR)]
        idx += 1
        prev = "h4"
    return prev, idx


def _clip_input(work_dir: Path, slot: dict) -> list:
    return ["-stream_loop", "-1", "-ss", f"{slot.get('offset', 0):.2f}", "-i", str(work_dir / slot["path"])]


def render_hook(work_dir: Path, info: dict) -> Path:
    """훅: 사용 장면이 화면 전체, 큰 훅 문구, HeyGen 아바타는 오른쪽 아래 둥근 창(목소리 그대로)."""
    _hook_text_png(info["hook_lines"], work_dir / "ub_hook_text.png")
    _pip_assets(work_dir)
    dur = _duration(work_dir / "hook.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error", *_clip_input(work_dir, info["slots"][0]), "-i", str(work_dir / "hook.mp4"),
           "-loop", "1", "-i", str(work_dir / "ub_hook_text.png"),
           "-loop", "1", "-i", str(work_dir / "ub_pip_mask.png"),
           "-loop", "1", "-i", str(work_dir / "ub_pip_frame.png")]
    lines = [
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
        f"eq=saturation=0.92:brightness=-0.04,fps={FPS},format=rgba[bg];",
        "[bg][2:v]overlay=0:0:shortest=1[a];",
        f"[1:v]scale={PIP_W}:{PIP_H}:force_original_aspect_ratio=increase,crop={PIP_W}:{PIP_H},setsar=1,fps={FPS},format=rgba[pv];",
        "[3:v]format=gray[pm];[pv][pm]alphamerge[pip];",
        f"[a][4:v]overlay={PIP_X - 8}:{PIP_Y - 8}:shortest=1[b];",
        f"[b][pip]overlay={PIP_X}:{PIP_Y}[c];",
    ]
    prev, idx = _header(cmd, lines, "c", work_dir, 5)
    lines.append(f"[{prev}]format=yuv420p[vout];")
    lines.append(f"[1:a]loudnorm=I=-14:TP=-1:LRA=11[aout]")
    fpath = work_dir / "filter_ub_hook.txt"
    fpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = work_dir / "hook_final.mp4"
    _run(cmd + ["-filter_complex_script", str(fpath), "-map", "[vout]", "-map", "[aout]", "-t", f"{dur:.3f}",
                "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", str(out)])
    return out


def render_middle(work_dir: Path, info: dict, switches: list, audio: Path) -> Path:
    """기능 3구간: 위쪽은 사용 장면(천천히 확대), 가운데 상품 카드가 튀어 오르고, 아래 단계 번호+기능
    제목. 구간마다 흰 플래시. 소리는 assemble_video가 만든 combined_audio.wav를 그대로 얹는다."""
    _product_card_png(work_dir / "product.jpg", info["name"], info["price"], work_dir / "ub_card.png")
    segs = []
    for i in range(3):
        d = switches[i + 1] - switches[i]
        title, body = info["specs"][i]
        _beat_panel_png(i, title, body, work_dir / f"ub_panel{i}.png")
        cmd = ["ffmpeg", "-y", "-v", "error", *_clip_input(work_dir, info["slots"][i + 1]),
               "-loop", "1", "-i", str(work_dir / f"ub_panel{i}.png"),
               "-loop", "1", "-i", str(work_dir / "ub_card.png")]
        lines = [
            f"[0:v]scale={W}:-2,crop={W}:{CLIP_H}:0:'max(0,(ih-{CLIP_H})/3)',"
            f"scale=w='{W}*(1+0.06*t/{d:.2f})':h=-2:eval=frame,crop={W}:{CLIP_H},setsar=1,eq=saturation=0.95,"
            f"fps={FPS},format=rgba,pad={W}:{H}:0:0:color=#161210[bg];",
            "[bg][1:v]overlay=0:0:shortest=1[a];",
            f"[a][2:v]overlay=x='(W-w)/2':y='if(lt(t,0.45),1900-(1900-{CARD_Y})*(1-pow(1-t/0.45,3)),{CARD_Y})':shortest=1[b];",
            f"color=white:s={W}x{H}:d=0.25,format=rgba,fade=t=out:st=0:d=0.25:alpha=1[fl];"
            "[b][fl]overlay=0:0:eof_action=pass[c];",
        ]
        prev, _ = _header(cmd, lines, "c", work_dir, 3)
        lines.append(f"[{prev}]format=yuv420p[vout]")
        fpath = work_dir / f"filter_ub_beat{i}.txt"
        fpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        seg = work_dir / f"ub_beat{i}.mp4"
        _run(cmd + ["-filter_complex_script", str(fpath), "-map", "[vout]", "-t", f"{d:.3f}", "-r", str(FPS),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(seg)])
        segs.append(seg)
    lst = work_dir / "ub_concat.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    out = work_dir / "middle_segment.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(audio),
          "-map", "0:v", "-map", "1:a", "-t", f"{switches[-1]:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          str(out)])
    return out
