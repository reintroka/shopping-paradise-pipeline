"""쇼핑의천국 채널에 영상 업로드 (공개, 채널 ID 검증 포함).

환경변수(클라우드 환경에 설정됨): YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
"""
import argparse
import json
import os
import time
import desc_format

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

EXPECTED_CHANNEL_TITLE = "쇼핑의 천국"

AI_DISCLOSURE_TEXT = "이 영상은 AI를 활용해 제작한 순수 창작물입니다."
COUPANG_DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

GCS_BACKUP_BUCKET = "shopping-paradise-daily-raw-luith"

BASE_SHORT_TAGS = [
    "쇼핑하울", "제품추천", "가성비템", "신상품리뷰", "실속템",
    "온라인쇼핑", "꿀템", "쿠팡추천", "인기상품", "Shorts",
]


def build_tags(product: dict) -> list[str]:
    """기존엔 태그가 쇼핑하울/제품추천/Shorts 3개로 고정돼 있었다 — 검색 노출
    범위를 넓히려고 채널 공통 태그 10개에 이번 상품의 카테고리 키워드와 상품명을
    더한다."""
    tags, seen = [], set()
    candidates = BASE_SHORT_TAGS + [product.get("keyword", ""), product.get("productName", "")[:20]]
    for t in candidates:
        # run_pipeline.py가 이 리스트를 ",".join()해서 --tags로 넘기므로, 상품명에 든
        # 쉼표(예: "..., White, 1개")가 태그를 잘못 쪼개지 않도록 미리 제거한다.
        t = t.replace(",", " ").strip()
        if t and t not in seen:
            seen.add(t)
            tags.append(t)
    return tags


def _backup_to_gcs(video_id: str, local_path: str) -> None:
    """업로드 성공한 mp4를 video_id 키로 GCS에 백업(3일 후 자동삭제 — 버킷
    라이프사이클 규칙으로 처리). 다른 채널들(latte-nk-daily-raw-luith 등)과 동일한
    목적 — compile_longform.py가 클라우드 샌드박스 IP에서 yt-dlp로 유튜브를 재다운로드
    하다가 봇차단(429/Sign in to confirm)에 걸리는 걸 애초에 피한다. 실패해도 업로드
    자체는 이미 끝났으니 예외를 삼키고 경고만 남긴다."""
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(GCS_BACKUP_BUCKET)
        blob = bucket.blob(f"{video_id}.mp4")
        blob.upload_from_filename(local_path, content_type="video/mp4")
        print(f"[gcs백업] {video_id}.mp4 업로드 완료 (gs://{GCS_BACKUP_BUCKET}/{video_id}.mp4)")
    except Exception as exc:
        print(f"[경고] GCS 백업 실패, 건너뜁니다: {exc}")


def backup_product_image(video_id: str, local_path) -> None:
    """숏폼 발행 시점에 이미 로컬로 내려받아둔 쿠팡 상품사진(product_image_path)을
    같은 버킷(products/ 프리픽스)에 영구 백업. 기존엔 shorts_log.json에 쿠팡 원본
    URL만 저장해뒀다가 롱폼 제작 시점(최대 3일 뒤)에 재다운로드했는데, 쿠팡 CDN URL이
    그 사이 만료되거나 네트워크 오류가 나면 실패했다(사용자 지적: "작업 시 들어간
    이미지를 저장해두면 되잖아, 나중에 다시 호출할 필요 없이"). 이 버킷은 이미
    7일 라이프사이클이라 3일 주기 롱폼 제작 전에 지워질 위험은 없다. 실패해도 발행
    자체는 이미 끝났으니 예외를 삼키고 경고만 남긴다."""
    try:
        from google.cloud import storage

        client = storage.Client()
        bucket = client.bucket(GCS_BACKUP_BUCKET)
        blob = bucket.blob(f"products/{video_id}.jpg")
        blob.upload_from_filename(str(local_path), content_type="image/jpeg")
        print(f"[gcs백업] products/{video_id}.jpg 업로드 완료")
    except Exception as exc:
        print(f"[경고] 상품사진 GCS 백업 실패, 건너뜁니다: {exc}")


def get_credentials():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


