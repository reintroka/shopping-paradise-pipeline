"""3일치(하루 2개 x 3일 = 6개) 숏츠가 쌓이면 자동으로 롱폼 다이제스트로 제작+업로드.

2026-09-01 개편(v2): 기존엔 6개 숏츠를 하드컷으로 단순히 이어붙이기만 했음(v1).
사용자 요청으로 다른 13개 채널의 "리캡 롱폼" 패턴(챕터 디바이더+딥다이브 확장
나레이션+강조자막+인트로/아웃트로 카드)을 이식해 훨씬 풍성하게 재구성했다. 시각
톤은 새로 만들지 않고 이 채널 숏츠가 이미 쓰고 있는 골드 럭셔리 팔레트
(build_graphics.py)를 그대로 재사용해 통일감을 유지한다.

2026-09-01 밤 추가 개편(v2.1): v2 첫 렌더링본을 실제로 본 사용자가 "롱폼인데
숏폼(세로)으로 만들면 어떡하나"고 지적 — v2는 원본 숏츠가 세로(1080x1920)라는
이유로 최종 롱폼도 세로로 이어붙였는데, "롱폼"은 가로(1920x1080)여야 자연스럽다는
지적. 카드(인트로/디바이더/전환/아웃트로)는 longform_graphics.py에서 가로 전용으로
새로 설계했고, 세로 원본 숏츠 클립과 딥다이브 배경 스틸은 블러 배경+가운데 배치
(필러박스, longform_graphics.pillarbox_filter_complex)로 가로 캔버스 안에 앉힌다.

- 각 파이프라인 실행(run_pipeline.py) 끝에서 soft_step으로 호출됨 — 6개가 안 쌓였으면
  아무것도 안 하고 조용히 리턴(매번 호출해도 안전). 실패해도 예외가 soft_step에서
  잡히므로 숏츠 발행 자체는 막지 않는다 — 다음 실행 때 재시도됨(compiled_in 마킹은
  성공 시에만 저장되므로 안전).
- 이미 올라간 숏츠를 로컬에 안 남겨두므로(클라우드 실행은 매번 새 샌드박스), 우선
  GCS 백업 버킷(shopping-paradise-daily-raw-luith, upload_youtube.py가 발행 직후
  올려둠)에서 받고, 백업이 없는(백업 도입 이전 발행분) 경우에만 yt-dlp로 유튜브에서
  다시 내려받는다.
- 딥다이브 배경: shorts_log.json에 product_image(쿠팡 원본 상품사진 URL, 2026-09-01
  추가)가 있으면 그걸 내려받아 매거진 화보풍 레이아웃(longform_graphics.
  build_deepdive_product_backdrop)으로 예쁘게 보여준다 — 숏츠의 정사각 카드와는
  다른 새 디자인(사용자 지시: "쇼츠하고 똑같은 형식일 필요는 없다"). product_image가
  없는 옛 발행분(2026-09-01 이전)이나 다운로드 실패 시에는 기존 방식대로 다운로드한
  숏츠 클립에서 프레임을 뽑아 블러 필러박스 배경으로 폴백한다.
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
import google_tts
import longform_graphics
import shorts_log
import upload_youtube
from longform_graphics import LH, LW

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
    잘 보이는 구간)쯤에서 한 장 뽑는다. clip_path는 원본 세로(1080x1920) 다운로드본."""
    dur = _ffprobe_duration(clip_path)
    mid = max(0.5, min(dur - 0.3, dur * 0.35))
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i", str(clip_path),
         "-frames:v", "1", "-q:v", "2", str(out_path)])


def _pillarbox_clip(src_path: Path, out_path: Path):
    """세로(1080x1920) 원본 숏츠 클립을 가로(1920x1080) 롱폼 캔버스에 블러 배경+
    가운데 배치(필러박스)로 변환 — 오디오는 그대로 유지."""
    filter_txt = longform_graphics.pillarbox_filter_complex(border=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src_path),
         "-filter_complex", filter_txt, "-map", "[vout]", "-map", "0:a",
         "-r", str(FPS), "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
         str(out_path)])


def _build_deepdive_backdrop(frame_path: Path, out_path: Path):
    """딥다이브 배경 스틸도 클립과 동일한 필러박스 합성(블러 배경+가운데 배치)을 거쳐
    가로 캔버스에 맞춘 뒤, 이 결과 위에 Ken Burns 줌을 적용한다(_deepdive_segment).
    product_image가 없는 옛 발행분이나 상품사진 다운로드 실패 시에만 쓰는 폴백."""
    filter_txt = longform_graphics.pillarbox_filter_complex(border=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(frame_path),
         "-filter_complex", filter_txt, "-map", "[vout]",
         "-frames:v", "1", "-q:v", "2", str(out_path)])


