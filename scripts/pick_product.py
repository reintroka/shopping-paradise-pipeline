"""쿠팡파트너스 API로 상품 하나를 골라서 JSON으로 출력한다.

- 여러 키워드로 검색해서 카테고리별 가격 하한 이상인 것만 후보로 삼는다
  (2026-08-29: 전자제품 단일 카테고리에서 뷰티/생활용품·가전가구까지 소싱 다양화 —
  카테고리마다 시세가 달라 가격 하한을 키워드별로 다르게 둠. 전자제품처럼 원래
  단가가 높은 카테고리는 300,000원, 뷰티/생활용품처럼 원래 단가가 낮은 카테고리는
  20,000~30,000원 등으로 낮춤. 하나의 MIN_PRICE로 통일하면 저가 카테고리 후보가
  전부 걸러져서 사실상 전자제품만 뽑히는 문제가 있었음).
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

# (검색 키워드, 가격 하한) — 카테고리마다 시세가 달라 하한을 다르게 둔다.
CATEGORY_KEYWORDS = [
    # 전자제품 (기존)
    ("노트북", 300_000), ("태블릿", 300_000), ("무선이어폰", 300_000),
    ("스마트워치", 300_000), ("모니터", 300_000), ("커피머신", 300_000),
    ("로봇청소기", 300_000), ("공기청정기", 300_000), ("게이밍마우스", 300_000),
    ("블루투스스피커", 300_000),
    # 가전/가구 (2026-08-29 추가, 원래 단가가 전자제품보다 낮아 하한 낮춤)
    ("에어프라이어", 100_000), ("인덕션레인지", 100_000), ("식기세척기", 300_000),
    ("매트리스", 200_000), ("러닝머신", 200_000), ("안마의자", 300_000),
    # 뷰티/생활용품 (2026-08-29 추가, 저가 카테고리라 하한 대폭 낮춤)
    ("화장품세트", 30_000), ("다이어트보조제", 30_000), ("샴푸세트", 20_000),
    ("청소용품세트", 20_000), ("주방수납용품", 20_000), ("캠핑용품세트", 50_000),
]

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


def bare_product_url(product_id, item_url):
    """productUrl(이미 lptag/traceid 등이 붙은 link.coupang.com 추적 링크)에서
    itemId/vendorItemId만 뽑아 순수 상품 URL(www.coupang.com/vp/products/...)을 재구성.
    딥링크 변환 API는 이미 추적 파라미터가 붙은 link.coupang.com URL을 넣으면
    "url convert failed"로 거부하므로, 반드시 순수 URL 형태로 다시 만들어야 함.
    """
    q = urllib.parse.urlparse(item_url).query
    params = urllib.parse.parse_qs(q)
    item_id = params.get("itemId", [None])[0]
    vendor_item_id = params.get("vendorItemId", [None])[0]
    url = f"https://www.coupang.com/vp/products/{product_id}"
    if item_id and vendor_item_id:
        url += f"?itemId={item_id}&vendorItemId={vendor_item_id}"
    return url


def shorten_link(product_id, item_url):
    """쿠팡 딥링크 변환 API로 순수 상품 URL을 link.coupang.com/a/xxxx 짧은 링크로 변환.
    댓글/설명란에 긴 URL을 그대로 붙이면 지저분하고 스팸처럼 보여서 반드시 축약해야 함.
    """
    coupang_url = bare_product_url(product_id, item_url)
    path = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
    auth = sign("POST", path)
    body = json.dumps({"coupangUrls": [coupang_url]}).encode("utf-8")
    req = urllib.request.Request(
        DOMAIN + path, data=body, method="POST",
        headers={"Authorization": auth, "Content-Type": "application/json;charset=UTF-8"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    return result["data"][0]["shortenUrl"]


def load_used():
    if USED_PATH.exists():
        return json.loads(USED_PATH.read_text(encoding="utf-8"))
    return []


def save_used(used):
    USED_PATH.write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding="utf-8")


# 2026-08-28: productId 완전일치만 걸러서는 "LG전자 퓨리케어 360도 Hit"과 "LG전자
# 퓨리케어 360도 오브제컬렉션 플러스"처럼 브랜드+제품라인이 같은 변형 상품(용량/모델
# 만 다름)이 서로 다른 productId로 반복 노출되는 문제가 있었다(사용자가 "같은건데
# 뒤에 버전만 다른 식으로 계속 올라간다" 지적으로 발견). 최근 사용한 상품명의 앞
# 두 단어(보통 브랜드+제품라인)를 시그니처로 뽑아 최근 목록과 겹치면 건너뛴다.
RECENT_SIMILARITY_WINDOW = 20


def _signature(product_name: str) -> str:
    tokens = product_name.replace(",", " ").split()
    return " ".join(tokens[:2]).lower()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="선정된 상품 JSON을 저장할 경로")
    args = p.parse_args()

    used = load_used()
    used_ids = {u["productId"] for u in used}
    recent_signatures = {_signature(u["productName"]) for u in used[-RECENT_SIMILARITY_WINDOW:]}

    category_keywords = CATEGORY_KEYWORDS[:]
    random.shuffle(category_keywords)

    for kw, min_price in category_keywords:
        try:
            result = search(kw, limit=10)
        except Exception as e:
            print(f"검색 실패({kw}): {e}")
            continue
        candidates = [
            item for item in result.get("data", {}).get("productData", [])
            if item["productPrice"] >= min_price
            and item["productId"] not in used_ids
            and item.get("isRocket") is True
            and _signature(item["productName"]) not in recent_signatures
        ]
        if candidates:
            chosen = random.choice(candidates)
            chosen["keyword"] = kw
            try:
                chosen["shortUrl"] = shorten_link(chosen["productId"], chosen["productUrl"])
            except Exception as e:
                print(f"딥링크 변환 실패, 원본 URL 사용: {e}")
                chosen["shortUrl"] = chosen["productUrl"]
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
