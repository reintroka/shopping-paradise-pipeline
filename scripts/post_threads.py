"""shoppingparadise.kr 쓰레드(Threads)에 발행 (Threads API) — 영상/텍스트/카드뉴스(캐러셀).

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
없으면 "비활성화"로 조용히 건너뛴다.

**2026-09-18 추가: 사용자가 직접 운영해보니 쓰레드는 영상보다 글/카드뉴스 포스팅의
조회수가 더 잘 나온다는 피드백 — --mode로 video/text/carousel 세 가지를 지원한다
(같은 실행에서 릴스 영상과 별개로 텍스트+카드뉴스도 추가 발행).

발행 방식: 인스타그램 릴스와 동일하게 컨테이너 생성 → (영상/이미지는) 처리 완료
폴링 → 발행(creation_id) 순서. 로컬 파일은 post_instagram.py와 동일한 GitHub Pages
임시 호스팅(shopping-paradise-media)을 거쳐 공개 URL을 넘긴다. 캐러셀은 이미지
여러 장의 URL이 쓰레드 서버가 각각을 가져갈 때까지 동시에 살아있어야 하므로, 개별
force push(파일 1개씩 덮어쓰기) 대신 이번 실행의 파일들을 한 커밋에 모아 한 번에
force push한다 — 그래야 카드1 URL이 카드2 push로 지워지는 일이 없다.
"""
import argparse
import json
import os
import re
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
# 쓰레드 게시물 본문은 500자 제한(인스타그램 2200자보다 훨씬 짧음). ig_caption은
# 맨 앞에 쿠팡 파트너스 고지 문구가 이미 붙어있는 상태(gen_script.py의
# append_disclosure)라, 뒤쪽만 잘라도 고지 문구는 항상 살아남는다.
THREADS_TEXT_MAX_LEN = 500
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
    with _urlopen_with_retry(req, timeout=30) as resp:
        return json.loads(resp.read())


def _post(url: str, params: dict) -> dict:
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    with _urlopen_with_retry(req, timeout=30) as resp:
        return json.loads(resp.read())


def _urlopen_with_retry(req: urllib.request.Request, timeout: int, max_attempts: int = 4):
    """urllib.request.urlopen을 지수 백오프로 재시도한다(2026-09-21, 코어디웹
    인스타그램 발행 실패 재점검 중 같은 패턴을 전체 채널에서 발견해 이식).
    지금까지는 이 파일의 _get/_post에 timeout은 있었지만 순수 네트워크 예외
    (TimeoutError/ConnectionError/URLError)와 429/5xx(서버 쪽 일시적 문제)에
    재시도가 전혀 없어서, 연결이 한 번만 흔들려도 그 실행 전체가 실패로 끝났다
    (post_tiktok.py에서 먼저 고친 것과 동일한 패턴). 4xx(요청 자체가 잘못된
    경우)는 재시도해도 안 고쳐지므로 그대로 올린다."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                last_exc = e
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_exc = e
        if attempt < max_attempts - 1:
            wait = 2 ** attempt
            print(f"  [post_threads] 요청 실패({last_exc}), {wait}초 후 재시도 ({attempt + 1}/{max_attempts})")
            time.sleep(wait)
    if isinstance(last_exc, urllib.error.HTTPError):
        raise _http_error_with_body(last_exc) from None
    raise RuntimeError(f"요청이 {max_attempts}회 재시도 후에도 실패했습니다: {last_exc}") from last_exc


def publish_to_temp_host(files: dict) -> dict:
    """{파일명: 로컬경로} 여러 개를 한 커밋으로 묶어 shopping-paradise-media 저장소에
    force push하고 {파일명: GitHub Pages URL}을 반환한다.

    한 번에(한 커밋으로) 밀어야 캐러셀처럼 여러 URL이 동시에 살아있어야 하는 경우에도
    먼저 올린 파일의 URL이 다음 파일 push로 지워지지 않는다. 파일명은 호출부에서
    타임스탬프 기반 고유값으로 만들어 캐시 충돌을 방지한다(post_instagram.py와 동일 이유).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for filename, local_path in files.items():
            (tmp_path / filename).write_bytes(Path(local_path).read_bytes())
        (tmp_path / ".nojekyll").touch()
        subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", MEDIA_REPO_URL], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.email=bot@shopping-paradise.local",
             "-c", "user.name=shopping-paradise-bot", "commit", "-q", "-m", f"temp host {len(files)} file(s)"],
            check=True,
        )
        subprocess.run(["git", "-C", str(tmp_path), "push", "--force", "origin", "HEAD:main"], check=True)
    return {filename: f"{MEDIA_PAGES_BASE}/{filename}" for filename in files}


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
        raise RuntimeError(f"영상 컨테이너 생성 실패: {result}")
    return result["id"]