def _fetch_gcs_product_image(video_id: str, out_path: Path) -> bool:
    """upload_youtube.backup_product_image()가 발행 시점에 영구 백업해둔 상품사진을
    가져온다(2026-09-02 도입) — 쿠팡 CDN URL이 만료되기 전에 이미 우리 버킷에 저장해둔
    원본이므로, 아래 _download_product_image()의 URL 재다운로드보다 항상 먼저
    시도한다. 옛 발행분(백업 도입 이전)엔 객체가 없으므로 그때만 False."""
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(upload_youtube.GCS_BACKUP_BUCKET)
        blob = bucket.blob(f"products/{video_id}.jpg")
        if not blob.exists():
            return False
        blob.download_to_filename(str(out_path))
        return True
    except Exception as exc:
        print(f"[compile_longform] GCS 상품사진 백업 조회 실패: {exc}")
        return False


def _download_product_image(url: str, out_path: Path) -> bool:
    """shorts_log.json에 저장된 쿠팡 원본 상품사진 URL을 내려받는다(GCS 백업이 없는
    옛 발행분 전용 폴백). 실패하면(URL 만료, 네트워크 오류 등) False를 반환해
    build_longform이 영상 프레임 캡처 폴백으로 넘어가게 한다."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            out_path.write_bytes(resp.read())
        return True
    except Exception as exc:
        print(f"[compile_longform] 상품사진 다운로드 실패, 영상 프레임으로 대체: {exc}")
        return False


def _static_segment(image_path: Path, duration: float, out_path: Path):
    run(["ffmpeg", "-y", "-v", "error",
         "-loop", "1", "-t", f"{duration:.2f}", "-i", str(image_path),
         "-f", "lavfi", "-t", f"{duration:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
         "-r", str(FPS), "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(out_path)])


def _narrated_static_segment(image_path: Path, narration_audio: Path, min_duration: float, out_path: Path):
    """정지 카드(인트로/아웃트로)에 나레이션 오디오를 얹는다(2026-09-05 추가 —
    기존엔 무음 정지카드였음, 사용자 요청으로 코어디웹 리캡롱폼과 동일하게
    멘트를 넣는다). 카드 표시시간은 나레이션 길이+0.6초 여유, min_duration보다
    짧아지지 않도록 하한을 둔다(나레이션이 아주 짧게 나올 경우 카드가 너무
    빨리 넘어가는 걸 방지). 나레이션이 min_duration보다 길면 apad 없이 그
    길이만큼 그대로 늘어난다."""
    audio_dur = _ffprobe_duration(narration_audio)
    total_dur = max(min_duration, audio_dur + 0.6)
    run(["ffmpeg", "-y", "-v", "error",
         "-loop", "1", "-t", f"{total_dur:.2f}", "-i", str(image_path),
         "-i", str(narration_audio),
         "-filter_complex", f"[1:a]apad=whole_dur={total_dur:.2f}[aout]",
         "-map", "0:v", "-map", "[aout]",
         "-r", str(FPS), "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
         "-t", f"{total_dur:.2f}",
         str(out_path)])


def _deepdive_segment(backdrop_path: Path, caption_specs: list, audio_path: Path, duration: float, out_path: Path):
    """backdrop_path는 이미 필러박스 합성이 끝난 가로(1920x1080) 스틸 — 그 위에 통째로
    Ken Burns 줌을 걸고, caption_specs(캡션이미지경로, 시작초, 끝초) 각각을 해당 구간에만
    enable='between(t,...)'로 오버레이한다. 2026-09-01 재설계: 기존엔 나레이션 전체를
    캡션 이미지 1장으로 만들어 20~30초 내내 고정 표시했음(사용자 지적: "긴 대사를 한
    화면으로 보여주나") — 오디오 트랙은 하나로 유지한 채 자막만 문장 단위로 페이지가
    넘어가도록 바꿨다(longform_graphics.split_narration_pages/allocate_page_durations로
    글자수 비례 타이밍 산출)."""
    zoom_frames = max(1, int(duration * FPS))
    filter_parts = [
        f"[0:v]scale={LW * 2}:{LH * 2},zoompan=z='min(zoom+0.0004,1.12)':d={zoom_frames}:s={LW}x{LH}:fps={FPS}[bgz];"
    ]
    cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(backdrop_path)]
    prev = "bgz"
    n = len(caption_specs)
    for i, (cap_path, start, end) in enumerate(caption_specs):
        cmd += ["-loop", "1", "-i", str(cap_path)]
        out_label = "vout" if i == n - 1 else f"v{i}"
        filter_parts.append(
            f"[{prev}][{i + 1}:v]overlay=(W-w)/2:900:enable='between(t,{start:.2f},{end:.2f})'[{out_label}];"
        )
        prev = out_label
    cmd += ["-i", str(audio_path)]
    audio_idx = n + 1
    filter_txt = "".join(filter_parts)
    cmd += ["-filter_complex", filter_txt, "-map", "[vout]", "-map", f"{audio_idx}:a",
            "-t", f"{duration:.2f}", "-r", str(FPS), "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
            str(out_path)]
    run(cmd)


def _normalized_pair(idx: int) -> str:
    return (
        f"[{idx}:v]fps={FPS},setsar=1,scale={LW}:{LH}[v{idx}];"
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
    intro_text = (
        f"이번 주 인기템 모음, 아이템 {n}개를 한 번에 몰아봅니다. "
        f"쇼핑의천국이 엄선한 오늘의 추천템, 지금 바로 시작할게요."
    )
    intro_audio = work_dir / "intro_narration.mp3"
    google_tts.synthesize(intro_text, "female", intro_audio)
    _narrated_static_segment(intro_img, intro_audio, INTRO_DUR, intro_seg)
    pieces.append(intro_seg)

    for i, e in enumerate(entries, start=1):
        clip_path = clip_paths[e["video_id"]]  # 원본 세로(1080x1920) 다운로드본

        divider_img = longform_graphics.build_chapter_divider(
            work_dir, i, n, e["product_name"], f"{e['price']:,}원",
        )
        divider_seg = work_dir / f"seg_divider{i}.mp4"
        _static_segment(divider_img, DIVIDER_DUR, divider_seg)
        pieces.append(divider_seg)

        landscape_clip = work_dir / f"clip_landscape{i}.mp4"
        _pillarbox_clip(clip_path, landscape_clip)
        pieces.append(landscape_clip)

        transition_img = longform_graphics.build_deepdive_transition(work_dir, i)
        transition_seg = work_dir / f"seg_transition{i}.mp4"
        _static_segment(transition_img, TRANSITION_DUR, transition_seg)
        pieces.append(transition_seg)

        product_jpg = work_dir / f"product{i}.jpg"
        got_photo = _fetch_gcs_product_image(e["video_id"], product_jpg)
        if not got_photo and e.get("product_image"):
            got_photo = _download_product_image(e["product_image"], product_jpg)

        backdrop_path = None
        if got_photo:
            backdrop_path = longform_graphics.build_deepdive_product_backdrop(
                work_dir, product_jpg, e["product_name"], f"{e['price']:,}원", i,
            )
        if backdrop_path is None:
            frame_path = work_dir / f"frame{i}.jpg"
            _extract_frame(clip_path, frame_path)
            backdrop_path = work_dir / f"backdrop{i}.jpg"
            _build_deepdive_backdrop(frame_path, backdrop_path)

        dd = deepdive_narration.generate_and_synthesize(
            e["product_name"], e["price"], _entry_specs(e), e["character"], work_dir, i,
        )
        pages = longform_graphics.split_narration_pages(dd["narration"])
        page_durs = longform_graphics.allocate_page_durations(pages, dd["duration"])
        caption_specs, t = [], 0.0
        for pi, (page_text, pdur) in enumerate(zip(pages, page_durs)):
            cap_img = longform_graphics.build_deepdive_caption(
                work_dir, f"{i}_{pi}", page_text, dd["emphasis_words"],
            )
            end = t + pdur + (DEEPDIVE_TAIL if pi == len(pages) - 1 else 0)
            caption_specs.append((cap_img, t, end))
            t += pdur

        deepdive_seg = work_dir / f"seg_deepdive{i}.mp4"
        _deepdive_segment(backdrop_path, caption_specs, dd["audio_path"], dd["duration"] + DEEPDIVE_TAIL, deepdive_seg)
        pieces.append(deepdive_seg)

    outro_img = longform_graphics.build_outro_card(work_dir)
    outro_seg = work_dir / "seg_outro.mp4"
    outro_text = (
        "오늘 소개해드린 아이템들은 프로필 링크에서 만나보실 수 있습니다. "
        "다음 다이제스트도 놓치지 마시고, 구독과 알림 설정 부탁드릴게요."
    )
    outro_audio = work_dir / "outro_narration.mp3"
    google_tts.synthesize(outro_text, "female", outro_audio)
    _narrated_static_segment(outro_img, outro_audio, OUTRO_DUR, outro_seg)
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


BASE_LONGFORM_TAGS = [
    "쇼핑하울", "제품추천", "가전추천", "생활템추천", "인기상품",
    "쿠팡추천", "가성비템", "신상품리뷰", "실속템", "온라인쇼핑",
]


def build_tags(entries: list) -> list[str]:
    """기존엔 태그가 3개(쇼핑하울/제품추천/가전추천)로 고정돼 있었다 — 검색 노출
    범위를 넓히려고 채널 공통 태그 10개에 이번 편에 실제로 다룬 상품명을 더한다."""
    tags, seen = [], set()
    for t in BASE_LONGFORM_TAGS + [e["product_name"][:20] for e in entries]:
        if t not in seen:
            seen.add(t)
            tags.append(t)
    return tags


def upload_longform(video_path: Path, title: str, description: str, tags: list[str],
                     thumbnail_path: Path | None = None) -> dict:
    creds = upload_youtube.get_credentials()
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=creds)
    channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
    actual_title = channel_resp["items"][0]["snippet"]["title"]
    if actual_title != upload_youtube.EXPECTED_CHANNEL_TITLE:
        raise RuntimeError(f"채널 불일치! 예상: {upload_youtube.EXPECTED_CHANNEL_TITLE}, 실제: {actual_title}")

    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "22"},
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

    # 기존엔 썸네일 설정 코드가 아예 없어서 유튜브가 영상에서 자동 선택한 프레임이
    # 그대로 노출되고 있었다 — 이미 만들어둔 인트로 카드(가로 1920x1080, 골드 럭셔리
    # 톤)를 그대로 재사용해 썸네일로 지정한다. 실패해도 업로드 자체는 이미 끝났으니
    # 예외를 삼키고 경고만 남긴다.
    if thumbnail_path and thumbnail_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/png"),
            ).execute()
            print(f"[compile_longform] 썸네일 설정 완료: {thumbnail_path.name}")
        except Exception as exc:
            print(f"[경고] 썸네일 설정 실패, 건너뜁니다: {exc}")

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
    tags = build_tags(batch)
    # 텍스트만 있는 인트로 카드를 그대로 썸네일로 쓰면 클릭률 관점에서 밋밋하다는
    # 지적(2026-09-02)으로, build_longform()이 이미 다운로드/추출해둔 상품 사진
    # (product{i}.jpg/frame{i}.jpg)을 콜라주로 보여주는 전용 썸네일로 교체.
    thumbnail_path = longform_graphics.build_thumbnail_collage(work_dir, batch, vol)
    result = upload_longform(longform_path, title, description, tags, thumbnail_path)

    for e in batch:
        e["compiled_in"] = result["video_id"]
    shorts_log.save_log(entries)

    # 2026-09-02: 숏츠는 run_pipeline.py 9단계에서 매번 유튜브 댓글로 쿠팡 링크를
    # 홍보하는데, 롱폼(compile_longform.py)에는 이 단계가 아예 빠져있었다(발견 계기:
    # 사용자 질문). 롱폼은 상품 하나가 아니라 6개를 묶은 다이제스트라 개별 쿠팡
    # 링크 하나로는 안 맞으므로, 전체 상품이 모여 있는 부업실험실 링크 페이지로
    # 유도한다. 댓글 실패가 이미 성공한 업로드/로그 저장에 영향 주지 않도록 여기서
    # 직접 예외를 삼킨다(run_pipeline.py soft_step과 동일한 원칙).
    try:
        comment_text = (
            "이 영상에서 소개한 상품들, 전체 링크는 여기서 한 번에 확인하세요 "
            "\U0001F449 https://reintroka.github.io/sidejoblab-links/"
        )
        subprocess.run(
            ["python3", str(HERE / "post_comment.py"), "--video-id", result["video_id"], "--text", comment_text],
            check=True,
        )
        print("[compile_longform] 유튜브 댓글 등록 완료")
    except Exception as exc:
        print(f"[경고] 롱폼 유튜브 댓글 등록 실패, 건너뜁니다: {exc}")

    print(f"[compile_longform] 완료: {result['url']}")
    return result


if __name__ == "__main__":
    check_and_compile()