# 2026-10-08: 410 Gone / 간헐적 401로 하루 종일 실패. 낮에 업로드를 requests 직접 호출로
# 바꿨었는데, 사용자 요청("다른 채널하고 방식을 같게")으로 다른 13개 채널과 똑같은
# googleapiclient 재개형 업로드(_resumable_insert)로 되돌렸다. 다른 채널 방식 그대로:
#   - 404/410: 세션 소실 → insert 요청을 새로 만들어 처음부터 (이 시점엔 영상이 없어 중복 없음)
#   - 5xx: 같은 세션에서 next_chunk 다시
#   - 401: 토큰 새로 받아 처음부터
# 다만 이 환경은 밤 진단에서 같은 토큰으로 channels.list 24번 중 14번이 401이었으므로
# (요청마다 들쭉날쭉) 재시도 횟수만 다른 채널보다 넉넉히(12회, 401은 3초 간격) 둔다.
_SESSION_GONE = {404, 410}
_RETRYABLE = {500, 502, 503, 504}
_AUTH_RETRIES = 12


def execute_401_retry(make_request, what: str = "YouTube API"):
    """make_request()로 만든 요청을 execute()하되, 401이면 3초 뒤 다시 만든다."""
    for i in range(_AUTH_RETRIES):
        try:
            return make_request().execute()
        except HttpError as exc:
            if exc.resp.status != 401 or i == _AUTH_RETRIES - 1:
                raise
            print(f"[{what}] 401 — 3초 후 재시도 ({i + 1}/{_AUTH_RETRIES - 1})")
            time.sleep(3)


def _refresh_upload_credentials(creds) -> None:
    try:
        creds.refresh(Request())
    except Exception as exc:  # noqa: BLE001 - 갱신 실패면 그대로 재시도(마지막 시도에서 원래 오류가 올라감)
        print(f"[업로드] 토큰 갱신 실패: {exc}")


def resumable_insert(creds, body: dict, video_path: str, max_attempts: int = _AUTH_RETRIES) -> dict:
    youtube = build("youtube", "v3", credentials=creds)

    def new_request():
        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
        return youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    request = new_request()
    response = None
    attempt = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"업로드 중... {int(status.progress() * 100)}%")
        except HttpError as exc:
            code = exc.resp.status
            if code not in _SESSION_GONE and code not in _RETRYABLE and code != 401:
                raise
            attempt += 1
            if attempt >= max_attempts:
                raise
            wait = 3 if code == 401 else min(10 * attempt, 60)
            if code == 401:
                print(f"[업로드] HTTP 401 — 토큰 새로 받아 {wait}초 후 처음부터 재시도 ({attempt}/{max_attempts - 1})")
                time.sleep(wait)
                _refresh_upload_credentials(creds)
                request = new_request()
            elif code in _SESSION_GONE:
                print(f"[업로드] HTTP {code} — 업로드 세션 소실, {wait}초 후 처음부터 재시도 ({attempt}/{max_attempts - 1})")
                time.sleep(wait)
                request = new_request()
            else:
                print(f"[업로드] HTTP {code} — {wait}초 후 이어서 재시도 ({attempt}/{max_attempts - 1})")
                time.sleep(wait)
    cleanup_orphan_uploads(youtube, body["snippet"]["title"], keep_id=response["id"])
    return response


# 2026-10-09: 10/8 401/410 폭주 때 끊긴 업로드 시도마다 파일 없는 빈 영상이 Studio
# '임시저장'에 "곧 처리 시작됨"으로 남았다(같은 제목 여러 개). 업로드 성공 직후 같은
# 제목이면서 처리 완료(processed)가 아닌 다른 영상 = 끊긴 시도의 껍데기로 보고 지운다.
# 정상 공개된 예전 영상은 uploadStatus가 processed라 같은 제목이어도 건드리지 않는다.
# 정리 실패는 업로드 결과에 영향 없도록 경고만 남긴다.
_ORPHAN_LOOKBACK = 25
_UPLOADED_THIS_RUN: set = set()  # 이번 실행에서 정상 업로드된 영상은 같은 제목이어도 절대 지우지 않는다


