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
                # 4xx는 재시도해도 안 고쳐지지만, 몸통(에러 사유)을 안 읽고 그냥
                # raise하면 "HTTP Error 400: Bad Request"처럼 원인을 알 수 없는
                # 메시지만 텔레그램 알림에 남는다(2026-09-24, 카드뉴스 인스타그램
                # 발행 400 실패를 실제로 이렇게 놓친 적 있음). 5xx/429와 동일하게
                # 몸통을 읽어서 실제 Graph API 에러를 알림에 남긴다.
                raise _http_error_with_body(e) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_exc = e
        if attempt < max_attempts - 1:
            wait = 2 ** attempt
            print(f"  [post_instagram] 요청 실패({last_exc}), {wait}초 후 재시도 ({attempt + 1}/{max_attempts})")
            time.sleep(wait)
    if isinstance(last_exc, urllib.error.HTTPError):
        raise _http_error_with_body(last_exc) from None
    raise RuntimeError(f"요청이 {max_attempts}회 재시도 후에도 실패했습니다: {last_exc}") from last_exc


def publish_images_to_temp_host(image_paths: list) -> list:
    """카드뉴스 이미지 여러 장을 한 커밋에 모아 한 번에 force push하고 URL 리스트를
    반환한다(post_threads.py의 동명 함수와 동일한 이유 — 개별 force push하면 앞
    이미지의 URL이 다음 이미지 push로 지워짐). 2026-09-18, 쓰레드뿐 아니라
    인스타그램/페이스북에도 카드뉴스를 발행하기로 함(사용자 지시: "쓰레드만
    발행하지 말고.. 할수 있는곳에는 다 발행해")."""
    ts = int(time.time())
    filenames = [f"ig-card{i}-{ts}.png" for i in range(1, len(image_paths) + 1)]
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
    """인스타그램이 video_url에서 영상을 내려받아 처리(FINISHED)할 때까지 폴링.

    2026-09-25: 카드뉴스 캐러셀은 이미지 3장 + 부모 컨테이너까지 컨테이너 4개를 각각
    이 함수로 폴링하는데, 10초 간격이면 최악의 경우(이미지 처리가 느린 날) 발행 하나당
    Graph API 호출이 100회를 넘어갈 수 있다. 2일 연속 2시(cards-noon) 타임에서만
    "Application request limit reached"(코드 4, 시간당 호출량 기반 한도)로 실패했는데
    9시(cards-evening) 타임은 같은 호출 패턴에서 멀쩡했던 걸 보면, 하루 누적 총량이
    아니라 짧은 시간에 몰리는 폴링 버스트가 원인일 가능성이 높다 — 간격을 20초로 늘려
    같은 300초 안에서 호출 횟수를 절반으로 줄인다(동작/기능은 동일, 최악의 경우 대기
    시간만 약간 늘어남).
    """
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        result = _get(f"{GRAPH_BASE}/{container_id}", {"fields": "status_code", "access_token": access_token})
        status = result.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"인스타그램 영상 처리 실패: {result}")
        time.sleep(20)
    raise RuntimeError(f"인스타그램 영상 처리 시간 초과({timeout_secs}초)")


def publish_container(ig_user_id: str, access_token: str, container_id: str) -> dict:
    return _post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        {"creation_id": container_id, "access_token": access_token},
    )


def publish_container_with_retry(
    ig_user_id: str, access_token: str, container_id: str, max_attempts: int = 3, wait_secs: int = 90
) -> dict:
    """마지막 발행 호출에서만 "Application request limit reached"(code 4)와
    "Generic Internal Error"(error_subcode 2207085)를 별도로 재시도한다(2026-09-25,
    male 카드뉴스가 이전에는 멀쩡하던 9시 타임에서도 code 4 에러로 실패해서, "2시에만
    터진다"는 이전 가설이 틀렸음이 드러남 — 폴링 간격 완화(20초)만으로는 부족함이
    확인됨. 2026-09-26, female 카드뉴스에서 이번엔 code 4가 아니라 error_subcode
    2207085 "Generic Internal Error"/"An internal server error occurred. Please
    try again later."로 같은 지점에서 실패 — Meta 응답 자체가 재시도를 권하는
    메시지인데도 재시도 대상이 아니었음). _urlopen_with_retry는 이 에러들을 코드상
    4xx로 보고 바로 올리는데, 실제로는 Meta 쪽 일시적 문제라 몇 분 안에 풀리는
    경우가 많다. 이미지/영상은 이미 호스팅되고 컨테이너까지 다 만들어진 상태라
    여기서 포기하면 그날 발행 자체가 통째로 날아가므로, 발행 호출만 짧게 대기 후
    재시도한다."""
    last_exc: RuntimeError | None = None
    for attempt in range(max_attempts):
        try:
            return publish_container(ig_user_id, access_token, container_id)
        except RuntimeError as e:
            msg = str(e)
            is_rate_limit = '"code":4' in msg or "request limit reached" in msg.lower()
            is_generic_internal = '"error_subcode":2207085' in msg or "generic internal error" in msg.lower()
            if not is_rate_limit and not is_generic_internal:
                raise
            last_exc = e
            if attempt < max_attempts - 1:
                reason = "앱 요청 한도 초과" if is_rate_limit else "Meta 서버 일시 오류(Generic Internal Error)"
                print(
                    f"  [post_instagram] {reason}, {wait_secs}초 후 발행 재시도 "
                    f"({attempt + 1}/{max_attempts})"
                )
                time.sleep(wait_secs)
    raise last_exc


