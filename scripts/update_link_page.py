"""부업실험실 링크 페이지(reintroka/sidejoblab-links)에 새 상품 카드를 추가하고 배포.

실패해도(권한/네트워크 문제) 파이프라인 전체를 막으면 안 되므로, 호출하는 쪽에서
예외를 잡아 경고만 남기고 넘어가도록 설계됨 — 이 스크립트 자체는 그냥 실패시 예외를 던진다.

2026-09-02: 정적 카드 HTML을 직접 이어붙이던 방식(무한정 스크롤 + 이미지 없음, 검색
불가)에서 index.html이 `const ITEMS = [...]` 데이터 배열 + JS 렌더링(검색/더보기/이미지
폴백 아이콘) 구조로 바뀜에 따라 삽입 로직도 함께 갱신. 이제 새 카드는 ITEMS 배열에
객체 하나를 끼워 넣는 방식이고, 배열 안에서의 위치는 상관없음(페이지가 rank 기준
내림차순으로 정렬해서 그림) — 그래서 항상 `const ITEMS = [` 바로 다음에 꽂는다.

이 스크립트는 실행마다 저장소를 새로 clone하는데, 매번 전체 커밋 히스토리를 받으면
카드가 수백~수천 개 쌓였을 때(=커밋도 그만큼 쌓였을 때) clone 자체가 계속 느려진다.
우리는 최신 index.html 내용만 있으면 되고 과거 히스토리는 필요 없으므로 --depth 1로
얕은 clone을 써서 이 파이프라인의 소요시간이 카드 개수와 무관하게 항상 일정하게 유지
되도록 한다(사용자가 "나중에 상품이 1000개 넘어가면?" 질문한 계기로 선제 반영).
"""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

REPO_URL = "https://github.com/reintroka/sidejoblab-links.git"
ITEMS_MARKER = "const ITEMS = [\n"


def run(cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True)


def push_with_retry(repo_dir, max_tries: int = 3) -> None:
    """run_pipeline.py의 push_with_retry와 동일한 이유로 `HEAD:main`을 명시한다
    (2026-08-28, 클라우드 샌드박스가 detached HEAD로 클론하는 경우 대비)."""
    for attempt in range(1, max_tries + 1):
        try:
            run(["git", "-C", repo_dir, "push", "origin", "HEAD:main"])
            return
        except subprocess.CalledProcessError as e:
            if attempt == max_tries:
                raise
            print(f"[update_link_page] push 실패(시도 {attempt}/{max_tries}): {e} — fetch+rebase 후 재시도")
            run(["git", "-C", repo_dir, "fetch", "origin"])
            run(["git", "-C", repo_dir, "rebase", "origin/main"])


def next_rank(html: str) -> int:
    """ITEMS 배열에 실제로 박혀있는 rank 값 중 최댓값+1. 텍스트 개수를 세지 않고 값
    자체의 최댓값을 쓰는 이유는 과거 개수 기반 계산에서 고정카드 포함/제외를 헷갈려
    번호가 중복 발급된 사고가 있었기 때문(구버전 next_ordinal_label 참고)."""
    nums = [int(n) for n in re.findall(r"rank:\s*(\d+)", html)]
    return (max(nums) if nums else 1) + 1


def add_card(product_name: str, price: str, coupang_url: str, hook_line: str, image_url: str = ""):
    with tempfile.TemporaryDirectory() as tmp:
        run(["git", "clone", "--depth", "1", REPO_URL, tmp])
        index_path = Path(tmp) / "index.html"
        html = index_path.read_text(encoding="utf-8")

        if ITEMS_MARKER not in html:
            raise RuntimeError("index.html에서 삽입 위치(const ITEMS = [)를 찾지 못했습니다.")

        rank = next_rank(html)
        fields = [
            f"rank: {rank}",
            f"url: {json.dumps(coupang_url, ensure_ascii=False)}",
        ]
        if image_url:
            fields.append(f"image: {json.dumps(image_url, ensure_ascii=False)}")
        fields.append(f"title: {json.dumps(product_name, ensure_ascii=False)}")
        fields.append(f"sub: {json.dumps(hook_line, ensure_ascii=False)}")
        fields.append(f"price: {json.dumps(price, ensure_ascii=False)}")
        new_item = "    { " + ", ".join(fields) + " },\n"

        html = html.replace(ITEMS_MARKER, ITEMS_MARKER + new_item, 1)
        index_path.write_text(html, encoding="utf-8")

        run(["git", "-C", tmp, "add", "index.html"])
        run(["git", "-C", tmp, "-c", "user.email=bot@shopping-paradise.local",
             "-c", "user.name=shopping-paradise-bot", "commit", "-m",
             f"Add {product_name} ({rank}번째 실험) product card"])
        push_with_retry(tmp)
    print(f"[update_link_page] 링크 페이지 업데이트 완료: {product_name} ({rank}번째 실험)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--product-name", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--coupang-url", required=True)
    p.add_argument("--hook-line", required=True)
    p.add_argument("--image-url", default="", help="쿠팡 상품 원본 이미지 URL (product['productImage']). 없으면 페이지가 키워드 기반 이모지로 대체함.")
    args = p.parse_args()
    add_card(args.product_name, args.price, args.coupang_url, args.hook_line, args.image_url)