def find_orphan_uploads(youtube, title: str | None, keep_id: str | None = None) -> list[dict]:
    """최근 업로드 중 처리 완료가 아닌 영상. title을 주면 같은 제목만."""
    ch = execute_401_retry(lambda: youtube.channels().list(part="contentDetails", mine=True), "업로드 목록")
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = execute_401_retry(lambda: youtube.playlistItems().list(
        part="contentDetails", playlistId=uploads, maxResults=_ORPHAN_LOOKBACK), "업로드 목록")
    ids = [it["contentDetails"]["videoId"] for it in items.get("items", [])]
    ids = [i for i in ids if i != keep_id and i not in _UPLOADED_THIS_RUN]
    if not ids:
        return []
    vids = execute_401_retry(lambda: youtube.videos().list(
        part="snippet,status,processingDetails", id=",".join(ids)), "업로드 상태")
    out = []
    for v in vids.get("items", []):
        if v["status"].get("uploadStatus") != "uploaded":  # 처리 중에 멈춘 것만. 거부·실패 영상은 건드리지 않음
            continue
        if title is not None and v["snippet"].get("title", "").strip() != title.strip():
            continue
        out.append(v)
    return out


def cleanup_orphan_uploads(youtube, title: str, keep_id: str) -> None:
    _UPLOADED_THIS_RUN.add(keep_id)
    try:
        orphans = find_orphan_uploads(youtube, title, keep_id)
        for v in orphans:
            execute_401_retry(lambda: youtube.videos().delete(id=v["id"]), "빈 영상 삭제")
            print(f"[업로드] 끊긴 시도의 빈 영상 삭제: {v['id']} ({v['status'].get('uploadStatus')})")
    except Exception as exc:  # noqa: BLE001
        print(f"[경고] 빈 영상 정리 실패, 건너뜁니다: {exc}")


def upload(video_path: str, title: str, description: str, tags: list[str], coupang_url: str,
           rank: int | None = None) -> str:
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    channel_resp = execute_401_retry(lambda: youtube.channels().list(part="snippet", mine=True), "채널 확인")
    actual_title = channel_resp["items"][0]["snippet"]["title"]
    if actual_title != EXPECTED_CHANNEL_TITLE:
        raise RuntimeError(f"채널 불일치! 예상: {EXPECTED_CHANNEL_TITLE}, 실제: {actual_title}. 업로드 중단.")
    print(f"[채널 확인] {actual_title}")

    # 2026-09-10: 사용자 요청 — 나중에 부업실험실 링크 페이지에서 번호로 다시 찾을 수
    # 있게, 설명란 맨 앞(가장 눈에 띄는 자리)에 순번을 강조. rank가 없으면(링크 페이지
    # 업데이트 실패) 존재하지 않는 번호를 안내하지 않도록 통째로 생략.
    rank_line = f"\U0001F50E [No.{rank}] 프로필 링크에서 이 번호로 검색하면 다시 찾을 수 있어요\n\n" if rank is not None else ""
    full_description = (
        f"{rank_line}"
        f"{description}\n\n"
        f"\U0001F517 상품 확인: {coupang_url}\n\n"
        f"{COUPANG_DISCLOSURE}\n{AI_DISCLOSURE_TEXT}\n\n"
        f"#쇼핑하울 #제품추천 #Shorts"
    )

    body = {
        "snippet": {"title": title[:100], "description": desc_format.format_description(full_description), "tags": tags, "categoryId": "22"},
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    response = resumable_insert(creds, body, video_path)

    video_id = response["id"]
    print(f"업로드 완료 (public): https://youtu.be/{video_id}")
    _backup_to_gcs(video_id, video_path)
    return video_id


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--tags", required=True, help="쉼표로 구분된 태그")
    p.add_argument("--coupang-url", required=True)
    p.add_argument("--rank", type=int, default=None, help="부업실험실 링크 페이지 순번 (없으면 설명란 번호 문구 생략)")
    p.add_argument("--out", required=True, help="video_id를 저장할 파일 경로")
    args = p.parse_args()

    vid = upload(args.video, args.title, args.description, args.tags.split(","), args.coupang_url, rank=args.rank)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"video_id": vid, "url": f"https://youtu.be/{vid}"}, f, ensure_ascii=False, indent=2)
