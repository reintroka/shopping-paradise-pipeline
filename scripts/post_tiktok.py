"""shoppingparadise.kr 틱톡에 영상을 전달 (TikTok Content Posting API — Inbox 방식).

환경변수: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN

앱이 아직 TikTok 심사(audit)를 통과하지 않은 동안에는 "Direct Post"(바로 공개 발행)
권한(video.publish)을 쓸 수 없다. 대신 "Post to inbox" 방식(video.upload 권한, 심사
불필요)으로 영상을 계정의 틱톡 앱 받은편지함(초안함)에 전달하면, 계정 소유자가
틱톡 앱에서 알림을 열어 캡션/공개범위를 확인하고 직접 "게시"를 눌러야 최종 발행된다.
캡션은 이 스텝에서 API로 지정할 수 없다(inbox 방식 자체의 제약 — 필요하면 알림/로그에
캡션 문구를 같이 남겨서 사람이 붙여넣게 한다).

리프레시 토큰은 응답에서 매번 새 값으로 회전(rotate)되므로, 다음 실행을 위해
새 refresh_token을 state 파일에 남긴다(호출부에서 이 값을 다음 환경변수로 갱신해야 함).
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB, TikTok 허용 범위(5MB~64MB) 안에서 여유있게


def _http_error_with_body(e: urllib.error.HTTPError) -> RuntimeError:
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(응답 바디 읽기 실패)"
    return RuntimeError(f"HTTP {e.code}: {body}")


def refresh_access_token() -> dict:
    body = urllib.parse.urlencode({
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error_with_body(e) from None
    if "access_token" not in data:
        raise RuntimeError(f"토큰 갱신 실패: {data}")
    return data


def init_inbox_upload(access_token: str, video_size: int) -> dict:
    total_chunk_count = max(1, (video_size + CHUNK_SIZE - 1) // CHUNK_SIZE)
    chunk_size = video_size if total_chunk_count == 1 else CHUNK_SIZE
    body = json.dumps({
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        }
    }).encode("utf-8")
    req = urllib.request.Request(
        INBOX_INIT_URL, data=body,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error_with_body(e) from None
    if data.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"업로드 초기화 실패: {data}")
    return data["data"]


def upload_video(upload_url: str, video_path: Path, video_size: int) -> None:
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    total_chunk_count = max(1, (video_size + CHUNK_SIZE - 1) // CHUNK_SIZE)
    if total_chunk_count == 1:
        chunks = [(0, video_size - 1, video_bytes)]
    else:
        chunks = []
        for start in range(0, video_size, CHUNK_SIZE):
            end = min(start + CHUNK_SIZE, video_size) - 1
            chunks.append((start, end, video_bytes[start : end + 1]))

    for start, end, chunk in chunks:
        req = urllib.request.Request(
            upload_url, data=chunk, method="PUT",
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes {start}-{end}/{video_size}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            raise _http_error_with_body(e) from None


def check_status(access_token: str, publish_id: str) -> dict:
    body = json.dumps({"publish_id": publish_id}).encode("utf-8")
    req = urllib.request.Request(
        STATUS_URL, data=body,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error_with_body(e) from None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--caption-hint", default="", help="사람이 앱에서 최종 게시할 때 참고할 캡션 문구(로그/알림용, API로는 전달 안 됨)")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    video_path = Path(args.video)
    video_size = video_path.stat().st_size

    token_data = refresh_access_token()
    access_token = token_data["access_token"]

    init_data = init_inbox_upload(access_token, video_size)
    upload_video(init_data["upload_url"], video_path, video_size)

    # 처리 상태를 잠깐 확인(실패해도 치명적이지 않음 — 이미 업로드는 끝난 상태)
    time.sleep(5)
    status = None
    try:
        status = check_status(access_token, init_data["publish_id"])
    except Exception as e:
        print(f"[post_tiktok] 상태 조회 실패(무시 가능): {e}")

    result = {
        "publish_id": init_data["publish_id"],
        "status": status,
        "new_refresh_token": token_data.get("refresh_token"),  # 회전된 리프레시 토큰 — 다음 실행 전 환경변수 갱신 필요
        "caption_hint": args.caption_hint,
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_tiktok] 받은편지함(초안)으로 전달 완료: publish_id={init_data['publish_id']}")
    print("[post_tiktok] 틱톡 앱 알림에서 확인 후 직접 게시해야 최종 발행됩니다.")


if __name__ == "__main__":
    main()
