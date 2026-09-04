"""shoppingparadise.kr 인스타그램에 Reels로 발행 (Instagram API with Instagram Login).

환경변수: IG_USER_ID, IG_ACCESS_TOKEN
  - IG_USER_ID: shoppingparadise.kr의 Instagram 비즈니스 계정 ID (graph.instagram.com/me로 확인)
  - IG_ACCESS_TOKEN: instagram_business_content_publish 권한이 있는 장기(long-lived, IGAA로
    시작) 토큰 — shopping-paradise-secrets 저장소에 아직 토큰 파일이 없을 때만 쓰이는
    최초 시드값. 이후로는 매 실행마다 그 저장소의 값을 읽고, REFRESH_MIN_AGE_HOURS(기본
    30일)만큼 지났으면 자동 갱신해서 다시 저장한다(2026-09-01, "만료 없이 되도록" 요청으로
    도입) — 사람이 60일마다 수동으로 토큰을 갱신할 필요가 없어짐. Meta 정책상 최소 24시간만
    지나면 갱신 가능하지만, 60일 유효기간 대비 매일 갱신할 이유가 없어서(불필요한 API
    호출+시크릿 저장소 push만 늘어남) 30일로 여유있게 잡음 — 60일 만료 전에 최소 한 번은
    반드시 갱신되도록 절반보다 짧게.

**중요**: "Instagram API with Instagram Login" 토큰(IGAA 접두사)은 graph.facebook.com이
아니라 graph.instagram.com을 써야 한다 — 처음에 graph.facebook.com으로 짰다가 토큰 타입
불일치로 전부 실패했을 것(실제 curl 테스트로 확인, graph.instagram.com/me만 정상 동작).

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
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
MEDIA_REPO_URL = "https://github.com/reintroka/shopping-paradise-media.git"
MEDIA_PAGES_BASE = "https://reintroka.github.io/shopping-paradise-media"
# 2026-09-04: 예전엔 매번 같은 파일명(reel.mp4)을 덮어썼는데, GitHub Pages가 앞단에 쓰는
# CDN 캐시(Cache-Control: max-age=600)가 URL 단위로 캐싱하다 보니 push 직후 인스타그램이
# video_url을 가져갈 때 어제자 캐시가 아직 안 밀려나 "어제 영상이 오늘 캡션으로 발행되는"
# 사고가 났음(실측 확인, [쇼핑의천국] female 인덕션 발행 건). 실행마다 고유 파일명을 써서
# URL 자체를 매번 새로 만들면 캐시 충돌이 원천적으로 불가능해진다 — 저장소는 여전히
# 파일 1개만(force push로 이전 파일 자동 제거) 유지되니 저장소 크기 문제도 없음.
TOKEN_FILE = "instagram_token.json"
# Meta 정책상 최소 24시간이면 재갱신 가능하지만, 토큰 자체가 60일 유효라 그렇게 자주
# 갱신할 필요가 없다 — 30일로 잡아서 매 실행마다 API 호출+시크릿 저장소 push가 늘어나는
# 것을 막으면서도 60일 만료 전에는 항상 갱신되도록 함(2026-09-01, 사용자 피드백 반영).
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

    히스토리를 쌓지 않기 위해 매번 얕은 클론 없이 새 커밋 하나만 만들어 force push한다
    (run_pipeline.py의 다른 저장소들과 달리 이 저장소는 순수 임시 호스팅 용도라
    fast-forward를 유지할 필요가 없음).

    파일명은 실행마다 고유하게(타임스탬프 기반) 만든다 — 고정 파일명을 재사용하면 GitHub
    Pages 앞단 CDN 캐시가 그 URL을 붙들고 있다가 인스타그램이 가져갈 때 어제자 영상을
    내줄 수 있다(실측으로 확인된 사고). 매번 새 URL이면 캐시 자체가 존재할 수 없다.
    """
    media_filename = f"reel-{int(time.time())}.mp4"
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


def refresh_long_lived_token(access_token: str) -> dict:
    return _get("https://graph.instagram.com/refresh_access_token", {
        "grant_type": "ig_refresh_token", "access_token": access_token,
    })


def get_valid_access_token() -> str:
    """secrets 저장소에서 현재 토큰을 읽고, 24시간 이상 지났으면 갱신 후 다시 저장한다.

    갱신 실패(24시간이 안 지났거나 일시적 오류)는 치명적 에러로 취급하지 않고 기존 토큰을
    그대로 쓴다 — 다음 실행에서 다시 시도하면 되므로, 발행 자체가 막히면 안 된다.
    """
    state = secrets_store.load(TOKEN_FILE, bootstrap={
        "access_token": os.environ["IG_ACCESS_TOKEN"], "obtained_at": None,
    })
    access_token = state["access_token"]
    obtained_at = state.get("obtained_at")

    if obtained_at is None:
        # 처음 보는 토큰(부트스트랩 직후) — 나이를 몰라서 갱신 시도는 안 하고, 지금
        # 시각을 기준으로 기록만 남겨서 다음 실행부터 24시간 계산이 가능하게 한다.
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
        print(f"[post_instagram] 토큰 갱신 실패(기존 토큰으로 계속 진행): {e}")
        return access_token

    state["access_token"] = new_token
    state["obtained_at"] = datetime.now(timezone.utc).isoformat()
    secrets_store.save(TOKEN_FILE, state)
    print("[post_instagram] 액세스 토큰 자동 갱신 완료")
    return new_token


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
    access_token = get_valid_access_token()

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