def create_text_container(threads_user_id: str, access_token: str, text: str) -> str:
    result = _post(
        f"{GRAPH_BASE}/{threads_user_id}/threads",
        {"media_type": "TEXT", "text": text, "access_token": access_token},
    )
    if "id" not in result:
        raise RuntimeError(f"텍스트 컨테이너 생성 실패: {result}")
    return result["id"]


def create_carousel_item_container(threads_user_id: str, access_token: str, image_url: str) -> str:
    result = _post(
        f"{GRAPH_BASE}/{threads_user_id}/threads",
        {"media_type": "IMAGE", "image_url": image_url, "is_carousel_item": "true", "access_token": access_token},
    )
    if "id" not in result:
        raise RuntimeError(f"캐러셀 아이템 컨테이너 생성 실패: {result}")
    return result["id"]


def create_carousel_container(threads_user_id: str, access_token: str, children_ids: list, text: str) -> str:
    result = _post(
        f"{GRAPH_BASE}/{threads_user_id}/threads",
        {"media_type": "CAROUSEL", "children": ",".join(children_ids), "text": text, "access_token": access_token},
    )
    if "id" not in result:
        raise RuntimeError(f"캐러셀 컨테이너 생성 실패: {result}")
    return result["id"]


def wait_for_container_ready(container_id: str, access_token: str, timeout_secs: int = 300) -> None:
    """쓰레드가 media_url에서 미디어를 내려받아 처리(FINISHED)할 때까지 폴링.
    텍스트 전용 컨테이너도 같은 흐름을 타지만 처리할 미디어가 없어 즉시 FINISHED가 된다."""
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        result = _get(f"{GRAPH_BASE}/{container_id}", {"fields": "status", "access_token": access_token})
        status = result.get("status")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"쓰레드 컨테이너 처리 실패: {result}")
        time.sleep(10)
    raise RuntimeError(f"쓰레드 컨테이너 처리 시간 초과({timeout_secs}초): {container_id}")


def publish_container(threads_user_id: str, access_token: str, container_id: str) -> dict:
    return _post(
        f"{GRAPH_BASE}/{threads_user_id}/threads_publish",
        {"creation_id": container_id, "access_token": access_token},
    )


def get_permalink(media_id: str, access_token: str) -> str:
    result = _get(f"{GRAPH_BASE}/{media_id}", {"fields": "permalink", "access_token": access_token})
    return result.get("permalink", "")


def _truncate_caption(text: str, max_len: int = THREADS_TEXT_MAX_LEN) -> str:
    """쓰레드 500자 제한에 맞춰 뒤쪽만 자른다. 쿠팡 파트너스 고지 문구는 항상 맨
    앞에 있으므로(gen_script.py) 이 방식으로는 절대 잘리지 않는다.

    2026-09-18: 예전엔 무조건 499자에서 잘라 "…"만 붙였는데, 그러면 문장이 중간에
    뚝 끊긴 티가 났다(사용자 지시: "잘리더라도.. 글이 중간에 잘리지 않고.. 그전
    단락까지 나가게.. 마무리되는 느낌이 들게" — coredlab/명리마스터에도 동일 적용).
    완결된 문단 > 완결된 문장 > 줄바꿈 > 공백 순으로 자르고, 그 정도로도 앞부분
    40% 이상을 못 건질 때만 마지막 수단으로 공백/강제 절단 + "…"을 쓴다."""
    if len(text) <= max_len:
        return text

    head = text[:max_len]
    min_acceptable = len(head) * 0.4

    paragraph_break = head.rfind("\n\n")
    sentence_ends = [m.end() for m in re.finditer(r"(?:[.!?]|다\.|요\.)(?=\s|\n|$)", head)]
    last_sentence_end = sentence_ends[-1] if sentence_ends else -1
    last_newline = head.rfind("\n")
    last_space = head.rfind(" ")

    if paragraph_break >= min_acceptable:
        return head[:paragraph_break].rstrip()
    if last_sentence_end >= min_acceptable:
        return head[:last_sentence_end].rstrip()
    if last_newline >= min_acceptable:
        return head[:last_newline].rstrip()
    if last_space >= min_acceptable:
        return head[:last_space].rstrip() + "…"
    return head.rstrip() + "…"


