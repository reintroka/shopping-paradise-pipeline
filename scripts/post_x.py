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
import re
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

# 2026-09-01: X는 순수 len()이 아니라 twitter-text 가중치 규칙으로 글자수를 센다
# — 한글/CJK 문자와 대부분의 이모지는 1글자가 아니라 2로 카운트된다(실측: 280자
# 한도가 한글 기준 실질적으로 약 140자). 처음엔 이걸 모르고 len(text)<=280으로만
# 잘랐는데, x_post가 전부 한글이라 실제로는 절반 정도 여유만 있는 셈이라 그대로
# 두면 여전히 X API에서 거부될 위험이 컸다. 아래 _weighted_len이 실제 X 카운팅에
# 맞춰 계산하고, 안전마진까지 둔 한도(X_SAFE_WEIGHTED_LIMIT)로 자른다.
X_WEIGHTED_LIMIT = 280
# 정확히 280에 딱 맞추면 X 쪽 카운팅과 1~2자 오차만 나도 거부될 수 있어서
# (사용자 지시: "너무 빡빡하게 채워서 잘리지 말고 조금 여유를 줘") 20자 여유를 둔다.
X_SAFE_WEIGHTED_LIMIT = 260

# 가중치 2인 문자 범위(twitter-text 기준 한글/CJK/가나 블록 + 대부분의 이모지).
# 이 코드베이스의 실제 입력(한글 문장 + VARIATIONS의 이모지 몇 개)을 정확히
# 커버하는 걸 목표로 함 — twitter-text 전체 스펙의 100% 재현은 아님.
_WEIGHT2_RANGES = [
    (0x1100, 0x11FF),  # 한글 자모
    (0x3130, 0x318F),  # 한글 호환 자모
    (0xA960, 0xA97F),  # 한글 자모 확장-A
    (0xAC00, 0xD7A3),  # 한글 음절
    (0xD7B0, 0xD7FF),  # 한글 자모 확장-B
    (0x3000, 0x303F),  # CJK 기호/구두점
    (0x3040, 0x30FF),  # 히라가나/가타카나
    (0x4E00, 0x9FFF),  # CJK 통합 한자
    (0xFF00, 0xFFEF),  # 전각 문자
    (0x2600, 0x27BF),  # 딩뱃/기타 기호(이모지 상당수 포함)
    (0x1F300, 0x1FAFF),  # 이모지 주요 블록
]


def _char_weight(ch: str) -> int:
    cp = ord(ch)
    for lo, hi in _WEIGHT2_RANGES:
        if lo <= cp <= hi:
            return 2
    return 1


def _weighted_len(text: str) -> int:
    """X(twitter-text) 방식의 가중치 글자수 계산."""
    return sum(_char_weight(ch) for ch in text)


def _strip_hashtags(text: str) -> str:
    """텍스트 중간/끝의 '#단어' 해시태그를 전부 제거."""
    return re.sub(r"(?<!\S)#\S+", "", text).strip()


def _truncate_preserving_cta(text: str, max_weighted: int = X_SAFE_WEIGHTED_LIMIT) -> str:
    """X 가중치 글자수 한도 초과 시 본문만 잘라내고 마지막 문장(대부분 프로필
    링크 유도 CTA, gen_script.py의 cta_phrase)은 항상 보존한다.

    2026-09-01: 기존엔 이 자리에서 마지막 문장을 통째로 "제거"했는데, 그 결과
    403 재시도가 한 번이라도 걸리면 실제 발행되는 트윗에 "프로필 링크에서
    확인하세요" 같은 CTA가 아예 빠진 채 올라가고 있었다(사용자가 실발행 결과에서
    직접 발견: "문구중에 프로필링크를 확인하라는 멘트가 없네"). CTA는 절대
    제거하지 않고, 길이가 넘칠 때만 본문 쪽을 잘라서 한도 안에 맞춘다. 길이
    판정은 순수 len()이 아니라 _weighted_len(한글/이모지 2배 가중치)으로 한다.
    """
    if _weighted_len(text) <= max_weighted:
        return text
    sentences = [s for s in re.split(r"(?<=[.!?~])\s+", text.strip()) if s]
    if len(sentences) <= 1:
        body_chars, total = [], 0
        for ch in text:
            w = _char_weight(ch)
            if total + w > max_weighted:
                break
            body_chars.append(ch)
            total += w
        return "".join(body_chars).rstrip()
    cta = sentences[-1]
    body = " ".join(sentences[:-1])
    budget = max_weighted - _weighted_len(cta) - _char_weight(" ")  # 본문-CTA 사이 공백 1자
    if budget <= 0:
        # CTA 자체가 한도를 넘는 극단적 경우 — CTA만 안전하게 잘라서 반환
        out, total = [], 0
        for ch in cta:
            w = _char_weight(ch)
            if total + w > max_weighted:
                break
            out.append(ch)
            total += w
        return "".join(out)
    body_chars, total = [], 0
    for ch in body:
        w = _char_weight(ch)
        if total + w > budget:
            break
        body_chars.append(ch)
        total += w
    return f"{''.join(body_chars).rstrip()} {cta}"


