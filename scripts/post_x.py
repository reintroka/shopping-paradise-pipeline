"""@sidejoblab_kr로 X 포스트 (OAuth 1.0a, 링크 없이 — 프로필 바이오 링크로 유도하는 기존 전략).

환경변수: X_CONSUMER_KEY, X_CONSUMER_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
"""
import argparse
import hashlib
import hmac
import json
import os
import random
import string
import time
import urllib.parse
import urllib.request


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


def post_tweet(text: str) -> dict:
    url = "https://api.twitter.com/2/tweets"
    token = os.environ["X_ACCESS_TOKEN"]
    token_secret = os.environ["X_ACCESS_SECRET"]
    auth = build_auth_header("POST", url, {}, token, token_secret)
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Authorization": auth, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    args = p.parse_args()
    result = post_tweet(args.text)
    print(json.dumps(result, ensure_ascii=False))
