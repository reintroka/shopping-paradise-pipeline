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


def build_middle_segment(work_dir: Path, durs, starts, ends, total_dur: float) -> Path:
    n = len(durs)
    zoom_cuts = starts
    inner = f"t-{zoom_cuts[-1]}"
    zoom_expr = ""
    for i in range(n - 1):
        zoom_expr += f"if(lt(t\\,{zoom_cuts[i+1]})\\,t-{zoom_cuts[i]}\\,"
    zoom_expr += inner
    zoom_expr += ")" * (n - 1)

    lines = []
    lines.append("[0:v]scale=1080:1920[bg];")
    lines.append(f"[bg][1:v]overlay={SHADOW_XY[0]}:{SHADOW_XY[1]}:shortest=1[s0];")
    lines.append(f"[s0][2:v]overlay={PRODUCT_XY[0]}:{PRODUCT_XY[1]}:shortest=1[s1];")
    lines.append(f"[s1][3:v]overlay={REFLECTION_XY[0]}:{REFLECTION_XY[1]}:shortest=1[s1b];")
    lines.append(f"[s1b][4:v]overlay={TITLE_XY[0]}:{TITLE_XY[1]}:shortest=1[s2];")

    card_labels = []
    for i in range(n):
        idx = 5 + i
        fade_in_st = 0.0 if i == 0 else max(0.0, starts[i] - CARD_FADEIN_LEAD)
        fade_out_st = (total_dur - CARD_FADE) if i == n - 1 else (ends[i] + CARD_FADEOUT_LEAD)
        lines.append(
            f"[{idx}:v]fade=t=in:st={fade_in_st:.3f}:d={CARD_FADE}:alpha=1,"
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

    flash_idx = 5 + n
    flash_conds = "+".join(f"between(t\\,{ends[i]:.3f}\\,{ends[i]+FLASH_DUR:.3f})" for i in range(n - 1))
    if flash_conds:
        lines.append(f"[punched][{flash_idx}:v]overlay=0:0:enable='{flash_conds}':shortest=1[flashed];")
    else:
        lines.append("[punched]copy[flashed];")

    logo_idx = flash_idx + 1
    ai_idx = logo_idx + 1
    lines.append(f"[flashed][{logo_idx}:v]overlay={LOGO_XY[0]}:{LOGO_XY[1]}:shortest=1[u1];")
    lines.append(f"[u1][{ai_idx}:v]overlay={AI_TAG_XY[0]}:{AI_TAG_XY[1]}:shortest=1[u1b];")

    switches = [0.0]
    for i in range(n - 1):
        switches.append(ends[i] + SWITCH_OFFSET)
    switches.append(total_dur)

    badge_base = ai_idx + 1
    prev = "u1b"
    for i in range(n):
        idx = badge_base + i
        lo = switches[i] + (SWITCH_EPS / 2 if i > 0 else 0)
        hi = switches[i + 1] - (SWITCH_EPS / 2 if i < n - 1 else 0)
        nxt = f"ub{i}"
        lines.append(f"[{prev}][{idx}:v]overlay={BADGE_XY[0]}:{BADGE_XY[1]}:enable='between(t\\,{lo:.3f}\\,{hi:.3f})':shortest=1[{nxt}];")
        prev = nxt

    # 2026-08-27: 설명구간 자막(카드 값 텍스트를 그대로 반복) 제거 — 카드 자체에 이미
    # 같은 문구가 적혀있어서 중복이었고, 자막 위치가 유튜브 쇼츠의 렌즈 배너와 겹치는
    # 문제도 이걸로 같이 해결됨(카드 위치를 따로 재설계할 필요가 없어짐).
    vignette_idx = badge_base + n
    lines.append(f"[{prev}][{vignette_idx}:v]overlay=0:0:shortest=1[vout]")

    filter_path = work_dir / "filter_middle.txt"
    filter_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    audio_idx = vignette_idx + 1
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-loop", "1", "-i", str(work_dir / "bg_bright.png"),
           "-loop", "1", "-i", str(work_dir / "product_shadow.png"),
           "-loop", "1", "-i", str(work_dir / "product_framed.png"),
           "-loop", "1", "-i", str(work_dir / "product_reflection.png"),
           "-loop", "1", "-i", str(work_dir / "title_block.png")]
    for i in range(n):
        cmd += ["-loop", "1", "-i", str(work_dir / f"gold_card{i+1}.png")]
    cmd += ["-loop", "1", "-i", str(work_dir / "flash_white.png")]
    cmd += ["-loop", "1", "-i", str(work_dir / "logo_xl.png")]
    cmd += ["-loop", "1", "-i", str(work_dir / "ai_tag.png")]
    for i in range(n):
        cmd += ["-loop", "1", "-i", str(work_dir / f"step_badge{i+1}.png")]
    cmd += ["-loop", "1", "-i", str(work_dir / "vignette.png")]
    cmd += ["-i", str(work_dir / "combined_audio.wav")]
    out_path = work_dir / "middle_segment.mp4"
    cmd += ["-filter_complex_script", str(filter_path),
            "-map", "[vout]", "-map", f"{audio_idx}:a",
            "-t", f"{total_dur:.2f}", "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", str(out_path)]
    run(cmd)
    return out_path


