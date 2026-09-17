"""쇼핑의천국 쓰레드 카드뉴스 마무리 발행 — run_pipeline.py(영상 본 발행) 2시간 후에
실행해 같은 상품을 카드뉴스(캐러셀)로 정리해서 올린다.

2026-09-18 도입: "텍스트로 궁금하게(run_teaser.py) → 영상 공개(run_pipeline.py) →
카드뉴스로 정리(이 스크립트)" 3단계 발행 아이디어(사용자 지시). 이 스크립트는
새 CCR 세션(fresh clone)이라 run_pipeline.py가 쓰던 work_dir 파일이 이미 없으므로,
shorts_log.json에 남겨둔 오늘자 항목(hook_speech/cta_speech/rank 포함,
run_pipeline.py 11번 스텝에서 저장)을 다시 읽어 카드뉴스를 재구성한다 — 상품을
다시 고르거나 영상을 다시 만들지 않는다.

사용법: python run_cards.py --character female|male
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KST = timezone(timedelta(hours=9))
COUPANG_DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

sys.path.insert(0, str(HERE))
import build_thread_cards  # noqa: E402


def _find_todays_entry(character: str) -> dict:
    log_path = REPO_ROOT / "shorts_log.json"
    if not log_path.exists():
        raise RuntimeError("shorts_log.json이 없습니다 — run_pipeline.py가 아직 한 번도 발행하지 않은 상태")
    entries = json.loads(log_path.read_text(encoding="utf-8"))
    today = datetime.now(KST).strftime("%Y-%m-%d")
    matches = [e for e in entries if e.get("date") == today and e.get("character") == character]
    if not matches:
        raise RuntimeError(f"오늘({today}) {character} 발행 기록을 shorts_log.json에서 찾을 수 없습니다 — "
                            "run_pipeline.py가 아직 안 돌았거나 실패했을 수 있음")
    entry = matches[-1]
    for field in ("hook_speech", "cta_speech", "specs", "product_image"):
        if field not in entry:
            raise RuntimeError(f"오늘 발행 기록에 {field}가 없습니다(구버전 항목?) — 카드뉴스를 만들 수 없음: {entry}")
    return entry


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--character", choices=["female", "male"], required=True)
    args = p.parse_args()

    entry = _find_todays_entry(args.character)

    if not (os.environ.get("THREADS_USER_ID") and os.environ.get("THREADS_ACCESS_TOKEN")):
        print("[run_cards] 건너뜀 (THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 — 비활성화 상태)")
        return

    work_dir = REPO_ROOT / "work" / args.character
    work_dir.mkdir(parents=True, exist_ok=True)
    img_path = work_dir / "product_for_cards.jpg"
    req = urllib.request.Request(entry["product_image"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        img_path.write_bytes(resp.read())

    specs = entry["specs"]
    product_name = entry.get("product_name_full") or entry["product_name"]
    card_paths = build_thread_cards.build_all(
        work_dir,
        product_name, f"{entry['price']:,}원대", img_path,
        (specs[0]["title"], specs[0]["body"]),
        (specs[1]["title"], specs[1]["body"]),
        (specs[2]["title"], specs[2]["body"]),
        entry["hook_speech"], entry["cta_speech"],
        rank=entry.get("rank"),
    )

    caption = f"{COUPANG_DISCLOSURE}\n\n오늘 소개한 상품, 다시 한 번 정리해드려요 📝\n\n" \
              f"{product_name} ({entry['price']:,}원대)\n\n프로필 링크에서 다시 확인하세요"
    if entry.get("rank") is not None:
        caption = f"\U0001F50E [No.{entry['rank']}] 이 번호로 프로필 링크에서 다시 찾을 수 있어요\n\n{caption}"

    out_path = work_dir / "threads_cards_result.json"
    cmd = [
        "python3", str(HERE / "post_threads.py"), "--mode", "carousel",
        "--images", ",".join(str(p) for p in card_paths),
        "--caption", caption, "--out", str(out_path),
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print("[run_cards] 쓰레드 카드뉴스 발행 완료")


if __name__ == "__main__":
    main()
