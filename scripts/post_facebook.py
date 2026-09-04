"""쇼핑의천국 페이스북 페이지("쇼핑의천국", Page ID 1314409945088774)에 영상을 발행.

환경변수: FACEBOOK_ACCESS_TOKEN
  - 페이지 관리자(강준구 계정)의 장기(long-lived, 60일) 사용자 액세스 토큰.
    pages_show_list, pages_manage_posts, pages_read_engagement, business_management
    권한 필요. shopping-paradise-secrets 저장소에 아직 토큰 파일이 없을 때만 쓰이는
    최초 시드값 — 이후로는 그 저장소(facebook_token.json)의 값을 우선 사용한다
    (인스타그램 토큰과 동일 패턴, secrets_store.py 참고).
  - 60일 만료 전에 자동 갱신된다: fb_exchange_token 그랜트로 현재 토큰을 다시
    교환하면 유효기간이 60일 더 연장된 새 토큰을 받을 수 있다(재인증 불필요,
    앱 시크릿만 있으면 됨 — facebook_token.json에 app_secret도 함께 저장되어
    있음). REFRESH_MIN_AGE_DAYS(40일)가 지나면 매 실행마다 자동으로 교환을
    시도한다 — 60일 만료 전에 여유있게 최소 한 번은 갱신되도록.

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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secrets_store  # noqa: E402

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
MEDIA_REPO_URL = "https://github.com/reintroka/shopping-paradise-media.git"
MEDIA_PAGES_BASE = "https://reintroka.github.io/shopping-paradise-media"
TOKEN_FILE = "facebook_token.json"
DEFAULT_PAGE_ID = "1314409945088774"  # "쇼핑의천국" Facebook 페이지
FACEBOOK_APP_ID = "1676158014013411"  # "쇼핑의천국 인스타그램 자동글쓰기" 앱 (공개 ID, 시크릿 아님)
# 페이스북 장기 사용자 토큰은 60일 유효. 매일 교환할 필요는 없어서(불필요한 API
# 호출만 늘어남) 40일로 잡아 60일 만료 전에 여유있게 갱신되도록 함(인스타그램의
# REFRESH_MIN_AGE_DAYS=30과 같은 목적, 2026-09-04 사용자 지시).
REFRESH_MIN_AGE_DAYS = 40


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


def refresh_long_lived_token(access_token: str, app_secret: str) -> str:
    result = _get(f"{GRAPH_BASE}/oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": FACEBOOK_APP_ID,
        "client_secret": app_secret, "fb_exchange_token": access_token,
    })
    return result["access_token"]


def get_valid_access_token() -> str:
    """secrets 저장소에서 현재 토큰을 읽고, REFRESH_MIN_AGE_DAYS 이상 지났으면
    fb_exchange_token으로 갱신 후 다시 저장한다(post_instagram.py와 동일 패턴).

    app_secret도 facebook_token.json에 함께 저장돼 있어야 한다 — 없으면(최초
    부트스트랩 직후) 갱신을 건너뛰고 기존 토큰을 그대로 쓴다.
    """
    state = secrets_store.load(TOKEN_FILE, bootstrap={
        "access_token": os.environ["FACEBOOK_ACCESS_TOKEN"], "obtained_at": None,
    })
    access_token = state["access_token"]
    obtained_at = state.get("obtained_at")
    app_secret = state.get("app_secret")

    if obtained_at is None:
        state["obtained_at"] = datetime.now(timezone.utc).isoformat()
        secrets_store.save(TOKEN_FILE, state)
        return access_token

    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(obtained_at)).total_seconds() / 86400
    if age_days < REFRESH_MIN_AGE_DAYS or not app_secret:
        return access_token

    try:
        new_token = refresh_long_lived_token(access_token, app_secret)
    except Exception as e:
        print(f"[post_facebook] 토큰 갱신 실패(기존 토큰으로 계속 진행): {e}")
        return access_token

    state["access_token"] = new_token
    state["obtained_at"] = datetime.now(timezone.utc).isoformat()
    secrets_store.save(TOKEN_FILE, state)
    print("[post_facebook] 액세스 토큰 자동 갱신 완료(60일 연장)")
    return new_token


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
    user_access_token = get_valid_access_token()
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
