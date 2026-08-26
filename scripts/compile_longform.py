"""3일치(하루 2개 x 3일 = 6개) 숏츠가 쌓이면 자동으로 롱폼으로 이어붙여 유튜브에 업로드.

- 각 파이프라인 실행(run_pipeline.py) 끝에서 soft_step으로 호출됨 — 6개가 안 쌓였으면
  아무것도 안 하고 조용히 리턴(매번 호출해도 안전).
- 이미 올라간 숏츠를 로컬에 안 남겨두므로(클라우드 실행은 매번 새 샌드박스),
  yt-dlp로 유튜브에서 다시 내려받아 이어붙인다.
- 6개를 다 쓰면 shorts_log.json의 해당 항목에 compiled_in(롱폼 video_id)을 표시해서
  다음에 중복으로 다시 안 묶이게 한다.

사용법: python3 compile_longform.py   (인자 없음, 조건 안 맞으면 그냥 종료)
"""
import json
import subprocess
from pathlib import Path

import shorts_log
import upload_youtube

BATCH_SIZE = 6  # 하루 2개 x 3일
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
COUNTER_PATH = REPO_ROOT / "longform_counter.json"


def run(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def next_volume_number() -> int:
    if COUNTER_PATH.exists():
        n = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))["next"]
    else:
        n = 1
    COUNTER_PATH.write_text(json.dumps({"next": n + 1}), encoding="utf-8")
    return n


def download_short(video_id: str, out_path: Path):
    run(["yt-dlp", "-f", "mp4", "-o", str(out_path), f"https://youtu.be/{video_id}"])


def build_longform(entries: list[dict], work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    clip_paths = []
    for i, e in enumerate(entries):
        p = work_dir / f"clip{i}.mp4"
        download_short(e["video_id"], p)
        clip_paths.append(p)

    # 화이트 플래시/후시 없이 하드컷으로 이어붙임(1차 버전) — 인코딩 편차에 안전하도록
    # scale/setsar/fps로 정규화 후 filter concat 사용.
    inputs = []
    filter_parts = []
    for i, p in enumerate(clip_paths):
        inputs += ["-i", str(p)]
        filter_parts.append(f"[{i}:v]scale=1080:1920,setsar=1,fps=25[v{i}];")
        filter_parts.append(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}];")
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(clip_paths)))
    filter_complex = "".join(filter_parts) + f"{concat_inputs}concat=n={len(clip_paths)}:v=1:a=1[vout][aout]"

    out_path = work_dir / "longform.mp4"
    run([
        "ffmpeg", "-y", "-v", "error",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-crf", "18",
        str(out_path),
    ])
    return out_path


def build_title_and_description(entries: list[dict], vol: int) -> tuple[str, str]:
    names = [e["product_name"] for e in entries]
    title = f"[쇼핑의천국] 요즘 핫한 가전템 모음 Vol.{vol} | " + " · ".join(names[:3])
    title = title[:100]

    lines = [f"최근 {len(entries)}개 영상에서 소개한 상품들을 한 번에 모았습니다.\n"]
    for e in entries:
        lines.append(f"- {e['product_name']} ({e['price']:,}원대): {e['coupang_url']}")
    lines.append("")
    lines.append("이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.")
    lines.append("이 영상은 AI를 활용해 제작한 순수 창작물입니다.")
    lines.append("\n#쇼핑하울 #제품추천 #가전추천")
    description = "\n".join(lines)
    return title, description


def upload_longform(video_path: Path, title: str, description: str) -> dict:
    creds = upload_youtube.get_credentials()
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=creds)
    channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
    actual_title = channel_resp["items"][0]["snippet"]["title"]
    if actual_title != upload_youtube.EXPECTED_CHANNEL_TITLE:
        raise RuntimeError(f"채널 불일치! 예상: {upload_youtube.EXPECTED_CHANNEL_TITLE}, 실제: {actual_title}")

    body = {
        "snippet": {"title": title, "description": description, "tags": ["쇼핑하울", "제품추천", "가전추천"], "categoryId": "22"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"업로드 중... {int(status.progress() * 100)}%")
    video_id = response["id"]
    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}"}


def check_and_compile():
    entries = shorts_log.load_log()
    pending = [e for e in entries if not e.get("compiled_in")]
    if len(pending) < BATCH_SIZE:
        print(f"[compile_longform] 아직 {len(pending)}/{BATCH_SIZE}개 — 대기")
        return None

    batch = pending[:BATCH_SIZE]
    vol = next_volume_number()
    work_dir = REPO_ROOT / "work" / "longform" / f"vol{vol}"
    print(f"[compile_longform] {BATCH_SIZE}개 도달 — Vol.{vol} 롱폼 제작 시작")

    longform_path = build_longform(batch, work_dir)
    title, description = build_title_and_description(batch, vol)
    result = upload_longform(longform_path, title, description)

    for e in batch:
        e["compiled_in"] = result["video_id"]
    shorts_log.save_log(entries)

    print(f"[compile_longform] 완료: {result['url']}")
    return result


if __name__ == "__main__":
    check_and_compile()
