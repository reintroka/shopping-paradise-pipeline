"""3일치(하루 2개 x 3일 = 6개) 숏츠가 쌓이면 자동으로 롱폼 다이제스트로 제작+업로드.

2026-09-01 개편(v2): 기존엔 6개 숏츠를 하드컷으로 단순히 이어붙이기만 했음(v1).
사용자 요청으로 다른 13개 채널의 "리캡 롱폼" 패턴(챕터 디바이더+딥다이브 확장
나레이션+강조자막+인트로/아웃트로 카드)을 이식해 훨씬 풍성하게 재구성했다. 시각
톤은 새로 만들지 않고 이 채널 숏츠가 이미 쓰고 있는 골드 럭셔리 팔레트
(build_graphics.py)를 그대로 재사용해 통일감을 유지한다.

- 각 파이프라인 실행(run_pipeline.py) 끝에서 soft_step으로 호출됨 — 6개가 안 쌓였으면
  아무것도 안 하고 조용히 리턴(매번 호출해도 안전). 실패해도 예외가 soft_step에서
  잡히므로 숏츠 발행 자체는 막지 않는다 — 다음 실행 때 재시도됨(compiled_in 마킹은
  성공 시에만 저장되므로 안전).
- 이미 올라간 숏츠를 로컬에 안 남겨두므로(클라우드 실행은 매번 새 샌드박스), 우선
  GCS 백업 버킷(shopping-paradise-daily-raw-luith, upload_youtube.py가 발행 직후
  올려둠)에서 받고, 백업이 없는(백업 도입 이전 발행분) 경우에만 yt-dlp로 유튜브에서
  다시 내려받는다.
- 딥다이브 배경 이미지는 별도로 생성/저장하지 않고, 다운로드한 숏츠 클립 자체에서
  프레임을 뽑아 재사용한다 — 제품 이미지 URL을 따로 영구 저장할 필요가 없어져서
  2026-09-01 이전 발행분(specs 없음)에도 동일하게 적용 가능.
- 딥다이브 나레이션의 스펙 정보(specs)는 2026-09-01부터 shorts_log.json에 저장되기
  시작했다 — 그 이전에 발행된 항목은 spec 없이(상품명/가격만으로) 생성된다.
- 클립 전환은 xfade가 아니라 정지 비트(디바이더/전환 카드)+콘캣 하드컷으로 처리한다
  (라떼는북한 채널에서 xfade 누적오차로 뒤로 갈수록 싱크가 어긋나는 문제를 겪은 뒤
  확립된 패턴 — 정지 비트가 있으면 하드컷이어도 자연스러움).
- 6개를 다 쓰면 shorts_log.json의 해당 항목에 compiled_in(롱폼 video_id)을 표시해서
  다음에 중복으로 다시 안 묶이게 한다.

사용법: python3 compile_longform.py   (인자 없음, 조건 안 맞으면 그냥 종료)
"""
import json
import subprocess
from pathlib import Path

import deepdive_narration
import longform_graphics
import shorts_log
import upload_youtube

BATCH_SIZE = 6  # 하루 2개 x 3일
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
COUNTER_PATH = REPO_ROOT / "longform_counter.json"

GCS_BACKUP_BUCKET = "shopping-paradise-daily-raw-luith"

FPS = 25
DIVIDER_DUR = 2.2
TRANSITION_DUR = 1.3
DEEPDIVE_TAIL = 0.4
INTRO_DUR = 3.2
OUTRO_DUR = 3.5


def run(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def next_volume_number() -> int:
    if COUNTER_PATH.exists():
        n = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))["next"]
    else:
        n = 1
    COUNTER_PATH.write_text(json.dumps({"next": n + 1}), encoding="utf-8")
    return n


def _download_from_gcs_backup(video_id: str, out_path: Path) -> bool:
    """upload_youtube.py가 발행 직후 백업해둔 원본이 있으면 그걸 받는다(유튜브 봇
    차단 회피). 없으면(백업 이전 발행분, 또는 백업 실패분) False를 반환해 yt-dlp
    폴백으로 넘어간다."""
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(GCS_BACKUP_BUCKET)
        blob = bucket.blob(f"{video_id}.mp4")
        if not blob.exists():
            return False
        blob.download_to_filename(str(out_path))
        print(f"[compile_longform] GCS 백업에서 다운로드 성공: {video_id}")
        return True
    except Exception as exc:
        print(f"[compile_longform] GCS 백업 다운로드 실패, yt-dlp 폴백: {exc}")
        return False