def create_carousel_item_container(ig_user_id: str, access_token: str, image_url: str) -> str:
    result = _post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        {"image_url": image_url, "is_carousel_item": "true", "access_token": access_token},
    )
    if "id" not in result:
        raise RuntimeError(f"캐러셀 아이템 컨테이너 생성 실패: {result}")
    return result["id"]


def create_carousel_container(ig_user_id: str, access_token: str, children_ids: list, caption: str) -> str:
    result = _post(
        f"{GRAPH_BASE}/{ig_user_id}/media",
        {"media_type": "CAROUSEL", "children": ",".join(children_ids), "caption": caption, "access_token": access_token},
    )
    if "id" not in result:
        raise RuntimeError(f"캐러셀 컨테이너 생성 실패: {result}")
    return result["id"]


def post_video(ig_user_id, access_token, video_path, caption, out_path):
    video_url = publish_to_temp_host(Path(video_path))
    print(f"[post_instagram:video] 임시 호스팅 완료: {video_url}")
    wait_until_reachable(video_url)
    print("[post_instagram:video] GitHub Pages 배포 확인됨")

    container_id = create_reels_container(ig_user_id, access_token, video_url, caption)
    print(f"[post_instagram:video] 컨테이너 생성: {container_id}")
    wait_for_container_ready(container_id, access_token)
    print("[post_instagram:video] 영상 처리 완료(FINISHED)")

    publish_result = publish_container_with_retry(ig_user_id, access_token, container_id)
    media_id = publish_result.get("id")
    if not media_id:
        raise RuntimeError(f"발행 실패: {publish_result}")

    # 2026-09-26: permalink 조회(GET)는 발행 자체와 무관한 알림용 호출인데, 이 값을
    # 실제로 읽는 곳이 run_cards.py/run_pipeline.py 어디에도 없음을 확인함(순수
    # write-only). 인스타그램 앱이 API 호출 한도에 자주 걸리는 상황(App Review 미제출,
    # [[shopping_paradise_instagram_app_rate_limit_2026-09-25]])이라 안 쓰는 호출을
    # 하나라도 줄이는 게 낫다 — 아예 호출하지 않는다(같은 계정군 명리마스터
    # 코드베이스도 permalink를 조회하지 않음, 참고해서 맞춤).
    result = {"media_id": media_id}
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_instagram:video] 발행 완료: {media_id}")


def post_carousel(ig_user_id, access_token, image_paths, caption, out_path):
    # 2026-09-18: 쓰레드뿐 아니라 인스타그램에도 카드뉴스(캐러셀)를 발행하기로 함
    # (사용자 지시: "쓰레드만 발행하지 말고.. 할수 있는곳에는 다 발행해"). 로직은
    # post_threads.py의 캐러셀 플로우와 동일 — 이미지 여러 장을 한 커밋에 모아
    # 호스팅→아이템 컨테이너 생성/대기→부모 컨테이너 생성/대기→발행.
    image_urls = publish_images_to_temp_host([Path(p) for p in image_paths])
    print(f"[post_instagram:carousel] 임시 호스팅 완료: {image_urls}")
    for url in image_urls:
        wait_until_reachable(url)
    print("[post_instagram:carousel] GitHub Pages 배포 확인됨")

    # 2026-09-25: 이미지 캐러셀 아이템 컨테이너는 동영상과 달리 비동기 처리 단계가 없어서
    # (Meta Graph API 문서상 캐러셀 이미지 아이템은 생성 즉시 준비됨 — status_code 폴링이
    # 필요한 건 동영상/릴스 컨테이너와 캐러셀 부모 컨테이너뿐) 아이템당 1회씩 걸던
    # wait_for_container_ready 호출을 제거함. 이미지 3장 캐러셀 기준 Graph API 호출을
    # 3회 줄여 앱 요청 한도(code 4)에 덜 부딪히게 한다 — 앱리뷰로 한도를 올리기 전까지의
    # 완화책. id가 정상 반환되면 생성 자체는 성공한 것이므로 안전.
    item_ids = [create_carousel_item_container(ig_user_id, access_token, url) for url in image_urls]
    print(f"[post_instagram:carousel] 아이템 컨테이너 {len(item_ids)}개 생성 완료")

    container_id = create_carousel_container(ig_user_id, access_token, item_ids, caption)
    print(f"[post_instagram:carousel] 캐러셀 컨테이너 생성: {container_id}")
    wait_for_container_ready(container_id, access_token)

    publish_result = publish_container_with_retry(ig_user_id, access_token, container_id)
    media_id = publish_result.get("id")
    if not media_id:
        raise RuntimeError(f"발행 실패: {publish_result}")

    # post_video와 동일한 이유로 permalink 조회 자체를 하지 않는다.
    result = {"media_id": media_id}
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[post_instagram:carousel] 발행 완료: {media_id}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["video", "carousel"], default="video")
    p.add_argument("--video")
    p.add_argument("--images", help="캐러셀 이미지 경로를 콤마로 구분해서 전달 (2~10장)")
    p.add_argument("--caption", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    ig_user_id = os.environ["IG_USER_ID"]
    access_token = get_valid_access_token()

    if args.mode == "video":
        if not args.video:
            raise SystemExit("--mode video 에는 --video가 필요합니다")
        post_video(ig_user_id, access_token, args.video, args.caption, args.out)
    elif args.mode == "carousel":
        if not args.images:
            raise SystemExit("--mode carousel 에는 --images가 필요합니다")
        image_paths = [s.strip() for s in args.images.split(",") if s.strip()]
        post_carousel(ig_user_id, access_token, image_paths, args.caption, args.out)


if __name__ == "__main__":
    main()