def _http_error_with_body(e: urllib.error.HTTPError) -> RuntimeError:
    """2026-08-28: 실제 프로덕션 실행(제품 이미지+생성된 문구)에서 403이 계속
    났는데, 그동안 str(HTTPError)가 "HTTP Error 403: Forbidden"만 보여주고
    실제 응답 바디(X가 왜 거부했는지 설명하는 JSON)는 버려지고 있어서 원인을
    특정할 수 없었다. 응답 바디를 읽어 메시지에 포함시킨다."""
    try:
        body = e.read().decode("utf-8", errors="replace")
    except Exception:
        body = "(응답 바디 읽기 실패)"
    return RuntimeError(f"HTTP {e.code}: {body}")


def post_tweet_with_retry(text: str, media_id: str = None, max_tries: int = 2) -> dict:
    """403은 대부분 중복 콘텐츠 거부로 추정됨 — 재시도 시 문구를 변형한다.

    2026-08-31: 기존에는 문구 끝에 이모지 하나만 붙여서 재시도했는데, 이러면
    해시태그+CTA로 굳어진 문장 구조 자체는 그대로라 재시도해도 다시 403이 나는
    사례가 있었다(진단 결과 계정/토큰/이미지는 정상 — 순수 문구 구조 문제로 확인).
    재시도부터는 해시태그를 전부 제거하고 이모지 변주를 붙여 구조를 바꾼다.

    2026-09-01: 마지막 문장(CTA) 제거는 빼고 항상 보존한다 — 아래
    _truncate_preserving_cta 참고. 매 시도마다 280자 한도도 같이 확인해서,
    변형 후 길어지더라도 CTA는 안 잘리고 본문만 잘려서 발행되게 한다.
    """
    last_err = None
    for i in range(max_tries):
        if i == 0:
            attempt_text = _truncate_preserving_cta(text)
        else:
            stripped = _strip_hashtags(text)
            attempt_text = _truncate_preserving_cta(f"{stripped} {random.choice(VARIATIONS)}")
        try:
            return post_tweet(attempt_text, media_id)
        except urllib.error.HTTPError as e:
            last_err = _http_error_with_body(e)
            if e.code != 403:
                raise last_err
            print(f"[post_x] {last_err} (시도 {i + 1}/{max_tries}), 문구 변형 후 재시도")
    raise last_err


# 2026-09-03: _truncate_preserving_cta가 문장 끝(CTA)을 지키려 해도, 실제 발행
# 결과에서 "프로필링크확인" 안내가 계속 빠지는 사고가 재발했다(사용자 확인).
# truncate 로직은 항상 본문을 "앞에서부터" 예산만큼 채우고 넘치는 뒤쪽만 잘라내므로,
# 아예 맨 앞에 고정 안내 문구를 붙이면 어떤 truncate/재시도 경로를 타도 항상 살아남는다.
PROFILE_LINK_PREFIX = "[프로필링크확인] "


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--image", help="첨부할 상품 이미지 경로 (선택)")
    args = p.parse_args()
    try:
        media_id = upload_media(args.image) if args.image else None
    except urllib.error.HTTPError as e:
        raise _http_error_with_body(e) from None
    text = args.text
    if not text.startswith(PROFILE_LINK_PREFIX):
        text = f"{PROFILE_LINK_PREFIX}{text}"
    result = post_tweet_with_retry(text, media_id)
    print(json.dumps(result, ensure_ascii=False))