def build_hook_segment(work_dir: Path) -> Path:
    filter_txt = (
        "[0:v]scale=1080:1920,setsar=1,fps=25[base];\n"
        f"[base][1:v]overlay={LOGO_XY[0]}:{LOGO_XY[1]}:shortest=1[u1];\n"
        f"[u1][2:v]overlay={AI_TAG_XY[0]}:{AI_TAG_XY[1]}:shortest=1[u2];\n"
        f"[u2][3:v]overlay={TITLE_XY[0]}:{TITLE_XY[1]}:shortest=1[u3];\n"
        f"[u3][4:v]overlay={CAPTION_X}:{HOOK_CAPTION_Y}:shortest=1[vout];\n"
        f"[0:a]{LOUDNORM_TARGET}[aout]\n"
    )
    filter_path = work_dir / "filter_hook.txt"
    filter_path.write_text(filter_txt, encoding="utf-8")
    out_path = work_dir / "hook_final.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-i", str(work_dir / "hook.mp4"),
           "-loop", "1", "-i", str(work_dir / "logo_xl.png"),
           "-loop", "1", "-i", str(work_dir / "ai_tag.png"),
           "-loop", "1", "-i", str(work_dir / "title_block.png"),
           "-loop", "1", "-i", str(work_dir / "caption_hook.png"),
           "-filter_complex_script", str(filter_path),
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out_path)]
    run(cmd)
    return out_path


def build_cta_segment(work_dir: Path) -> Path:
    # 자막이 2줄이 되면(build_graphics.build_caption의 max_lines=2) 고정 CTA_BUTTON_Y로는
    # 버튼과 겹친다(2026-08-27 사용자 스크린샷 제보로 발견) — 실제로 만들어진
    # caption_cta.png 높이를 읽어서 그 밑에 여유(CTA_CAPTION_BUTTON_GAP)를 두고 버튼을
    # 놓는다. 1줄일 때는 기존 CTA_BUTTON_Y와 사실상 같은 위치가 나옴.
    caption_h = Image.open(work_dir / "caption_cta.png").height
    button_y = max(CTA_CAPTION_Y + caption_h + CTA_CAPTION_BUTTON_GAP, CTA_BUTTON_Y)
    filter_txt = (
        "[0:v]scale=1080:1920,setsar=1,fps=25[base];\n"
        f"[base][1:v]overlay={LOGO_XY[0]}:{LOGO_XY[1]}:shortest=1[u1];\n"
        f"[u1][2:v]overlay={AI_TAG_XY[0]}:{AI_TAG_XY[1]}:shortest=1[u2];\n"
        f"[u2][3:v]overlay={CAPTION_X}:{CTA_CAPTION_Y}:shortest=1[u3];\n"
        "[4:v]scale=w='560*(1+0.045*sin(2*3.14159265*t/1.1))':"
        "h='108*(1+0.045*sin(2*3.14159265*t/1.1))':eval=frame[btn];\n"
        f"[u3][btn]overlay=x='(1080-w)/2':y={button_y}:eval=frame:shortest=1[vout];\n"
        f"[0:a]{LOUDNORM_TARGET}[aout]\n"
    )
    filter_path = work_dir / "filter_cta.txt"
    filter_path.write_text(filter_txt, encoding="utf-8")
    out_path = work_dir / "cta_final.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-i", str(work_dir / "cta.mp4"),
           "-loop", "1", "-i", str(work_dir / "logo_xl.png"),
           "-loop", "1", "-i", str(work_dir / "ai_tag.png"),
           "-loop", "1", "-i", str(work_dir / "caption_cta.png"),
           "-loop", "1", "-i", str(work_dir / "cta_button.png"),
           "-filter_complex_script", str(filter_path),
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out_path)]
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
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         str(out_path)])
    print(f"[assemble_video] 최종 영상 완료: {out_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--work-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    assemble(Path(args.work_dir), Path(args.out))
