"""ffmpeg으로 훅+스펙설명+CTA를 최종 mp4 하나로 조립 (2026-08-26 확정 v10 골드 디자인 재현).

전제: build_graphics.py로 만든 PNG들과 heygen_gen.py로 만든 hook.mp4/cta.mp4/
middle_narration.mp3(+.json)가 같은 work_dir에 있어야 함.
"""
import argparse
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SFX_DIR = HERE.parent / "assets" / "sfx"


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def assemble(work_dir: Path, out_path: Path):
    narration_meta = json.loads((work_dir / "middle_narration.json").read_text(encoding="utf-8"))
    narration_dur = narration_meta["duration"]
    third = narration_dur / 3

    seg_bounds = [
        (0.0, third + 0.15),
        (third - 0.15, 2 * third + 0.15),
        (2 * third - 0.15, narration_dur + 0.1),
    ]

    filter_middle = f"""
[0:v]scale=1080:1920[bg];
[1:v]format=rgba,scale=w='700+t*1':h=-1:eval=frame[prodz];
[bg][prodz]overlay=x='(1080-w)/2':y=480[bg1];
[bg1][2:v]overlay=(1080-900)/2:240[bg2];
[3:v]fade=t=in:st=0:d=0.25:alpha=1,fade=t=out:st={seg_bounds[0][1]-0.25:.2f}:d=0.25:alpha=1[c1];
[4:v]fade=t=in:st={seg_bounds[1][0]:.2f}:d=0.25:alpha=1,fade=t=out:st={seg_bounds[1][1]-0.25:.2f}:d=0.25:alpha=1[c2];
[5:v]fade=t=in:st={seg_bounds[2][0]:.2f}:d=0.25:alpha=1,fade=t=out:st={seg_bounds[2][1]-0.25:.2f}:d=0.25:alpha=1[c3];
[bg2][c1]overlay=104:1250:enable='between(t\\,{seg_bounds[0][0]:.2f}\\,{seg_bounds[0][1]:.2f})'[s1];
[s1][c2]overlay=104:1250:enable='between(t\\,{seg_bounds[1][0]:.2f}\\,{seg_bounds[1][1]:.2f})'[s2];
[s2][c3]overlay=104:1250:enable='between(t\\,{seg_bounds[2][0]:.2f}\\,{seg_bounds[2][1]:.2f})'[s3];
[s3][6:v]overlay=40:60:shortest=1[vout]
""".strip()
    filter_path = work_dir / "filter_middle.txt"
    filter_path.write_text(filter_middle, encoding="utf-8")

    pop_delays = [int(seg_bounds[i][0] * 1000) for i in range(3)]
    middle_mp4 = work_dir / "middle_segment.mp4"
    run([
        "ffmpeg", "-y", "-v", "error",
        "-loop", "1", "-i", str(work_dir / "bg_bright.png"),
        "-loop", "1", "-i", str(work_dir / "product_framed.png"),
        "-loop", "1", "-i", str(work_dir / "title_block.png"),
        "-loop", "1", "-i", str(work_dir / "gold_card1.png"),
        "-loop", "1", "-i", str(work_dir / "gold_card2.png"),
        "-loop", "1", "-i", str(work_dir / "gold_card3.png"),
        "-loop", "1", "-i", str(work_dir / "channel_logo_xl.png"),
        "-i", str(work_dir / "middle_narration.mp3"),
        "-i", str(SFX_DIR / "pop.mp3"),
        "-filter_complex_script", str(filter_path),
        "-filter_complex",
        f"[8:a]volume=0.5[pop0];[8:a]volume=0.5[pop1];[8:a]volume=0.5[pop2];"
        f"[pop0]adelay={pop_delays[0]}|{pop_delays[0]}[p0d];"
        f"[pop1]adelay={pop_delays[1]}|{pop_delays[1]}[p1d];"
        f"[pop2]adelay={pop_delays[2]}|{pop_delays[2]}[p2d];"
        f"[7:a][p0d][p1d][p2d]amix=inputs=4:duration=first:dropout_transition=0:normalize=0[aout]",
        "-map", "[vout]", "-map", "[aout]",
        "-t", str(narration_dur),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-crf", "18",
        str(middle_mp4),
    ])

    hook_mp4 = work_dir / "hook.mp4"
    cta_mp4 = work_dir / "cta.mp4"
    hook_dur = ffprobe_duration(hook_mp4)
    cta_dur = ffprobe_duration(cta_mp4)
    whoosh1_ms = int(hook_dur * 1000)
    whoosh2_ms = int((hook_dur + narration_dur) * 1000)

    run([
        "ffmpeg", "-y", "-v", "error",
        "-i", str(hook_mp4), "-i", str(middle_mp4), "-i", str(cta_mp4),
        "-loop", "1", "-i", str(work_dir / "caption_hook.png"),
        "-loop", "1", "-i", str(work_dir / "caption_cta.png"),
        "-loop", "1", "-i", str(work_dir / "hook_title.png"),
        "-loop", "1", "-i", str(work_dir / "channel_logo_xl.png"),
        "-loop", "1", "-i", str(work_dir / "cta_banner.png"),
        "-i", str(SFX_DIR / "whoosh-short.mp3"),
        "-filter_complex",
        "[0:v]scale=1080:1920,setsar=1,fps=25[h0s];"
        "[6:v]scale=520:-1[logo1];"
        "[h0s][logo1]overlay=40:60:shortest=1[h0l];"
        "[5:v]scale=w='1000*min(1\\,0.75+0.25*t/0.4)':h=-1:eval=frame,"
        "fade=t=in:st=0:d=0.35:alpha=1,fade=t=out:st=2.3:d=0.4:alpha=1[htitle];"
        "[h0l][htitle]overlay=x='(1080-w)/2':y=280:shortest=1[h0t];"
        "[3:v]scale=860:-1[c0];"
        "[h0t][c0]overlay=(1080-860)/2:1250:shortest=1[v0];"
        "[1:v]setsar=1,fps=25[v1];"
        "[2:v]scale=1080:1920,setsar=1,fps=25[h2s];"
        "[6:v]scale=520:-1[logo2];"
        "[h2s][logo2]overlay=40:60:shortest=1[h2l];"
        "[7:v]scale=w='560*min(1\\,0.6+0.4*t/0.3)*(1+0.045*sin(2*PI*t/1.1))':h=-1:eval=frame,"
        "fade=t=in:st=0:d=0.3:alpha=1[banner];"
        "[h2l][banner]overlay=x='(1080-w)/2':y=1050:shortest=1[h2b];"
        "[4:v]scale=860:-1[c2];"
        "[h2b][c2]overlay=(1080-860)/2:1220:shortest=1[v2];"
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
        "[2:a]aformat=sample_rates=44100:channel_layouts=stereo[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vconcat][aconcat];"
        f"[8:a]volume=0.7[wh0];[8:a]volume=0.7[wh1];"
        f"[wh0]adelay={whoosh1_ms}|{whoosh1_ms}[wh0d];"
        f"[wh1]adelay={whoosh2_ms}|{whoosh2_ms}[wh1d];"
        "[aconcat][wh0d][wh1d]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[aout]",
        "-map", "[vconcat]", "-map", "[aout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-crf", "18",
        str(out_path),
    ])
    print(f"[assemble_video] 최종 영상 완료: {out_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--work-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    assemble(Path(args.work_dir), Path(args.out))
