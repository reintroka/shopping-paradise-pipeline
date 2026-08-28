"""부업실험실 링크 페이지(reintroka/sidejoblab-links)에 새 상품 카드를 추가하고 배포.

실패해도(권한/네트워크 문제) 파이프라인 전체를 막으면 안 되므로, 호출하는 쪽에서
예외를 잡아 경고만 남기고 넘어가도록 설계됨 — 이 스크립트 자체는 그냥 실패시 예외를 던진다.
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

REPO_URL = "https://github.com/reintroka/sidejoblab-links.git"


def run(cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True)


def push_with_retry(repo_dir, max_tries: int = 3) -> None:
    for attempt in range(1, max_tries + 1):
        try:
            run(["git", "-C", repo_dir, "push"])
            return
        except subprocess.CalledProcessError as e:
            if attempt == max_tries:
                raise
            print(f"[update_link_page] push 실패(시도 {attempt}/{max_tries}): {e} — fetch+rebase 후 재시도")
            run(["git", "-C", repo_dir, "fetch", "origin"])
            run(["git", "-C", repo_dir, "rebase", "origin/main"])


def next_ordinal_label(html: str) -> str:
    """2026-08-27: 예전엔 "첫/두/세.../열 번째"처럼 순우리말 수사를 하드코딩된 목록
    (10개까지)에서 골라 썼는데, 10개를 넘으면 계속 "열 번째"만 반복되는 버그가 있었고
    (사용자가 "숫자가 커지면 어쩔라고 그래" 지적으로 발견), 애초에 순우리말 수사는
    숫자가 커질수록(예: "백서른두 번째") 아라비아 숫자보다 훨씬 길어져서 카드 태그
    공간에 안 맞을 위험도 있었음. 숫자+번째로 교체 — 몇 개가 쌓여도 짧고 스케일됨.

    2026-08-28: "len(labels) + 1"(고정카드=1번째로 이미 세어짐 가정)이 실제로는 틀려서
    카드가 9번째로 중복 발급되는 사고가 났다(사용자가 "10번째 실험인데 9번째로 잘못
    올라감" 지적으로 발견) — 고정카드는 "tag num"이 아니라 "tag pin"이라 애초에
    labels에 안 잡히므로 +1 가정 자체가 틀렸었음. 텍스트가 아니라 실제 박혀있는
    숫자 중 최댓값+1로 계산하도록 바꿔서, 카운트 가정 없이 항상 다음 번호를 구한다."""
    nums = [int(n) for n in re.findall(r'class="tag num">(\d+)번째 실험', html)]
    count = (max(nums) if nums else 1) + 1
    return f"{count}번째"


def add_card(product_name: str, price: str, coupang_url: str, hook_line: str):
    with tempfile.TemporaryDirectory() as tmp:
        run(["git", "clone", REPO_URL, tmp])
        index_path = Path(tmp) / "index.html"
        html = index_path.read_text(encoding="utf-8")

        label = next_ordinal_label(html)
        new_card = f"""      <a class="card" href="{coupang_url}" target="_blank" rel="noopener sponsored">
        <span class="tag num">{label} 실험</span>
        <p class="title">{product_name}</p>
        <p class="sub">{hook_line} <span class="price">{price}</span></p>
      </a>

"""
        # 자소서 프롬프트팩(핵심 상품)은 항상 목록 맨 위에 고정돼야 함(class="card pinned").
        # 새 카드를 그냥 <div class="list"> 바로 다음에 꽂으면 고정 카드보다 위로 밀려나므로,
        # 고정 카드가 있으면 그 블록 바로 다음에, 없으면 리스트 맨 위에 삽입한다.
        pinned_match = re.search(r'( {6}<a class="card pinned".*?</a>\n\n)', html, re.S)
        if pinned_match:
            insert_after = pinned_match.group(1)
            html = html.replace(insert_after, insert_after + new_card, 1)
        else:
            marker = '<div class="list">\n'
            if marker not in html:
                raise RuntimeError("index.html에서 삽입 위치(<div class=\"list\">)를 찾지 못했습니다.")
            html = html.replace(marker, marker + new_card, 1)
        index_path.write_text(html, encoding="utf-8")

        run(["git", "-C", tmp, "add", "index.html"])
        run(["git", "-C", tmp, "-c", "user.email=bot@shopping-paradise.local",
             "-c", "user.name=shopping-paradise-bot", "commit", "-m",
             f"Add {product_name} ({label} 실험) product card"])
        push_with_retry(tmp)
    print(f"[update_link_page] 링크 페이지 업데이트 완료: {product_name} ({label} 실험)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--product-name", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--coupang-url", required=True)
    p.add_argument("--hook-line", required=True)
    args = p.parse_args()
    add_card(args.product_name, args.price, args.coupang_url, args.hook_line)
