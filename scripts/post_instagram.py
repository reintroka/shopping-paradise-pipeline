"""shoppingparadise.kr 인스타그램에 Reels로 발행 (Instagram Graph API).

환경변수: IG_USER_ID, IG_ACCESS_TOKEN
  - IG_USER_ID: shoppingparadise.kr의 Instagram 비즈니스/크리에이터 계정 ID
  - IG_ACCESS_TOKEN: instagram_business_content_publish 권한이 있는 장기(long-lived) 토큰

Graph API의 Reels 발행(POST /{ig-user-id}/media, media_type=REELS)은 로컬 파일을
직접 업로드하는 방식이 아니라 "video_url"로 공개 URL을 넘겨주면 인스타그램 서버가
그 URL에서 직접 영상을 가져가는 방식이다. 이 파이프라인은 클라우드 샌드박스에서
돌아서 영상이 로컬에만 있으므로, GitHub Pages 정적 사이트(reintroka/shopping-paradise-media)
에 영상을 잠깐 올려 공개 URL을 만든 뒤 그 URL을 넘긴다(다음 실행 때 덮어써지므로
별도 삭제 스텝은 없음 — force push로 히스토리도 누적되지 않게 함).
"""
import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
MEDIA_REPO_URL = "https://github.com/reintroka/shopping-paradise-media.git"
MEDIA_PAGES_BASE = "https://reintroka.github.io/shopping-paradise-media"
MEDIA_FILENAME = "reel.mp4"  # 매번 같은 파일명을 덮어써서 저장소 크기를 일정하게 유지


def _http_error_with_body(e: urllib.error.HTTPError) -> RuntimeError:
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(응답 바디 읽기 실패)"
    return RuntimeError(f"HTTP {e.code}: {body}")


def _get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error_with_body(e) from None


def _post(url: str, params: dict) -> dict:
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error_with_body(e) from None


def publish_to_temp_host(video_path: Path) -> str:
    """영상을 shopping-paradise-media 저장소에 force push하고 GitHub Pages URL을 반환.

    히스토리를 쌓지 않기 위해 매번 얕은 클론 없이 새 커밋 하나만 만들어 force push한다
    (run_pipeline.py의 다른 저장소들과 달리 이 저장소는 순수 임시 호스팅 용도라
    fast-forward를 유지할 필요가 없음).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / MEDIA_FILENAME).write_bytes(video_path.read_bytes())
        (tmp_path / ".nojekyll").touch()
        subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", MEDIA_REPO_URL], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.email=bot@shopping-paradise.local",
             "-c", "user.name=shopping-paradise-bot", "commit", "-q", "-m", "temp host reel"],
            check=True,
        )
        subprocess.run(["git", "-C", str(tmp_path), "push", "--force", "origin", "HEAD:main"], check=True)
    return f"{MEDIA_PAGES_BASE}/{MEDIA_FILENAME}"


def wait_until_reachable(url: str, timeout_secs: int = 180) -> None:
    """GitHub Pages 배포에는 push 후 수십 초~수 분 정도 걸릴 수 있어서, 인스타그램에
    video_url을 넘기기 전에 실제로 그 URL이 응답하는지(200) 폴링으로 확인한다."""
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
    raise RuntimeError(f"GitHub Pages 영상 URL이 {timeout_secs}초 내에 응답하지 않음: {last_err}")


def create_reels_container(ig_user_id: str, access_token: str, video_url: str, caption: str) -> str:
    result = _post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        {"media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": access_token},
    )
    if "id" not in result:
        raise RuntimeError(f"컨테이너 생성 실패: {result}")
    return result["id"]


def wait_for_container_ready(container_id: str, access_token: str, timeout_secs: int = 300) -> None:
    """인스타그램이 video_url에서 영상을 내려받아 처리(FINISHED)할 때까지 폴링."""
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        result = _get(f"{GRAPH_BASE}/{container_id}", {"fields": "status_code", "access_token": access_token})
        status = result.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"인스타그램 영상 처리 실패: {result}")
        time.sleep(10)
    raise RuntimeError(f"인스타그램 영상 처리 시간 초과({timeout_secs}초)")


def publish_container(ig_user_id: str, access_token: str, container_id: str) -> dict:
    return _post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        {"creation_id": container_id, "access_token": access_token},
    )


def get_permalink(media_id: str, access_token: str) -> str:
    result = _get(f"{GRAPH_BASE}/{media_id}", {"fields": "permalink", "access_token": access_token})
    return result.get("permalink", "")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--caption", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    ig_user_id = os.environ["IG_USER_ID"]
    access_token = os.environ["IG_ACCESS_TOKEN"]

    video_url = publish_to_temp_host(Path(args.video))
    print(f"[post_instagram] 임시 호스팅 완료: {video_url}")
    wait_until_reachable(video_url)
    print("[post_instagram] GitHub Pages 배포 확인됨")

    container_id = create_reels_container(ig_user_id, access_token, video_url, args.caption)
    print(f"[post_instagram] 컨테이너 생성: {container_id}")
    wait_for_container_ready(container_id, access_token)
    print("[post_instagram] 영상 처리 완료(FINISHED)")

    publish_result = publish_container(ig_user_id, access_token, container_id)
    media_id = publish_result.get("id")
    if not media_id:
        raise RuntimeError(f"발행 실패: {publish_result}")

    permalink = get_permalink(media_id, access_token)
    result = {"media_id": media_id, "permalink": permalink}
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_instagram] 발행 완료: {permalink or media_id}")


if __name__ == "__main__":
    main()
