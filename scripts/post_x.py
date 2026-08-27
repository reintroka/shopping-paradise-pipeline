"""@sidejoblab_kr로 X 포스트 (OAuth 1.0a, 링크 없이 — 프로필 바이오 링크로 유도하는 기존 전략).

환경변수: X_CONSUMER_KEY, X_CONSUMER_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

2026-08-27: 세 가지 추가/수정
  1. --image로 상품 이미지(쿠팡에서 받은 product.jpg)를 첨부 — 트윗이 더 눈에 띄고,
     텍스트만 겹칠 때보다 X의 중복 콘텐츠 판정을 피하는 데도 도움됨.
  2. 403(주로 "중복 콘텐츠" 거부로 추정 — 토큰 자체는 정상 확인됨, project memory
     `project_shoppingparadise_youtube.md` 2026-08-27 항목 참고) 발생 시, 문구 끝에
     짧은 변주를 붙여서 1회 재시도.
  3. 이미지 업로드를 v1.1 구버전 단일 멀티파트(upload.twitter.com/1.1/media/upload.json)
     에서 v2 청크 업로드(api.x.com/2/media/upload, INIT→APPEND→FINALIZE[→STATUS])로
     교체 — 실제 파이프라인 실행(하루 2회)에서 이미지 첨부 시 반복적으로 403이 났는데,
     같은 X 계정 구조로 영상을 첨부하는 다른 프로젝트(코어디랩 명리마스터)는 v2를
     써서 안정적으로 성공하고 있어 동일한 방식으로 맞췄다. v1.1은 X가 계속 정리/제한
     중인 구버전 엔드포인트라 신규 앱에서 더 까다롭게 걸렸을 가능성이 높음.
"""
import argparse
import hashlib
import hmac
import json
import os
import random
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def pct(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


def build_auth_header(method, url, extra_params, token, token_secret):
    consumer_key = os.environ["X_CONSUMER_KEY"]
    consumer_secret = os.environ["X_CONSUMER_SECRET"]
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": "".join(random.choices(string.ascii_letters + string.digits, k=32)),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
        **extra_params,
    }
    param_string = "&".join(f"{pct(k)}={pct(oauth_params[k])}" for k in sorted(oauth_params))
    base_string = f"{method.upper()}&{pct(url)}&{pct(param_string)}"
    signing_key = f"{pct(consumer_secret)}&{pct(token_secret)}"
    signature = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    import base64
    oauth_params["oauth_signature"] = base64.b64encode(signature).decode()
    header = "OAuth " + ", ".join(f'{pct(k)}="{pct(oauth_params[k])}"' for k in sorted(oauth_params))
    return header


MEDIA_UPLOAD_URL = "https://api.x.com/2/media/upload"
MEDIA_CHUNK_SIZE = 4 * 1024 * 1024  # X의 5MB 청크 제한보다 여유있게


def _init_media_upload(total_bytes: int, media_type: str, media_category: str) -> str:
    url = f"{MEDIA_UPLOAD_URL}/initialize"
    token = os.environ["X_ACCESS_TOKEN"]
    token_secret = os.environ["X_ACCESS_SECRET"]
    auth = build_auth_header("POST", url, {}, token, token_secret)
    body = json.dumps(
        {"media_type": media_type, "media_category": media_category, "total_bytes": total_bytes}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Authorization": auth, "Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["data"]["id"]


def _append_media_chunk(media_id: str, chunk: bytes, segment_index: int) -> None:
    url = f"{MEDIA_UPLOAD_URL}/{media_id}/append"
    token = os.environ["X_ACCESS_TOKEN"]
    token_secret = os.environ["X_ACCESS_SECRET"]
    # multipart/form-data 바디는 OAuth 1.0a 서명 베이스에서 제외되므로(JSON 바디와 동일)
    # oauth_* 파라미터만 서명한다.
    auth = build_auth_header("POST", url, {}, token, token_secret)

    boundary = "----xmediaboundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="segment_index"\r\n\r\n'
        f"{segment_index}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="chunk"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + chunk + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": auth, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()


def _finalize_media_upload(media_id: str) -> dict | None:
    url = f"{MEDIA_UPLOAD_URL}/{media_id}/finalize"
    token = os.environ["X_ACCESS_TOKEN"]
    token_secret = os.environ["X_ACCESS_SECRET"]
    auth = build_auth_header("POST", url, {}, token, token_secret)
    req = urllib.request.Request(url, data=b"", headers={"Authorization": auth}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get("data", {}).get("processing_info")


def _wait_for_media_processing(media_id: str, initial_check_after_secs) -> None:
    check_after = initial_check_after_secs or 1
    token = os.environ["X_ACCESS_TOKEN"]
    token_secret = os.environ["X_ACCESS_SECRET"]
    for _ in range(30):
        time.sleep(check_after)
        extra = {"media_id": media_id, "command": "STATUS"}
        auth = build_auth_header("GET", MEDIA_UPLOAD_URL, extra, token, token_secret)
        query_url = f"{MEDIA_UPLOAD_URL}?media_id={pct(media_id)}&command=STATUS"
        req = urllib.request.Request(query_url, headers={"Authorization": auth}, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        info = data.get("data", {}).get("processing_info")
        if not info or info.get("state") == "succeeded":
            return
        if info.get("state") == "failed":
            raise RuntimeError("X 미디어 처리 실패 (state=failed)")
        check_after = info.get("check_after_secs", 3)
    raise RuntimeError("X 미디어 처리 시간 초과 (timeout)")


def upload_media(image_path: str) -> str:
    """X API v2 청크 업로드(INIT→APPEND→FINALIZE[→STATUS])."""
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    media_type = "image/png" if Path(image_path).suffix.lower() == ".png" else "image/jpeg"

    media_id = _init_media_upload(len(img_bytes), media_type, "tweet_image")
    for i in range(0, len(img_bytes), MEDIA_CHUNK_SIZE):
        _append_media_chunk(media_id, img_bytes[i : i + MEDIA_CHUNK_SIZE], i // MEDIA_CHUNK_SIZE)
    processing_info = _finalize_media_upload(media_id)
    if processing_info:
        _wait_for_media_processing(media_id, processing_info.get("check_after_secs"))
    return media_id


def post_tweet(text: str, media_id: str = None) -> dict:
    url = "https://api.twitter.com/2/tweets"
    token = os.environ["X_ACCESS_TOKEN"]
    token_secret = os.environ["X_ACCESS_SECRET"]
    auth = build_auth_header("POST", url, {}, token, token_secret)
    body_dict = {"text": text}
    if media_id:
        body_dict["media"] = {"media_ids": [media_id]}
    body = json.dumps(body_dict).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Authorization": auth, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


VARIATIONS = ["🛍️", "✨", "👍", "🔥", "📦"]


def post_tweet_with_retry(text: str, media_id: str = None, max_tries: int = 2) -> dict:
    """403은 대부분 중복 콘텐츠 거부로 추정됨 — 문구를 살짝 바꿔서 1회 재시도."""
    last_err = None
    for i in range(max_tries):
        attempt_text = text if i == 0 else f"{text} {random.choice(VARIATIONS)}"
        try:
            return post_tweet(attempt_text, media_id)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code != 403:
                raise
            print(f"[post_x] 403 (시도 {i + 1}/{max_tries}), 문구 변형 후 재시도")
    raise last_err


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--image", help="첨부할 상품 이미지 경로 (선택)")
    args = p.parse_args()
    media_id = upload_media(args.image) if args.image else None
    result = post_tweet_with_retry(args.text, media_id)
    print(json.dumps(result, ensure_ascii=False))
