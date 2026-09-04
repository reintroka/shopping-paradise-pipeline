"""쇼핑의천국 페이스북 페이지("쇼핑의천국", Page ID 1314409945088774)에 영상을 발행.

환경변수: FACEBOOK_ACCESS_TOKEN
  - 페이지 관리자(강준구 계정)의 장기(long-lived) 사용자 액세스 토큰. pages_show_list,
    pages_manage_posts, pages_read_engagement 권한 필요. shopping-paradise-secrets
    저장소에 아직 토큰 파일이 없을 때만 쓰이는 최초 시드값 — 이후로는 그 저장소의
    값을 우선 사용한다(인스타그램 토큰과 동일 패턴, secrets_store.py 참고).
  - 인스타그램(ig_refresh_token)과 달리 페이스북 사용자 토큰은 간단한 자동 갱신
    엔드포인트가 없어서(재인증 없이는 60일 이상 연장 불가), 여기서는 자동 갱신을
    시도하지 않는다 — 만료되면 새 토큰을 발급해 secrets 저장소의 facebook_token.json을
    수동으로 갱신해야 한다.

발행 방식: 사용자 토큰으로 /me/accounts를 조회해 페이지 액세스 토큰을 얻은 뒤,
POST /{page-id}/videos에 file_url(공개 URL)을 넘긴다 — 인스타그램 릴스처럼 컨테이너
생성/폴링 2단계가 아니라 한 번의 호출로 끝난다(Graph API가 서버에서 직접 다운로드).
영상 임시 호스팅은 post_instagram.py와 동일하게 shopping-paradise-media 저장소를
쓰되, 파일명 접두사를 다르게 해서 동시 실행 시 충돌하지 않게 한다.
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

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
MEDIA_REPO_URL = "https://github.com/reintroka/shopping-paradise-media.git"
MEDIA_PAGES_BASE = "https://reintroka.github.io/shopping-paradise-media"
TOKEN_FILE = "facebook_token.json"
DEFAULT_PAGE_ID = "1314409945088774"  # "쇼핑의천국" Facebook 페이지


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

    post_instagram.py의 동명 함수와 동일한 이유(캐시 충돌 방지를 위한 타임스탬프
    파일명, force push로 히스토리 미누적)로 동작하되, 파일명 접두사를 "fb-"로 달리해
    같은 실행 사이클 안에서 인스타그램 업로드와 겹치지 않게 한다.
    """
    media_filename = f"fb-{int(time.time())}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / media_filename).write_bytes(video_path.read_bytes())
        (tmp_path / ".nojekyll").touch()
        subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", MEDIA_REPO_URL], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.email=bot@shopping-paradise.local",
             "-c", "user.name=shopping-paradise-bot", "commit", "-q", "-m", f"temp host {media_filename}"],
            check=True,
        )
        subprocess.run(["git", "-C", str(tmp_path), "push", "--force", "origin", "HEAD:main"], check=True)
    return f"{MEDIA_PAGES_BASE}/{media_filename}"


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
    raise RuntimeError(f"GitHub Pages 영상 URL이 {timeout_secs}초 내에 응답하지 않음: {last_err}")


def get_user_access_token() -> str:
    state = secrets_store.load(TOKEN_FILE, bootstrap={"access_token": os.environ["FACEBOOK_ACCESS_TOKEN"]})
    return state["access_token"]


def get_page_credentials(user_access_token: str, page_id: str) -> dict:
    """/me/accounts에서 관리 중인 페이지 목록을 조회해 지정된 page_id의 페이지
    액세스 토큰을 찾는다 — 페이지 토큰을 별도로 저장/갱신할 필요가 없어진다."""
    result = _get(f"{GRAPH_BASE}/me/accounts", {
        "fields": "id,name,access_token", "access_token": user_access_token,
    })
    pages = result.get("data", [])
    for page in pages:
        if page["id"] == page_id:
            return page
    raise RuntimeError(f"관리 중인 페이지 목록에서 page_id={page_id}를 찾을 수 없습니다: {pages}")


def publish_video(page_id: str, page_access_token: str, video_url: str, description: str) -> dict:
    return _post(f"{GRAPH_BASE}/{page_id}/videos", {
        "file_url": video_url, "description": description, "access_token": page_access_token,
    })


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--caption", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    page_id = os.environ.get("FACEBOOK_PAGE_ID", DEFAULT_PAGE_ID)
    user_access_token = get_user_access_token()
    page = get_page_credentials(user_access_token, page_id)
    print(f"[post_facebook] 타겟 페이지 확인: {page['name']} (ID: {page['id']})")

    video_url = publish_to_temp_host(Path(args.video))
    print(f"[post_facebook] 임시 호스팅 완료: {video_url}")
    wait_until_reachable(video_url)
    print("[post_facebook] GitHub Pages 배포 확인됨")

    result = publish_video(page["id"], page["access_token"], video_url, args.caption)
    video_id = result.get("id")
    if not video_id:
        raise RuntimeError(f"발행 실패: {result}")

    out = {"video_id": video_id, "page_name": page["name"]}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_facebook] 발행 완료: video_id={video_id}")


if __name__ == "__main__":
    main()
