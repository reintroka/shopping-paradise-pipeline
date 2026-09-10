# -*- coding: utf-8 -*-
"""ffmpeg으로 훅+스펙설명(3비트)+CTA를 최종 mp4로 조립 (2026-08-27 v2, 로컬 v15 이식).

전제: build_graphics.py로 만든 PNG들, heygen_gen.py로 만든 hook.mp4/cta.mp4,
google_tts.py로 만든 narration1/2/3.mp3(+.json, duration 포함)가 work_dir에 있어야 함.

v1(2026-08-26)과 차이: 나레이션을 통짜 1개→3개(스펙당 1개)로 바꾸고, 각 비트가
끝날 때마다 화면 전체 크래시줌+화이트 플래시+후시 컷 전환, 스텝배지(01/02/03),
비네트, 세이프존 확보된 자막 위치, 로고 옆 AI활용고지 태그, 펄스 CTA버튼까지
추가. 디자인 근거는 project memory `project_shoppingparadise_youtube.md` 참고.
"""
import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SFX_DIR = HERE.parent / "assets" / "sfx"

# build_graphics.py의 좌표와 정확히 일치해야 함 (product frame_w=600 고정 기준 도출값)
LOGO_XY = (40, 50)
AI_TAG_XY = (40, 210)
TITLE_XY = (90, 264)
PRODUCT_XY = (210, 470)
SHADOW_XY = (175, 1060)
REFLECTION_XY = (210, 1130)
BADGE_XY = (720, 400)
CARDS_XY_X = 104
CARDS_Y = 1204
CAPTION_X = 80
# 2026-08-27: 설명구간(카드) 자막은 완전히 제거함 — 카드에 이미 같은 문구가 적혀있어
# 중복이었고, 그 위치(옛 CAPTION_Y=1506)가 유튜브 쇼츠의 "눈앞에 있는 사물 검색"(구글
# 렌즈) 안내 배너와 겹친다는 사용자 스크린샷 제보도 있었음 — 자막을 없애서 둘 다 해결.
# 훅 구간엔 카드가 없어서 자막을 그대로 유지하되, 같은 렌즈 배너 문제를 피하려고 위로 올림.
HOOK_CAPTION_Y = 1320
# 2026-09-10: 링크 페이지 검색번호 배지. 처음엔 우상단 고정이었는데 사용자 피드백
# ("얼굴부분에서 강조하는게 안낫나, 네모를 사선으로 기울이고") — 아바타 얼굴 바로
# 옆(사람 시선이 제일 먼저 가는 자리)으로 옮기고, 사선(스티커 느낌)으로 기울임.
# hook/cta는 아바타 얼굴이 화면 중앙~오른쪽 뺨 옆 여백에 오므로 그 자리를 앵커로
# 쓰고, middle(아바타 없음)은 대신 상품사진 카드 우상단 모서리에 "가격표 스티커"처럼
# 겹치게 둔다 — 이 채널 상품소개 톤과도 더 잘 맞음. 앵커는 배지의 중심점이며, 회전 후
# 실제 폭/높이가 프레임마다(펄스로) 조금씩 바뀌므로 오버레이 x/y는 항상 동적 계산한다.
RANK_BADGE_ANCHOR_FACE = (220, 620)      # hook/cta: 아바타 얼굴 왼쪽 여백(2026-09-10, 오른쪽→왼쪽으로 이동 요청)
RANK_BADGE_ANCHOR_PRODUCT = (270, 510)   # middle: 상품 카드 좌상단 모서리(우상단은 스텝배지 01/02/03과 겹침)
RANK_BADGE_ANGLE_DEG = -10
# 2026-08-27: CTA 자막+버튼을 하단(1380/1580)에 두니 위치가 어색하다는 피드백 —
# 아바타 얼굴(대략 555~930)과 두 손 모은 제스처(대략 1200~1515) 사이, 화면
# 중앙에 가까운 빈 공간(약 930~1200)으로 옮김. hook_v2/cta_v2 원본 프레임
# 기준으로 잡은 값이라, 캐릭터/구도가 많이 다른 아바타를 쓰면 겹칠 수 있음 —
# 그때는 이 두 값을 다시 확인할 것.
CTA_CAPTION_Y = 1030
CTA_BUTTON_Y = 1140  # 자막이 1줄일 때 기준값 — 2줄이면 build_cta_segment()가 실제
# caption_cta.png 높이를 읽어서 이 밑으로 내려 겹침을 막는다(아래 참고).
CTA_CAPTION_BUTTON_GAP = 20

