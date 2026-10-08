"""쇼핑의천국 채널에 영상 업로드 (공개, 채널 ID 검증 포함).

환경변수(클라우드 환경에 설정됨): YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
"""
import argparse
import json
import os
import time
import desc_format
import requests

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
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


# 2026-10-08: 업로드 도중 "HttpError 410 Gone"으로 쇼츠가 통째로 미발행됨, 재실행에서는
# 같은 단계가 401 Invalid Credentials로 실패. 진단해보니 계정/토큰은 정상이었다(tokeninfo
# 스코프 4종, channels.list OK, requests로 직접 연 재개형 업로드 세션은 200). 실패한 건
# googleapiclient(httplib2) 업로드 경로였고, 그날 클라우드 환경의 pip이 다른 파이썬
# 버전으로 설치되면서 라이브러리 조합이 꼬여 있었다. 그래서 영상 업로드만은 검증된
# requests 경로로 직접 한다(YouTube 재개형 업로드 프로토콜 그대로).
#   - 16MB 단위로 PUT, 308이면 Range 헤더로 이어갈 위치를 받는다
#   - 5xx/연결 오류: 서버에 받은 위치를 물어보고 거기서부터 이어서
#   - 404/410: 세션 소실 → 새 세션으로 처음부터 (이 시점엔 영상이 아직 없어 중복 발행 없음)
#   - 401: 토큰 갱신 후 재시도
# 2026-10-08 저녁: 남자 쇼츠가 410을 4번 연속 받은 뒤, 새 세션을 열다 401로 끝났다.
# 세션 열기는 갱신 플래그를 무시하고 있었고, 재시도도 4번뿐이었다. 그래서
#   - 세션 열기에도 갱신 플래그를 적용하고, 세션이 사라지면(404/410) 토큰도 새로 받는다
#   - 재시도를 7번으로 늘리고 대기는 최대 60초
#   - 그래도 실패하면 예전 googleapiclient 경로로 한 번 더 올린다(다른 13개 채널이 쓰는 방식)
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
_CHUNK = 16 * 1024 * 1024  # 256KB의 배수여야 함
_SESSION_GONE = {404, 410}
_RETRYABLE = {500, 502, 503, 504}


class UploadError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(f"YouTube 업로드 HTTP {status}: {text[:500]}")
        self.status = status


def _auth(creds, force_refresh: bool = False) -> dict:
    if force_refresh or not creds.valid:
        creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}"}


def _start_session(creds, body: dict, size: int, force_refresh: bool = False) -> str:
    r = requests.post(_UPLOAD_URL, timeout=60, data=json.dumps(body).encode("utf-8"), headers={
        **_auth(creds, force_refresh),
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(size),
    })
    if r.status_code != 200 or "Location" not in r.headers:
        raise UploadError(r.status_code, r.text)
    return r.headers["Location"]


def _offset_from(r) -> int:
    rng = r.headers.get("Range")  # "bytes=0-12345"
    return int(rng.rsplit("-", 1)[1]) + 1 if rng else 0


def _query_offset(creds, session_url: str, size: int):
    """서버가 지금까지 받은 바이트 수를 묻는다. 이미 끝났으면 (None, 응답 JSON)."""
    r = requests.put(session_url, timeout=60, headers={
        **_auth(creds), "Content-Range": f"bytes */{size}", "Content-Length": "0"})
    if r.status_code in (200, 201):
        return None, r.json()
    if r.status_code == 308:
        return _offset_from(r), None
    raise UploadError(r.status_code, r.text)


def resumable_insert(creds, body: dict, video_path: str, max_attempts: int = 8) -> dict:
    try:
        return _requests_insert(creds, body, video_path, max_attempts)
    except (UploadError, requests.ConnectionError, requests.Timeout) as exc:
        print(f"[업로드] 직접 업로드 실패({exc}) — googleapiclient 경로로 한 번 더 시도")
    creds.refresh(Request())
    youtube = build("youtube", "v3", credentials=creds)
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"업로드 중... {int(status.progress() * 100)}%")
    return response


def _requests_insert(creds, body: dict, video_path: str, max_attempts: int) -> dict:
    size = os.path.getsize(video_path)
    session_url = None
    offset = 0
    attempt = 0
    force_refresh = False
    with open(video_path, "rb") as f:
        while True:
            try:
                if session_url is None:
                    session_url = _start_session(creds, body, size, force_refresh)
                    force_refresh = False
                    offset = 0
                f.seek(offset)
                chunk = f.read(_CHUNK)
                last = offset + len(chunk) - 1
                r = requests.put(session_url, data=chunk, timeout=600, headers={
                    **_auth(creds, force_refresh),
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{last}/{size}",
                })
                force_refresh = False
                if r.status_code in (200, 201):
                    print("업로드 중... 100%")
                    return r.json()
                if r.status_code == 308:
                    offset = _offset_from(r)
                    print(f"업로드 중... {int(offset * 100 / size)}%")
                    continue
                raise UploadError(r.status_code, r.text)
            except (UploadError, requests.ConnectionError, requests.Timeout) as exc:
                code = getattr(exc, "status", None)
                if code is not None and code not in _SESSION_GONE | _RETRYABLE | {401}:
                    raise
                attempt += 1
                if attempt >= max_attempts:
                    raise
                wait = min(10 * attempt, 60)
                print(f"[업로드] {exc} — {wait}초 후 재시도 ({attempt}/{max_attempts - 1})")
                time.sleep(wait)
                if code in _SESSION_GONE:
                    session_url = None  # 처음부터 새 세션
                    force_refresh = True
                    continue
                if code == 401:
                    force_refresh = True
                if session_url is not None:
                    try:
                        offset, done = _query_offset(creds, session_url, size)
                        if done is not None:
                            return done
                    except UploadError as qexc:
                        if qexc.status in _SESSION_GONE:
                            session_url = None
                    except (requests.ConnectionError, requests.Timeout):
                        pass


def upload(video_path: str, title: str, description: str, tags: list[str], coupang_url: str,
           rank: int | None = None) -> str:
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
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
