"""임시 테스트 업로드 스크립트 — TTS 교체 확인용 영상을 비공개(private)로 업로드.
upload_youtube.upload()은 public으로 고정되어 있으므로 재사용하지 않고,
get_credentials()만 재사용해서 privacyStatus='private'로 직접 업로드 요청을 작성한다.

테스트 끝나면 이 파일과 test_assets/, work/는 지울 것.
"""
import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import upload_youtube  # noqa: E402

REPO_ROOT = HERE.parent
VIDEO_PATH = REPO_ROOT / "work" / "female" / "final_test.mp4"
TITLE = "[TEST] Google TTS 교체 확인용"


def upload_private(video_path: Path, title: str) -> str:
    creds = upload_youtube.get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
    actual_title = channel_resp["items"][0]["snippet"]["title"]
    if actual_title != upload_youtube.EXPECTED_CHANNEL_TITLE:
        raise RuntimeError(
            f"채널 불일치! 예상: {upload_youtube.EXPECTED_CHANNEL_TITLE}, 실제: {actual_title}. 업로드 중단."
        )
    print(f"[채널 확인] {actual_title}")

    body = {
        "snippet": {"title": title[:100], "description": "", "categoryId": "22"},
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"업로드 중... {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"업로드 완료 (private): https://youtu.be/{video_id}")
    return video_id


if __name__ == "__main__":
    if not VIDEO_PATH.exists():
        raise SystemExit(f"영상 파일 없음: {VIDEO_PATH}")
    vid = upload_private(VIDEO_PATH, TITLE)
    print(f"video_id={vid}")