# 2026-08-27: 헤이젠 훅/CTA 오디오는 그대로(raw) 붙여왔는데, 나레이션(google_tts.py)에는
# loudnorm을 적용해서 세 구간(훅/설명/CTA) 볼륨이 서로 다르게 들리는 문제가 있었음.
# 나레이션 쪽과 동일한 타깃으로 훅/CTA 오디오도 정규화해서 구간 전환 시 볼륨이 안 튀게 함.
# google_tts.py의 LOUDNORM_TARGET과 반드시 같은 값으로 유지할 것.
LOUDNORM_TARGET = "loudnorm=I=-14:TP=-1:LRA=11"

LEAD_IN = 0.3
BEAT_GAP = 0.4
FLASH_DUR = 0.06
SWITCH_OFFSET = 0.03
SWITCH_EPS = 0.004
CARD_FADE = 0.15
CARD_FADEIN_LEAD = 0.16
CARD_FADEOUT_LEAD = 0.035


def run(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def _rank_badge_path(work_dir: Path) -> Path | None:
    """rank_badge.png가 있으면(=링크 페이지 등록 성공) 그 경로를, 없으면 None을 반환.
    세 세그먼트(훅/미들/CTA) 빌드 함수가 전부 이걸로 배지 오버레이 여부를 결정한다."""
    p = work_dir / "rank_badge.png"
    return p if p.exists() else None


def _rank_badge_pulse_lines(prev: str, badge_idx: int, out_label: str, anchor: tuple) -> list[str]:
    """CTA 버튼과 같은 사인파 스케일 펄스(±6%)로 배지를 미세하게 맥동시키고, 사선(-10도)으로
    기울여 스티커처럼 보이게 한다(2026-09-10, 사용자 피드백 "눈에 띄게" + "얼굴부분에서
    강조, 네모를 사선으로"). rotate 필터는 ow/oh를 명시해야 기울어진 모서리가 안 잘리고,
    회전+펄스로 매 프레임 실제 크기가 바뀌므로 x/y는 항상 'anchor가 중심이 되도록' 동적
    계산한다(고정좌표를 쓰면 커질 때 중심이 밀려 앵커에서 벗어남)."""
    cx, cy = anchor
    angle_rad = f"({RANK_BADGE_ANGLE_DEG}*PI/180)"
    return [
        f"[{badge_idx}:v]scale=w='iw*(1+0.06*sin(2*3.14159265*t/1.2))':"
        f"h='ih*(1+0.06*sin(2*3.14159265*t/1.2))':eval=frame,"
        f"rotate={angle_rad}:c=black@0:ow=rotw({angle_rad}):oh=roth({angle_rad})[badgepulse];\n",
        f"[{prev}][badgepulse]overlay=x='{cx}-w/2':y='{cy}-h/2':eval=frame:shortest=1[{out_label}];\n",
    ]


def _beat_duration(work_dir: Path, i: int) -> float:
    return json.loads((work_dir / f"narration{i}.json").read_text(encoding="utf-8"))["duration"]


def compute_beat_timing(durs):
    starts, ends = [], []
    t = LEAD_IN
    for i, d in enumerate(durs):
        if i > 0:
            t += BEAT_GAP
        starts.append(t)
        t += d
        ends.append(t)
    return starts, ends


def build_audio_timeline(work_dir: Path, durs, starts, ends) -> Path:
    n = len(durs)
    whoosh = SFX_DIR / "whoosh-short.mp3"
    pop = SFX_DIR / "pop.mp3"
    lines = []
    for i in range(n):
        ms = int(starts[i] * 1000)
        lines.append(f"[{i}:a]adelay={ms},aformat=channel_layouts=stereo:sample_rates=44100[a{i}];")

    whoosh_idx = n
    whoosh_labels = []
    if n > 1:
        lines.append(f"[{whoosh_idx}:a]asplit={n-1}[" + "][".join(f"w{i}s" for i in range(n - 1)) + "];")
        for i in range(n - 1):
            ms = int(ends[i] * 1000)
            lines.append(f"[w{i}s]volume=0.85,adelay={ms}|{ms},aformat=sample_rates=44100[w{i}];")
            whoosh_labels.append(f"[w{i}]")

    pop_idx = n + 1
    lines.append(f"[{pop_idx}:a]asplit={n}[" + "][".join(f"p{i}s" for i in range(n)) + "];")
    pop_labels = []
    for i in range(n):
        ms = int(max(0, starts[i] * 1000 - 50))
        lines.append(f"[p{i}s]volume=0.6,adelay={ms}|{ms},aformat=sample_rates=44100[p{i}];")
        pop_labels.append(f"[p{i}]")

    all_labels = [f"[a{i}]" for i in range(n)] + whoosh_labels + pop_labels
    lines.append("".join(all_labels) + f"amix=inputs={len(all_labels)}:duration=longest:normalize=0[aout]")

    filter_path = work_dir / "filter_audio.txt"
    filter_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = ["ffmpeg", "-y", "-v", "error"]
    for i in range(n):
        cmd += ["-i", str(work_dir / f"narration{i+1}.mp3")]
    cmd += ["-i", str(whoosh), "-i", str(pop)]
    cmd += ["-filter_complex_script", str(filter_path), "-map", "[aout]", "-t", f"{ends[-1]:.2f}",
            "-c:a", "pcm_s16le", str(work_dir / "combined_audio.wav")]
    run(cmd)
    return work_dir / "combined_audio.wav"


def _build_product_video_cell(work_dir: Path, total_dur: float) -> Path | None:
    """product_video_raw.mp4(generate_product_video.py가 만든 4초 AI 회전영상)가 있으면
    라운드마스크+골드링을 씌워 정지이미지 product_framed.png와 같은 자리에 넣을 수 있는
    형태로 만든다(2026-09-11, 사용자 요청 — 반응 저조한 정지이미지를 실제 모션으로).
    없으면(생성 실패/미설정) None을 반환해서 호출부가 기존 정지이미지 경로로 폴백하게 함.

    4초 원본은 정방향+역방향을 이어붙인 "부메랑" 루프로 total_dur까지 채운다 — 그냥
    -stream_loop로 하드컷 반복하면 4초마다 티나는 점프컷이 생기는데, 부메랑은 이음매가
    안 보임(재생↔역재생 경계가 항상 같은 프레임이라 끊김이 없음).
    """
    raw = work_dir / "product_video_raw.mp4"
    mask = work_dir / "round_mask.png"
    ring = work_dir / "product_ring.png"
    backdrop = work_dir / "product_video_backdrop.png"
    if not (raw.exists() and mask.exists() and ring.exists() and backdrop.exists()):
        return None

    reversed_p = work_dir / "_pv_reversed.mp4"
    forward_p = work_dir / "_pv_forward.mp4"
    boomerang_p = work_dir / "_pv_boomerang.mp4"
    out = work_dir / "product_video_cell.mp4"
    try:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-vf", "reverse", "-an",
             "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(reversed_p)])
        run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-an",
             "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(forward_p)])
        concat_list = work_dir / "_pv_concat.txt"
        concat_list.write_text(f"file '{forward_p.name}'\nfile '{reversed_p.name}'\n", encoding="utf-8")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(boomerang_p)])

        filter_txt = (
            "[0:v]scale=600:600,setsar=1,format=yuva420p[vid];"
            "[1:v]format=gray[m];[vid][m]alphamerge[vidm];"
            "[2:v]format=rgba[bg2];[bg2][vidm]overlay=30:30:shortest=0[step1];"
            "[step1][3:v]overlay=0:0:shortest=0[out]"
        )
        run(["ffmpeg", "-y", "-v", "error",
             "-stream_loop", "-1", "-i", str(boomerang_p),
             "-loop", "1", "-i", str(mask),
             "-loop", "1", "-i", str(backdrop),
             "-loop", "1", "-i", str(ring),
             "-filter_complex", filter_txt,
             "-map", "[out]", "-t", f"{total_dur:.2f}", "-r", "25",
             "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out)])
    except subprocess.CalledProcessError as e:
        print(f"[assemble_video] 상품영상 합성 실패, 정지이미지로 폴백: {e}")
        return None
    finally:
        for p in (reversed_p, forward_p, boomerang_p, work_dir / "_pv_concat.txt"):
            p.unlink(missing_ok=True)
    return out


def build_middle_segment(work_dir: Path, durs, starts, ends, total_dur: float) -> Path:
    n = len(durs)
    zoom_cuts = starts
    inner = f"t-{zoom_cuts[-1]}"
    zoom_expr = ""
    for i in range(n - 1):
        zoom_expr += f"if(lt(t\\,{zoom_cuts[i+1]})\\,t-{zoom_cuts[i]}\\,"
    zoom_expr += inner
    zoom_expr += ")" * (n - 1)

    product_video_path = _build_product_video_cell(work_dir, total_dur)

    lines = []
    cmd = ["ffmpeg", "-y", "-v", "error"]
    next_idx = [0]

    def add_input(*args) -> int:
        cmd.extend(args)
        i = next_idx[0]
        next_idx[0] += 1
        return i

    bg_idx = add_input("-loop", "1", "-i", str(work_dir / "bg_bright.png"))
    lines.append(f"[{bg_idx}:v]scale=1080:1920[bg];")
    shadow_idx = add_input("-loop", "1", "-i", str(work_dir / "product_shadow.png"))
    lines.append(f"[bg][{shadow_idx}:v]overlay={SHADOW_XY[0]}:{SHADOW_XY[1]}:shortest=1[s0];")

    if product_video_path:
        # 2026-09-11: AI영상은 이미 배경패치+골드링까지 합성된 상태(product_video_cell,
        # 660x660)라 정지이미지 경로의 반사(reflection) 레이어는 필요 없음 — 회전하는
        # 영상에 정지된 반사를 겹치면 오히려 부자연스러워서 의도적으로 생략.
        product_idx = add_input("-i", str(product_video_path))
        lines.append(f"[s0][{product_idx}:v]overlay={PRODUCT_XY[0]}:{PRODUCT_XY[1]}:shortest=1[s1b];")
    else:
        product_idx = add_input("-loop", "1", "-i", str(work_dir / "product_framed.png"))
        lines.append(f"[s0][{product_idx}:v]overlay={PRODUCT_XY[0]}:{PRODUCT_XY[1]}:shortest=1[s1];")
        reflection_idx = add_input("-loop", "1", "-i", str(work_dir / "product_reflection.png"))
        lines.append(f"[s1][{reflection_idx}:v]overlay={REFLECTION_XY[0]}:{REFLECTION_XY[1]}:shortest=1[s1b];")

    title_idx = add_input("-loop", "1", "-i", str(work_dir / "title_block.png"))
    lines.append(f"[s1b][{title_idx}:v]overlay={TITLE_XY[0]}:{TITLE_XY[1]}:shortest=1[s2];")

    card_indices = [add_input("-loop", "1", "-i", str(work_dir / f"gold_card{i+1}.png")) for i in range(n)]
    card_labels = []
    for i, ci in enumerate(card_indices):
        fade_in_st = 0.0 if i == 0 else max(0.0, starts[i] - CARD_FADEIN_LEAD)
        fade_out_st = (total_dur - CARD_FADE) if i == n - 1 else (ends[i] + CARD_FADEOUT_LEAD)
        lines.append(
            f"[{ci}:v]fade=t=in:st={fade_in_st:.3f}:d={CARD_FADE}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={CARD_FADE}:alpha=1[c{i}];"
        )
        card_labels.append(f"c{i}")
    prev = "s2"
    for i, lbl in enumerate(card_labels):
        nxt = f"sc{i}"
        lines.append(f"[{prev}][{lbl}]overlay={CARDS_XY_X}:{CARDS_Y}:shortest=1[{nxt}];")
        prev = nxt

    lines.append(
        f"[{prev}]scale=w='1080*(1+0.05*exp(-6*max({zoom_expr}\\,0)))':"
        f"h='1920*(1+0.05*exp(-6*max({zoom_expr}\\,0)))':eval=frame[zoomed];"
    )
    lines.append("[zoomed]crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2[punched];")

    flash_input_idx = add_input("-loop", "1", "-i", str(work_dir / "flash_white.png"))
    flash_conds = "+".join(f"between(t\\,{ends[i]:.3f}\\,{ends[i]+FLASH_DUR:.3f})" for i in range(n - 1))
    if flash_conds:
        lines.append(f"[punched][{flash_input_idx}:v]overlay=0:0:enable='{flash_conds}':shortest=1[flashed];")
    else:
        lines.append("[punched]copy[flashed];")

    logo_idx = add_input("-loop", "1", "-i", str(work_dir / "logo_xl.png"))
    lines.append(f"[flashed][{logo_idx}:v]overlay={LOGO_XY[0]}:{LOGO_XY[1]}:shortest=1[u1];")
    ai_idx = add_input("-loop", "1", "-i", str(work_dir / "ai_tag.png"))
    lines.append(f"[u1][{ai_idx}:v]overlay={AI_TAG_XY[0]}:{AI_TAG_XY[1]}:shortest=1[u1b];")

    rank_badge_path = _rank_badge_path(work_dir)
    prev = "u1b"
    if rank_badge_path:
        badge_idx = add_input("-loop", "1", "-i", str(rank_badge_path))
        lines += _rank_badge_pulse_lines(prev, badge_idx, "u1c", RANK_BADGE_ANCHOR_PRODUCT)
        prev = "u1c"

    switches = [0.0]
    for i in range(n - 1):
        switches.append(ends[i] + SWITCH_OFFSET)
    switches.append(total_dur)

    for i in range(n):
        step_idx = add_input("-loop", "1", "-i", str(work_dir / f"step_badge{i+1}.png"))
        lo = switches[i] + (SWITCH_EPS / 2 if i > 0 else 0)
        hi = switches[i + 1] - (SWITCH_EPS / 2 if i < n - 1 else 0)
        nxt = f"ub{i}"
        lines.append(f"[{prev}][{step_idx}:v]overlay={BADGE_XY[0]}:{BADGE_XY[1]}:enable='between(t\\,{lo:.3f}\\,{hi:.3f})':shortest=1[{nxt}];")
        prev = nxt

    # 2026-08-27: 설명구간 자막(카드 값 텍스트를 그대로 반복) 제거 — 카드 자체에 이미
    # 같은 문구가 적혀있어서 중복이었고, 자막 위치가 유튜브 쇼츠의 렌즈 배너와 겹치는
    # 문제도 이걸로 같이 해결됨(카드 위치를 따로 재설계할 필요가 없어짐).
    vignette_idx = add_input("-loop", "1", "-i", str(work_dir / "vignette.png"))
    lines.append(f"[{prev}][{vignette_idx}:v]overlay=0:0:shortest=1[vout]")

    filter_path = work_dir / "filter_middle.txt"
    filter_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    audio_idx = add_input("-i", str(work_dir / "combined_audio.wav"))
    out_path = work_dir / "middle_segment.mp4"
    cmd += ["-filter_complex_script", str(filter_path),
            "-map", "[vout]", "-map", f"{audio_idx}:a",
            "-t", f"{total_dur:.2f}", "-r", "25", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", str(out_path)]
    run(cmd)
    return out_path


def build_hook_segment(work_dir: Path) -> Path:
    badge_path = _rank_badge_path(work_dir)
    lines = [
        "[0:v]scale=1080:1920,setsar=1,fps=25[base];\n",
        f"[base][1:v]overlay={LOGO_XY[0]}:{LOGO_XY[1]}:shortest=1[u1];\n",
        f"[u1][2:v]overlay={AI_TAG_XY[0]}:{AI_TAG_XY[1]}:shortest=1[u2];\n",
        f"[u2][3:v]overlay={TITLE_XY[0]}:{TITLE_XY[1]}:shortest=1[u3];\n",
    ]
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-i", str(work_dir / "hook.mp4"),
           "-loop", "1", "-i", str(work_dir / "logo_xl.png"),
           "-loop", "1", "-i", str(work_dir / "ai_tag.png"),
           "-loop", "1", "-i", str(work_dir / "title_block.png")]
    prev = "u3"
    next_idx = 4
    if badge_path:
        lines += _rank_badge_pulse_lines(prev, next_idx, "u3b", RANK_BADGE_ANCHOR_FACE)
        cmd += ["-loop", "1", "-i", str(badge_path)]
        prev = "u3b"
        next_idx += 1
    lines.append(f"[{prev}][{next_idx}:v]overlay={CAPTION_X}:{HOOK_CAPTION_Y}:shortest=1[vout];\n")
    cmd += ["-loop", "1", "-i", str(work_dir / "caption_hook.png")]
    lines.append(f"[0:a]{LOUDNORM_TARGET}[aout]\n")

    filter_path = work_dir / "filter_hook.txt"
    filter_path.write_text("".join(lines), encoding="utf-8")
    out_path = work_dir / "hook_final.mp4"
    cmd += ["-filter_complex_script", str(filter_path),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out_path)]
    run(cmd)
    return out_path


def build_cta_segment(work_dir: Path) -> Path:
    # 자막이 2줄이 되면(build_graphics.build_caption의 max_lines=2) 고정 CTA_BUTTON_Y로는
    # 버튼과 겹친다(2026-08-27 사용자 스크린샷 제보로 발견) — 실제로 만들어진
    # caption_cta.png 높이를 읽어서 그 밑에 여유(CTA_CAPTION_BUTTON_GAP)를 두고 버튼을
    # 놓는다. 1줄일 때는 기존 CTA_BUTTON_Y와 사실상 같은 위치가 나옴.
    caption_h = Image.open(work_dir / "caption_cta.png").height
    button_y = max(CTA_CAPTION_Y + caption_h + CTA_CAPTION_BUTTON_GAP, CTA_BUTTON_Y)
    badge_path = _rank_badge_path(work_dir)
    lines = [
        "[0:v]scale=1080:1920,setsar=1,fps=25[base];\n",
        f"[base][1:v]overlay={LOGO_XY[0]}:{LOGO_XY[1]}:shortest=1[u1];\n",
        f"[u1][2:v]overlay={AI_TAG_XY[0]}:{AI_TAG_XY[1]}:shortest=1[u2];\n",
    ]
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-i", str(work_dir / "cta.mp4"),
           "-loop", "1", "-i", str(work_dir / "logo_xl.png"),
           "-loop", "1", "-i", str(work_dir / "ai_tag.png")]
    prev = "u2"
    next_idx = 3
    if badge_path:
        lines += _rank_badge_pulse_lines(prev, next_idx, "u2b", RANK_BADGE_ANCHOR_FACE)
        cmd += ["-loop", "1", "-i", str(badge_path)]
        prev = "u2b"
        next_idx += 1
    lines.append(f"[{prev}][{next_idx}:v]overlay={CAPTION_X}:{CTA_CAPTION_Y}:shortest=1[u3];\n")
    cmd += ["-loop", "1", "-i", str(work_dir / "caption_cta.png")]
    btn_idx = next_idx + 1
    lines.append(
        "[{}:v]scale=w='560*(1+0.045*sin(2*3.14159265*t/1.1))':"
        "h='108*(1+0.045*sin(2*3.14159265*t/1.1))':eval=frame[btn];\n".format(btn_idx)
    )
    cmd += ["-loop", "1", "-i", str(work_dir / "cta_button.png")]
    lines.append(f"[u3][btn]overlay=x='(1080-w)/2':y={button_y}:eval=frame:shortest=1[vout];\n")
    lines.append(f"[0:a]{LOUDNORM_TARGET}[aout]\n")

    filter_path = work_dir / "filter_cta.txt"
    filter_path.write_text("".join(lines), encoding="utf-8")
    out_path = work_dir / "cta_final.mp4"
    cmd += ["-filter_complex_script", str(filter_path),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out_path)]
    run(cmd)
    return out_path


def assemble(work_dir: Path, out_path: Path):
    durs = [_beat_duration(work_dir, i) for i in (1, 2, 3)]
    starts, ends = compute_beat_timing(durs)
    total_dur = ends[-1]
    print(f"[assemble_video] 비트 길이: {[round(d,2) for d in durs]}, 설명구간 {total_dur:.2f}초")

    build_audio_timeline(work_dir, durs, starts, ends)
    middle_path = build_middle_segment(work_dir, durs, starts, ends, total_dur)
    hook_path = build_hook_segment(work_dir)
    cta_path = build_cta_segment(work_dir)

    filter_txt = (
        "[0:v]fps=25,setsar=1[v0];[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
        "[1:v]fps=25,setsar=1[v1];[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
        "[2:v]fps=25,setsar=1[v2];[2:a]aformat=sample_rates=44100:channel_layouts=stereo[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]"
    )
    run(["ffmpeg", "-y", "-v", "error",
         "-i", str(hook_path), "-i", str(middle_path), "-i", str(cta_path),
         "-filter_complex", filter_txt,
         "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         str(out_path)])
    print(f"[assemble_video] 최종 영상 완료: {out_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--work-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    assemble(Path(args.work_dir), Path(args.out))
