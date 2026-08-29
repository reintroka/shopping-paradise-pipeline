"""쇼핑의천국 채널에 영상 업로드 (공개, 채널 ID 검증 포함).

환경변수(클라우드 환경에 설정됨): YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
"""
import argparse
import json
import os

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


def upload(video_path: str, title: str, description: str, tags: list[str], coupang_url: str) -> str:
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
    actual_title = channel_resp["items"][0]["snippet"]["title"]
    if actual_title != EXPECTED_CHANNEL_TITLE:
        raise RuntimeError(f"채널 불일치! 예상: {EXPECTED_CHANNEL_TITLE}, 실제: {actual_title}. 업로드 중단.")
    print(f"[채널 확인] {actual_title}")

    full_description = (
        f"{description}\n\n"
        f"\U0001F517 상품 확인: {coupang_url}\n\n"
        f"{COUPANG_DISCLOSURE}\n{AI_DISCLOSURE_TEXT}\n\n"
        f"#쇼핑하울 #제품추천 #Shorts"
    )

    body = {
        "snippet": {"title": title[:100], "description": full_description, "tags": tags, "categoryId": "22"},
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"업로드 중... {int(status.progress() * 100)}%")

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
    p.add_argument("--out", required=True, help="video_id를 저장할 파일 경로")
    args = p.parse_args()

    vid = upload(args.video, args.title, args.description, args.tags.split(","), args.coupang_url)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"video_id": vid, "url": f"https://youtu.be/{vid}"}, f, ensure_ascii=False, indent=2)
