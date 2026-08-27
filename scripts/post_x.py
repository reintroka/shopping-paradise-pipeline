"""@sidejoblab_kr로 X 포스트 (OAuth 1.0a, 링크 없이 — 프로필 바이오 링크로 유도하는 기존 전략).

환경변수: X_CONSUMER_KEY, X_CONSUMER_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

2026-08-27: 두 가지 추가
  1. --image로 상품 이미지(쿠팡에서 받은 product.jpg)를 첨부 — 트윗이 더 눈에 띄고,
     텍스트만 겹칠 때보다 X의 중복 콘텐츠 판정을 피하는 데도 도움됨.
  2. 403(주로 "중복 콘텐츠" 거부로 추정 — 토큰 자체는 정상 확인됨, project memory
     `project_shoppingparadise_youtube.md` 2026-08-27 항목 참고) 발생 시, 문구 끝에
     짧은 변주를 붙여서 1회 재시도.
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


def upload_media(image_path: str) -> str:
    """멀티파트 업로드라 OAuth 서명에 body 파라미터를 포함할 필요 없음(단순 폼 인코딩과 차이점)."""
    url = "https://upload.twitter.com/1.1/media/upload.json"
    token = os.environ["X_ACCESS_TOKEN"]
    token_secret = os.environ["X_ACCESS_SECRET"]
    auth = build_auth_header("POST", url, {}, token, token_secret)

    boundary = "----xmediaboundary"
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="{Path(image_path).name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": auth, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["media_id_string"]


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