def _finish_and_write(threads_user_id, access_token, container_id, out_path, tag):
    publish_result = publish_container(threads_user_id, access_token, container_id)
    media_id = publish_result.get("id")
    if not media_id:
        raise RuntimeError(f"발행 실패: {publish_result}")

    permalink = get_permalink(media_id, access_token)
    result = {"media_id": media_id, "permalink": permalink}
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_threads:{tag}] 발행 완료: {permalink or media_id}")


def post_video(threads_user_id, access_token, video_path, caption, out_path):
    ts = int(time.time())
    filename = f"th-{ts}.mp4"
    urls = publish_to_temp_host({filename: video_path})
    video_url = urls[filename]
    print(f"[post_threads:video] 임시 호스팅 완료: {video_url}")
    wait_until_reachable(video_url)
    print("[post_threads:video] GitHub Pages 배포 확인됨")

    container_id = create_video_container(threads_user_id, access_token, video_url, caption)
    print(f"[post_threads:video] 컨테이너 생성: {container_id}")
    wait_for_container_ready(container_id, access_token)
    print("[post_threads:video] 영상 처리 완료(FINISHED)")

    _finish_and_write(threads_user_id, access_token, container_id, out_path, "video")


def post_text(threads_user_id, access_token, caption, out_path):
    container_id = create_text_container(threads_user_id, access_token, caption)
    print(f"[post_threads:text] 컨테이너 생성: {container_id}")
    wait_for_container_ready(container_id, access_token)
    _finish_and_write(threads_user_id, access_token, container_id, out_path, "text")


def post_carousel(threads_user_id, access_token, image_paths, caption, out_path):
    ts = int(time.time())
    filenames = [f"th-card{i}-{ts}.png" for i in range(1, len(image_paths) + 1)]
    urls = publish_to_temp_host(dict(zip(filenames, image_paths)))
    image_urls = [urls[f] for f in filenames]
    print(f"[post_threads:carousel] 임시 호스팅 완료: {image_urls}")
    for url in image_urls:
        wait_until_reachable(url)
    print("[post_threads:carousel] GitHub Pages 배포 확인됨")

    item_ids = []
    for url in image_urls:
        item_id = create_carousel_item_container(threads_user_id, access_token, url)
        wait_for_container_ready(item_id, access_token)
        item_ids.append(item_id)
    print(f"[post_threads:carousel] 아이템 컨테이너 {len(item_ids)}개 처리 완료")

    container_id = create_carousel_container(threads_user_id, access_token, item_ids, caption)
    print(f"[post_threads:carousel] 캐러셀 컨테이너 생성: {container_id}")
    wait_for_container_ready(container_id, access_token)

    _finish_and_write(threads_user_id, access_token, container_id, out_path, "carousel")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["video", "text", "carousel"], default="video")
    p.add_argument("--video")
    p.add_argument("--images", help="캐러셀 이미지 경로를 콤마로 구분해서 전달 (2~10장)")
    p.add_argument("--caption", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    threads_user_id = os.environ["THREADS_USER_ID"]
    access_token = get_valid_access_token()
    args.caption = _truncate_caption(args.caption)

    if args.mode == "video":
        if not args.video:
            raise SystemExit("--mode video 에는 --video가 필요합니다")
        post_video(threads_user_id, access_token, Path(args.video), args.caption, args.out)
    elif args.mode == "text":
        post_text(threads_user_id, access_token, args.caption, args.out)
    elif args.mode == "carousel":
        if not args.images:
            raise SystemExit("--mode carousel 에는 --images가 필요합니다")
        image_paths = [Path(s.strip()) for s in args.images.split(",") if s.strip()]
        post_carousel(threads_user_id, access_token, image_paths, args.caption, args.out)


if __name__ == "__main__":
    main()
