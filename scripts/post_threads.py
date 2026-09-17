"""shoppingparadise.kr 쓰레드(Threads)에 영상을 발행 (Threads API).

환경변수: THREADS_USER_ID, THREADS_ACCESS_TOKEN
  - THREADS_USER_ID: shoppingparadise.kr의 Threads 사용자 ID (graph.threads.net/me로 확인)
  - THREADS_ACCESS_TOKEN: threads_basic, threads_content_publish 권한이 있는 장기
    (long-lived, 60일) 토큰 — shopping-paradise-secrets 저장소에 아직 토큰 파일이 없을
    때만 쓰이는 최초 시드값. 이후로는 매 실행마다 그 저장소의 값을 읽고,
    REFRESH_MIN_AGE_DAYS(30일)만큼 지났으면 자동 갱신해서 다시 저장한다
    (post_instagram.py와 동일 패턴, secrets_store.py 참고).

**2026-09-18: 계정을 막 만든 상태라 며칠간 자동 발행을 켜지 않기로 함(사용자 지시,
신규 계정이 바로 대량 자동 게시하면 계정 삭제 위험이 있다는 우려). THREADS_USER_ID/
THREADS_ACCESS_TOKEN 클라우드 환경변수를 등록하지 않는 한 이 스크립트는 절대
호출되지 않는다 — run_pipeline.py가 실행 전에 두 환경변수 존재를 먼저 확인하고,
없으면 "비활성화"로 조용히 건너뛴다(실패로 취급 안 함, 텔레그램에 매번 실패 알림이
쌓이지 않게). 계정이 안정됐다고 판단되면 클라우드 환경변수만 채우면 코드 변경 없이
바로 켜진다.

발행 방식: 인스타그램 릴스와 동일하게 컨테이너 생성(media_type=VIDEO) → 처리 완료
폴링 → 발행(creation_id) 2단계. 영상은 로컬에만 있으므로 post_instagram.py와 동일한
GitHub Pages 임시 호스팅(shopping-paradise-media)을 거쳐 공개 URL을 넘긴다. 파일명
접두사는 "th-"로 달리해 같은 실행 사이클의 인스타/페이스북 업로드와 충돌하지 않게 한다.
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

GRAPH_API_VERSION = "v1.0"
GRAPH_BASE = f"https://graph.threads.net/{GRAPH_API_VERSION}"
MEDIA_REPO_URL = "https://github.com/reintroka/shopping-paradise-media.git"
MEDIA_PAGES_BASE = "https://reintroka.github.io/shopping-paradise-media"
TOKEN_FILE = "threads_token.json"
# 쓰레드 장기 토큰도 인스타그램과 동일하게 60일 유효. 24시간 이후부터 갱신 가능하지만
# 매일 갱신할 이유가 없어 30일로 잡음(post_instagram.py의 REFRESH_MIN_AGE_DAYS와 동일 근거).
REFRESH_MIN_AGE_DAYS = 30
REFRESH_MIN_AGE_HOURS = REFRESH_MIN_AGE_DAYS * 24


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
    파일명)로 동작하되, 파일명 접두사를 "th-"로 달리해 같은 실행 사이클 안에서
    인스타그램/페이스북 업로드와 겹치지 않게 한다.
    """
    media_filename = f"th-{int(time.time())}.mp4"
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


def refresh_long_lived_token(access_token: str) -> dict:
    return _get(f"{GRAPH_BASE}/refresh_access_token", {
        "grant_type": "th_refresh_token", "access_token": access_token,
    })


def get_valid_access_token() -> str:
    """secrets 저장소에서 현재 토큰을 읽고, REFRESH_MIN_AGE_HOURS 이상 지났으면 갱신 후
    다시 저장한다(post_instagram.py의 get_valid_access_token과 동일 패턴).

    갱신 실패는 치명적 에러로 취급하지 않고 기존 토큰을 그대로 쓴다 — 발행 자체가
    막히면 안 되고, 다음 실행에서 다시 시도하면 된다.
    """
    state = secrets_store.load(TOKEN_FILE, bootstrap={
        "access_token": os.environ["THREADS_ACCESS_TOKEN"], "obtained_at": None,
    })
    access_token = state["access_token"]
    obtained_at = state.get("obtained_at")

    if obtained_at is None:
        state["obtained_at"] = datetime.now(timezone.utc).isoformat()
        secrets_store.save(TOKEN_FILE, state)
        return access_token

    age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(obtained_at)).total_seconds() / 3600
    if age_hours < REFRESH_MIN_AGE_HOURS:
        return access_token

    try:
        result = refresh_long_lived_token(access_token)
        new_token = result["access_token"]
    except Exception as e:
        print(f"[post_threads] 토큰 갱신 실패(기존 토큰으로 계속 진행): {e}")
        return access_token

    state["access_token"] = new_token
    state["obtained_at"] = datetime.now(timezone.utc).isoformat()
    secrets_store.save(TOKEN_FILE, state)
    print("[post_threads] 액세스 토큰 자동 갱신 완료")
    return new_token


def create_video_container(threads_user_id: str, access_token: str, video_url: str, text: str) -> str:
    result = _post(
        f"{GRAPH_BASE}/{threads_user_id}/threads",
        {"media_type": "VIDEO", "video_url": video_url, "text": text, "access_token": access_token},
    )
    if "id" not in result:
        raise RuntimeError(f"컨테이너 생성 실패: {result}")
    return result["id"]


def wait_for_container_ready(container_id: str, access_token: str, timeout_secs: int = 300) -> None:
    """쓰레드가 video_url에서 영상을 내려받아 처리(FINISHED)할 때까지 폴링."""
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        result = _get(f"{GRAPH_BASE}/{container_id}", {"fields": "status", "access_token": access_token})
        status = result.get("status")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"쓰레드 영상 처리 실패: {result}")
        time.sleep(10)
    raise RuntimeError(f"쓰레드 영상 처리 시간 초과({timeout_secs}초)")


def publish_container(threads_user_id: str, access_token: str, container_id: str) -> dict:
    return _post(
        f"{GRAPH_BASE}/{threads_user_id}/threads_publish",
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

    threads_user_id = os.environ["THREADS_USER_ID"]
    access_token = get_valid_access_token()

    video_url = publish_to_temp_host(Path(args.video))
    print(f"[post_threads] 임시 호스팅 완료: {video_url}")
    wait_until_reachable(video_url)
    print("[post_threads] GitHub Pages 배포 확인됨")

    container_id = create_video_container(threads_user_id, access_token, video_url, args.caption)
    print(f"[post_threads] 컨테이너 생성: {container_id}")
    wait_for_container_ready(container_id, access_token)
    print("[post_threads] 영상 처리 완료(FINISHED)")

    publish_result = publish_container(threads_user_id, access_token, container_id)
    media_id = publish_result.get("id")
    if not media_id:
        raise RuntimeError(f"발행 실패: {publish_result}")

    permalink = get_permalink(media_id, access_token)
    result = {"media_id": media_id, "permalink": permalink}
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_threads] 발행 완료: {permalink or media_id}")


if __name__ == "__main__":
    main()
