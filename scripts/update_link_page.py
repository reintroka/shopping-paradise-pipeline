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


def next_ordinal_label(html: str) -> str:
    labels = re.findall(r'class="tag num">([^<]+) 실험', html)
    korean_numbers = ["첫", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열"]
    count = len(labels) + 1  # + 1 (pinned item은 "첫 실험"으로 이미 세어짐 별도 처리 없이 근사)
    idx = min(count, len(korean_numbers) - 1)
    return f"{korean_numbers[idx]} 번째"


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
        marker = '<div class="list">\n'
        if marker not in html:
            raise RuntimeError("index.html에서 삽입 위치(<div class=\"list\">)를 찾지 못했습니다.")
        html = html.replace(marker, marker + new_card, 1)
        index_path.write_text(html, encoding="utf-8")

        run(["git", "-C", tmp, "add", "index.html"])
        run(["git", "-C", tmp, "-c", "user.email=bot@shopping-paradise.local",
             "-c", "user.name=shopping-paradise-bot", "commit", "-m",
             f"Add {product_name} ({label} 실험) product card"])
        run(["git", "-C", tmp, "push"])
    print(f"[update_link_page] 링크 페이지 업데이트 완료: {product_name} ({label} 실험)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--product-name", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--coupang-url", required=True)
    p.add_argument("--hook-line", required=True)
    args = p.parse_args()
    add_card(args.product_name, args.price, args.coupang_url, args.hook_line)
