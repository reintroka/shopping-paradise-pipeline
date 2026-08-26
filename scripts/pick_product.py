"""쿠팡파트너스 API로 고가 전자제품 하나를 골라서 JSON으로 출력한다.

- 여러 키워드로 검색해서 가격 하한(기본 300,000원) 이상인 것만 후보로 삼는다.
- used_products.json(레포에 커밋됨)에 이미 쓴 productId는 건너뛴다.
- **로켓배송(isRocket=true)만 후보로 삼는다** — 쿠팡파트너스 검색 API는 후기수/재고
  필드를 제공하지 않아서(2026-08-26 확인) "후기 많은" 필터는 구현 불가. 대신 로켓배송은
  쿠팡이 직접 재고를 보유한 상품이라 반짝특가 한정수량보다 재고가 안정적인 경향이 있어
  이걸로 대체함(사용자 승인, 2026-08-26).
- 후보를 찾으면 stdout에 JSON 한 줄 출력 + used_products.json에 추가.
"""
import argparse
import hashlib
import hmac
import json
import os
import random
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DOMAIN = "https://api-gateway.coupang.com"
KEYWORDS = [
    "노트북", "태블릿", "무선이어폰", "스마트워치", "모니터",
    "커피머신", "로봇청소기", "공기청정기", "게이밍마우스", "블루투스스피커",
]
MIN_PRICE = 300_000

HERE = Path(__file__).resolve().parent
USED_PATH = HERE.parent / "used_products.json"


def sign(method, url):
    access_key = os.environ["COUPANG_ACCESS_KEY"]
    secret_key = os.environ["COUPANG_SECRET_KEY"]
    path, _, query = url.partition("?")
    datetime_str = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = datetime_str + method + path + query
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={datetime_str}, signature={signature}"


def search(keyword, limit=10):
    path = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
    query = f"keyword={urllib.parse.quote(keyword)}&limit={limit}"
    url = f"{path}?{query}"
    auth = sign("GET", url)
    req = urllib.request.Request(
        DOMAIN + url,
        headers={"Authorization": auth, "Content-Type": "application/json;charset=UTF-8"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def load_used():
    if USED_PATH.exists():
        return json.loads(USED_PATH.read_text(encoding="utf-8"))
    return []


def save_used(used):
    USED_PATH.write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="선정된 상품 JSON을 저장할 경로")
    args = p.parse_args()

    used = load_used()
    used_ids = {u["productId"] for u in used}

    keywords = KEYWORDS[:]
    random.shuffle(keywords)

    for kw in keywords:
        try:
            result = search(kw, limit=10)
        except Exception as e:
            print(f"검색 실패({kw}): {e}")
            continue
        candidates = [
            item for item in result.get("data", {}).get("productData", [])
            if item["productPrice"] >= MIN_PRICE
            and item["productId"] not in used_ids
            and item.get("isRocket") is True
        ]
        if candidates:
            chosen = random.choice(candidates)
            chosen["keyword"] = kw
            Path(args.out).write_text(json.dumps(chosen, ensure_ascii=False, indent=2), encoding="utf-8")
            used.append({
                "productId": chosen["productId"],
                "productName": chosen["productName"],
                "used_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            save_used(used)
            print(f"선정: {chosen['productName']} ({chosen['productPrice']}원)")
            return
        time.sleep(0.5)

    raise RuntimeError("모든 키워드에서 로켓배송+미사용 신규 후보를 찾지 못했습니다 (used_products.json 확인 필요)")


if __name__ == "__main__":
    main()
