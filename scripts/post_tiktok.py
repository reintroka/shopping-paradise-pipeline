"""shoppingparadise.kr 틱톡에 영상/카드뉴스를 전달 (TikTok Content Posting API — Inbox 방식).

환경변수: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN

앱이 아직 TikTok 심사(audit)를 통과하지 않은 동안에는 "Direct Post"(바로 공개 발행)
권한(video.publish)을 쓸 수 없다. 대신 "Post to inbox" 방식(video.upload 권한, 심사
불필요)으로 영상을 계정의 틱톡 앱 받은편지함(초안함)에 전달하면, 계정 소유자가
틱톡 앱에서 알림을 열어 캡션/공개범위를 확인하고 직접 "게시"를 눌러야 최종 발행된다.
캡션은 이 스텝에서 API로 지정할 수 없다(inbox 방식 자체의 제약 — 필요하면 알림/로그에
캡션 문구를 같이 남겨서 사람이 붙여넣게 한다).

리프레시 토큰은 응답에서 매번 새 값으로 회전(rotate)된다 — 예전 값은 그 즉시 무효가
되므로, 환경변수(TIKTOK_REFRESH_TOKEN)를 매번 손으로 갱신하는 대신 shopping-paradise-secrets
(비공개 저장소)에 최신 값을 저장/조회한다(2026-09-01, "만료 없이 되도록" 요청으로 도입).
shopping-paradise-pipeline 저장소 자체는 public이라 토큰을 절대 거기 커밋하면 안 됨.
환경변수는 secrets 저장소에 아직 파일이 없을 때만 쓰이는 최초 시드값이다.

2026-09-18 추가(--mode photo): 카드뉴스(3장)도 틱톡 "사진 모드" 받은편지함으로
전달한다(사용자 지시 — "쓰레드만 발행하지 말고.. 할수 있는곳에는 다 발행해", 이어서
"릴스하고 똑같이 넣을수 있어?"). 영상 inbox는 FILE_UPLOAD(직접 바이트 청크 업로드)
방식만 쓰는데, 이 앱의 심사(audit) 등급이 그 방식만 허용하는 것으로 보여(video
쪽이 이미 그렇게 구현돼 있음) 사진도 같은 등급 제약을 받을 가능성이 있다 — 다만
TikTok 공식 문서상 사진 inbox는 PULL_FROM_URL(공개 URL을 틱톡 서버가 직접 가져가는
방식, 다른 플랫폼 임시 호스팅과 동일한 패턴)이 표준 경로라 이 방식으로 구현했다.
**주의**: 실제 계정으로 아직 검증 못 함 — 이 앱의 심사 등급이 PULL_FROM_URL을 거부하면
(사람이 실제로 시도해봐야 확인 가능) 이 스텝만 실패하고 나머지 플랫폼 발행에는 영향
없다(run_cards.py에서 try/except로 감쌈).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secrets_store  # noqa: E402

TOKEN_FILE = "tiktok_token.json"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
CONTENT_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/content/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
MEDIA_REPO_URL = "https://github.com/reintroka/shopping-paradise-media.git"
MEDIA_PAGES_BASE = "https://reintroka.github.io/shopping-paradise-media"
CHUNK_SIZE = 10 * 1024 * 1024  # 여러 청크로 나눌 때 쓰는 기본 청크 크기(TikTok 허용 범위 5MB~64MB 안)
MIN_CHUNK_SIZE = 5 * 1024 * 1024  # TikTok 최소 청크 크기(마지막 청크는 예외)
SINGLE_CHUNK_MAX_VIDEO_SIZE = 64 * 1024 * 1024  # 이 이하 영상은 TikTok 규칙상 반드시 단일 청크


def _http_error_with_body(e: urllib.error.HTTPError) -> RuntimeError:
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(응답 바디 읽기 실패)"
    return RuntimeError(f"HTTP {e.code}: {body}")


def refresh_access_token() -> dict:
    """secrets 저장소의 최신 refresh_token으로 access_token을 발급받고, 응답에 담긴
    새로 회전된 refresh_token을 즉시 secrets 저장소에 반영한다(다음 실행이 옛 값으로
    실패하지 않도록)."""
    state = secrets_store.load(TOKEN_FILE, bootstrap={
        "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
    })
    body = urllib.parse.urlencode({
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": state["refresh_token"],
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
    if data.get("refresh_token"):
        secrets_store.save(TOKEN_FILE, {"refresh_token": data["refresh_token"]})
    return data


def _plan_chunks(video_size: int) -> tuple[int, int]:
    """TikTok 청크 규칙에 맞는 (chunk_size, total_chunk_count)를 계산한다.
    - 영상이 64MB 이하면 반드시 단일 청크(chunk_size=video_size)여야 한다.
    - 64MB를 초과하면 CHUNK_SIZE 단위로 나누되, 마지막 청크가 최소 청크 크기(5MB)보다
      작아지지 않도록 청크 수를 조정한다(마지막 청크만 더 커지는 것은 허용됨)."""
    if video_size <= SINGLE_CHUNK_MAX_VIDEO_SIZE:
        return video_size, 1
    total_chunk_count = video_size // CHUNK_SIZE
    remainder = video_size - total_chunk_count * CHUNK_SIZE
    if remainder == 0:
        pass
    elif remainder < MIN_CHUNK_SIZE:
        total_chunk_count -= 1  # 남는 조각을 마지막 청크에 합침
    else:
        total_chunk_count += 1
    return CHUNK_SIZE, total_chunk_count


def init_inbox_upload(access_token: str, video_size: int) -> dict:
    chunk_size, total_chunk_count = _plan_chunks(video_size)
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
    result = data["data"]
    # upload_video가 여기서 실제로 쓴 chunk_size/total_chunk_count를 그대로 넘겨받아
    # 동일한 기준으로 청크 경계를 계산하도록 함께 반환한다(중복 계산으로 인한 불일치 방지).
    result["chunk_size"] = chunk_size
    result["total_chunk_count"] = total_chunk_count
    return result


def upload_video(upload_url: str, video_path: Path, video_size: int, chunk_size: int, total_chunk_count: int) -> None:
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    chunks = []
    for i in range(total_chunk_count):
        start = i * chunk_size
        end = min(start + chunk_size, video_size) - 1
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


def publish_images_to_temp_host(image_paths: list) -> list:
    """카드뉴스 이미지를 한 커밋에 모아 한 번에 force push(다른 플랫폼 스크립트와
    동일한 이유 — 개별 force push하면 앞 이미지의 URL이 지워짐)."""
    ts = int(time.time())
    filenames = [f"tt-card{i}-{ts}.png" for i in range(1, len(image_paths) + 1)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for filename, local_path in zip(filenames, image_paths):
            (tmp_path / filename).write_bytes(Path(local_path).read_bytes())
        (tmp_path / ".nojekyll").touch()
        subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", MEDIA_REPO_URL], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.email=bot@shopping-paradise.local",
             "-c", "user.name=shopping-paradise-bot", "commit", "-q", "-m", f"temp host {len(filenames)} file(s)"],
            check=True,
        )
        subprocess.run(["git", "-C", str(tmp_path), "push", "--force", "origin", "HEAD:main"], check=True)
    return [f"{MEDIA_PAGES_BASE}/{f}" for f in filenames]


def wait_until_reachable(url: str, timeout_secs: int = 180) -> None:
    deadline = time.time() + timeout_secs
    last_err = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return
        except Exception as e:
            last_err = e
        time.sleep(5)
    raise RuntimeError(f"GitHub Pages URL이 {timeout_secs}초 내에 응답하지 않음: {url} ({last_err})")


def init_photo_inbox(access_token: str, image_urls: list) -> dict:
    """TikTok 공식 문서상 사진 inbox의 표준 경로(PULL_FROM_URL) — 검증 안 됨, 위
    모듈 docstring 참고."""
    body = json.dumps({
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": image_urls,
        },
        "post_mode": "MEDIA_UPLOAD",
        "media_type": "PHOTO",
    }).encode("utf-8")
    req = urllib.request.Request(
        CONTENT_INIT_URL, data=body,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error_with_body(e) from None
    if data.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"사진 inbox 초기화 실패: {data}")
    return data["data"]


def post_video(video_path, caption_hint, out_path):
    video_path = Path(video_path)
    video_size = video_path.stat().st_size

    token_data = refresh_access_token()
    access_token = token_data["access_token"]

    init_data = init_inbox_upload(access_token, video_size)
    upload_video(
        init_data["upload_url"], video_path, video_size,
        init_data["chunk_size"], init_data["total_chunk_count"],
    )

    # 처리 상태를 잠깐 확인(실패해도 치명적이지 않음 — 이미 업로드는 끝난 상태)
    time.sleep(5)
    status = None
    try:
        status = check_status(access_token, init_data["publish_id"])
    except Exception as e:
        print(f"[post_tiktok:video] 상태 조회 실패(무시 가능): {e}")

    result = {"publish_id": init_data["publish_id"], "status": status, "caption_hint": caption_hint}
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_tiktok:video] 받은편지함(초안)으로 전달 완료: publish_id={init_data['publish_id']}")
    print("[post_tiktok:video] 틱톡 앱 알림에서 확인 후 직접 게시해야 최종 발행됩니다.")


def post_photo(image_paths, caption_hint, out_path):
    image_urls = publish_images_to_temp_host([Path(p) for p in image_paths])
    print(f"[post_tiktok:photo] 임시 호스팅 완료: {image_urls}")
    for url in image_urls:
        wait_until_reachable(url)
    print("[post_tiktok:photo] GitHub Pages 배포 확인됨")

    token_data = refresh_access_token()
    access_token = token_data["access_token"]

    init_data = init_photo_inbox(access_token, image_urls)
    publish_id = init_data["publish_id"]

    time.sleep(5)
    status = None
    try:
        status = check_status(access_token, publish_id)
    except Exception as e:
        print(f"[post_tiktok:photo] 상태 조회 실패(무시 가능): {e}")

    result = {"publish_id": publish_id, "status": status, "caption_hint": caption_hint}
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_tiktok:photo] 받은편지함(초안)으로 전달 완료: publish_id={publish_id}")
    print("[post_tiktok:photo] 틱톡 앱 알림에서 확인 후 직접 게시해야 최종 발행됩니다.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["video", "photo"], default="video")
    p.add_argument("--video")
    p.add_argument("--images", help="사진 모드 이미지 경로를 콤마로 구분해서 전달")
    p.add_argument("--caption-hint", default="", help="사람이 앱에서 최종 게시할 때 참고할 캡션 문구(로그/알림용, API로는 전달 안 됨)")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if args.mode == "video":
        if not args.video:
            raise SystemExit("--mode video 에는 --video가 필요합니다")
        post_video(args.video, args.caption_hint, args.out)
    elif args.mode == "photo":
        if not args.images:
            raise SystemExit("--mode photo 에는 --images가 필요합니다")
        image_paths = [s.strip() for s in args.images.split(",") if s.strip()]
        post_photo(image_paths, args.caption_hint, args.out)


if __name__ == "__main__":
    main()