def download_short(video_id: str, out_path: Path):
    if _download_from_gcs_backup(video_id, out_path):
        return
    print(f"[compile_longform] GCS 백업 없음, yt-dlp로 폴백: {video_id}")
    run(["yt-dlp", "-f", "mp4", "-o", str(out_path), f"https://youtu.be/{video_id}"])


def _extract_frame(clip_path: Path, out_path: Path):
    """딥다이브 배경용 프레임 — 훅(약 0~8초)이 지나고 스펙설명 구간(제품이 화면에
    잘 보이는 구간)쯤에서 한 장 뽑는다."""
    dur = _ffprobe_duration(clip_path)
    mid = max(0.5, min(dur - 0.3, dur * 0.35))
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i", str(clip_path),
         "-frames:v", "1", "-q:v", "2", str(out_path)])


def _static_segment(image_path: Path, duration: float, out_path: Path):
    run(["ffmpeg", "-y", "-v", "error",
         "-loop", "1", "-t", f"{duration:.2f}", "-i", str(image_path),
         "-f", "lavfi", "-t", f"{duration:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
         "-r", str(FPS), "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(out_path)])


def _deepdive_segment(frame_path: Path, caption_path: Path, audio_path: Path, duration: float, out_path: Path):
    zoom_frames = max(1, int(duration * FPS))
    filter_txt = (
        f"[0:v]scale=2160:3840,zoompan=z='min(zoom+0.0006,1.15)':d={zoom_frames}:s=1080x1920:fps={FPS}[bg];"
        f"[bg][1:v]overlay=(1080-w)/2:1300:shortest=1[vout]"
    )
    run(["ffmpeg", "-y", "-v", "error",
         "-loop", "1", "-i", str(frame_path),
         "-loop", "1", "-i", str(caption_path),
         "-i", str(audio_path),
         "-filter_complex", filter_txt,
         "-map", "[vout]", "-map", "2:a",
         "-t", f"{duration:.2f}", "-r", str(FPS), "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
         str(out_path)])


def _normalized_pair(idx: int) -> str:
    return (
        f"[{idx}:v]fps={FPS},setsar=1,scale=1080:1920[v{idx}];"
        f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{idx}];"
    )


def _concat_pieces(pieces: list, out_path: Path):
    """이미 각각 완결된(오디오 포함) mp4 조각들을 하드컷으로 이어붙인다. 라떼는북한
    채널에서 확립된 교훈(xfade 누적오차 대신 concat 필터+fps/setsar 정규화)을 따름."""
    n = len(pieces)
    filter_parts = [_normalized_pair(i) for i in range(n)]
    concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_parts.append(f"{concat_in}concat=n={n}:v=1:a=1[vout][aout]")
    filter_txt = "".join(filter_parts)

    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p in pieces:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", filter_txt, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            str(out_path)]
    run(cmd)


def _entry_specs(e: dict):
    specs = e.get("specs")
    if not specs:
        return None
    return [(s["title"], s["body"]) for s in specs]


def build_longform(entries: list, clip_paths: dict, work_dir: Path, vol: int) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    n = len(entries)
    pieces = []

    intro_img = longform_graphics.build_intro_card(work_dir, vol, n)
    intro_seg = work_dir / "seg_intro.mp4"
    _static_segment(intro_img, INTRO_DUR, intro_seg)
    pieces.append(intro_seg)

    for i, e in enumerate(entries, start=1):
        clip_path = clip_paths[e["video_id"]]

        divider_img = longform_graphics.build_chapter_divider(
            work_dir, i, n, e["product_name"], f"{e['price']:,}원",
        )
        divider_seg = work_dir / f"seg_divider{i}.mp4"
        _static_segment(divider_img, DIVIDER_DUR, divider_seg)
        pieces.append(divider_seg)
        pieces.append(clip_path)

        transition_img = longform_graphics.build_deepdive_transition(work_dir, i)
        transition_seg = work_dir / f"seg_transition{i}.mp4"
        _static_segment(transition_img, TRANSITION_DUR, transition_seg)
        pieces.append(transition_seg)

        frame_path = work_dir / f"frame{i}.jpg"
        _extract_frame(clip_path, frame_path)

        dd = deepdive_narration.generate_and_synthesize(
            e["product_name"], e["price"], _entry_specs(e), e["character"], work_dir, i,
        )
        caption_img = longform_graphics.build_deepdive_caption(
            work_dir, i, dd["narration"], dd["emphasis_words"],
        )
        deepdive_seg = work_dir / f"seg_deepdive{i}.mp4"
        _deepdive_segment(frame_path, caption_img, dd["audio_path"], dd["duration"] + DEEPDIVE_TAIL, deepdive_seg)
        pieces.append(deepdive_seg)

    outro_img = longform_graphics.build_outro_card(work_dir)
    outro_seg = work_dir / "seg_outro.mp4"
    _static_segment(outro_img, OUTRO_DUR, outro_seg)
    pieces.append(outro_seg)

    out_path = work_dir / "longform.mp4"
    _concat_pieces(pieces, out_path)
    return out_path


def build_title_and_description(entries: list, vol: int) -> tuple:
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


def _gather_batch(pending: list, work_dir: Path):
    """다운로드 가능한 항목만 골라 6개를 채운다.

    2026-09-01: 미리보기 렌더링 중 실제로 겪은 문제 — GCS 백업이 없고(그 날의
    upload_youtube.py _backup_to_gcs가 예외를 삼키고 경고만 남기는 실패 케이스) yt-dlp
    폴백도 유튜브 봇차단(429/"Sign in to confirm you're not a bot")에 걸려 영구히
    다운로드 불가능한 항목이 하나 있었다. 이런 항목을 그냥 pending[:6]으로 고정해
    버리면, 다운로드 불가 항목이 매번 배치에 포함돼 매 실행마다 5개를 헛수고로 다시
    처리하고 실패하는 걸 영원히 반복하게 된다 — 실패한 항목은 즉시
    compiled_in="SKIPPED_UNAVAILABLE"로 영구 마킹해 배치에서 빼고, 그다음 대기 항목으로
    6개를 채운다."""
    batch, clip_paths = [], {}
    skipped_any = False
    for e in pending:
        if len(batch) >= BATCH_SIZE:
            break
        clip_path = work_dir / f"clip_{e['video_id']}.mp4"
        try:
            download_short(e["video_id"], clip_path)
        except Exception as exc:
            print(f"[compile_longform] {e['video_id']}({e['product_name']}) 다운로드 실패, 영구 스킵: {exc}")
            e["compiled_in"] = "SKIPPED_UNAVAILABLE"
            skipped_any = True
            continue
        batch.append(e)
        clip_paths[e["video_id"]] = clip_path
    return batch, clip_paths, skipped_any


def check_and_compile():
    entries = shorts_log.load_log()
    pending = [e for e in entries if not e.get("compiled_in")]
    if len(pending) < BATCH_SIZE:
        print(f"[compile_longform] 아직 {len(pending)}/{BATCH_SIZE}개 — 대기")
        return None

    vol = next_volume_number()
    work_dir = REPO_ROOT / "work" / "longform" / f"vol{vol}"
    work_dir.mkdir(parents=True, exist_ok=True)

    batch, clip_paths, skipped_any = _gather_batch(pending, work_dir)
    if skipped_any:
        # 스킵 마킹은 배치 성사 여부와 무관하게 즉시 저장 — 다음 실행 때 같은 항목을
        # 또 시도하지 않게 하기 위함.
        shorts_log.save_log(entries)

    if len(batch) < BATCH_SIZE:
        print(f"[compile_longform] 다운로드 가능한 항목이 {len(batch)}/{BATCH_SIZE}개뿐 — 이번엔 대기")
        return None

    print(f"[compile_longform] {BATCH_SIZE}개 도달 — Vol.{vol} 롱폼 다이제스트 제작 시작")

    longform_path = build_longform(batch, clip_paths, work_dir, vol)
    title, description = build_title_and_description(batch, vol)
    result = upload_longform(longform_path, title, description)

    for e in batch:
        e["compiled_in"] = result["video_id"]
    shorts_log.save_log(entries)

    print(f"[compile_longform] 완료: {result['url']}")
    return result


if __name__ == "__main__":
    check_and_compile()
