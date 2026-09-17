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
import notify_telegram  # noqa: E402


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


def _run_captured(cmd):
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (result.stdout or "") + (result.stderr or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if result.returncode != 0:
        raise RuntimeError(f"exit {result.returncode}: {output[-1500:].strip()}")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--character", choices=["female", "male"], required=True)
    args = p.parse_args()

    entry = _find_todays_entry(args.character)

    work_dir = REPO_ROOT / "work" / args.character
    work_dir.mkdir(parents=True, exist_ok=True)
    img_path = work_dir / "product_for_cards.jpg"
    req = urllib.request.Request(entry["product_image"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        img_path.write_bytes(resp.read())

    specs = entry["specs"]
    product_name = entry.get("product_name_full") or entry["product_name"]
    # 2026-09-18: 카드뉴스는 쓰레드 전용이 아니라 인스타그램/페이스북/X에도 같이
    # 발행한다(사용자 지시: "쓰레드만 발행하지 말고.. 할수 있는곳에는 다 발행해") —
    # 카드 이미지 자체는 한 번만 만들어서 4개 플랫폼이 재사용한다.
    card_paths = build_thread_cards.build_all(
        work_dir,
        product_name, f"{entry['price']:,}원대", img_path,
        (specs[0]["title"], specs[0]["body"]),
        (specs[1]["title"], specs[1]["body"]),
        (specs[2]["title"], specs[2]["body"]),
        entry["hook_speech"], entry["cta_speech"],
        rank=entry.get("rank"),
    )
    card_paths_str = ",".join(str(p) for p in card_paths)

    caption = f"{COUPANG_DISCLOSURE}\n\n오늘 소개한 상품, 다시 한 번 정리해드려요 📝\n\n" \
              f"{product_name} ({entry['price']:,}원대)\n\n프로필 링크에서 다시 확인하세요"
    if entry.get("rank") is not None:
        caption = f"\U0001F50E [No.{entry['rank']}] 이 번호로 프로필 링크에서 다시 찾을 수 있어요\n\n{caption}"

    # 1. 쓰레드 카드뉴스 — THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 시 건너뜀
    # (계정을 며칠 지켜보는 중이라 아직 비활성, run_pipeline.py 8.56번과 동일 게이트).
    if os.environ.get("THREADS_USER_ID") and os.environ.get("THREADS_ACCESS_TOKEN"):
        try:
            threads_out = work_dir / "threads_cards_result.json"
            _run_captured([
                "python3", str(HERE / "post_threads.py"), "--mode", "carousel",
                "--images", card_paths_str, "--caption", caption, "--out", str(threads_out),
            ])
            print("[run_cards] 쓰레드 카드뉴스 발행 완료")
        except Exception as e:
            print(f"[경고] 쓰레드 카드뉴스 발행 실패 (계속 진행): {e}")
    else:
        print("[run_cards] 쓰레드 카드뉴스 건너뜀 (THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 — 비활성화 상태)")

    # 2. 인스타그램 캐러셀 — IG_USER_ID/IG_ACCESS_TOKEN은 이미 활성화돼 있으므로
    # (run_pipeline.py가 매일 릴스를 발행 중) 게이트 없이 바로 시도한다.
    try:
        ig_out = work_dir / "instagram_cards_result.json"
        _run_captured([
            "python3", str(HERE / "post_instagram.py"), "--mode", "carousel",
            "--images", card_paths_str, "--caption", caption, "--out", str(ig_out),
        ])
        print("[run_cards] 인스타그램 카드뉴스 발행 완료")
    except Exception as e:
        print(f"[경고] 인스타그램 카드뉴스 발행 실패 (계속 진행): {e}")

    # 3. 페이스북 카드뉴스(멀티포토) — FACEBOOK_ACCESS_TOKEN도 이미 활성화 상태.
    try:
        fb_out = work_dir / "facebook_cards_result.json"
        _run_captured([
            "python3", str(HERE / "post_facebook.py"), "--mode", "carousel",
            "--images", card_paths_str, "--caption", caption, "--out", str(fb_out),
        ])
        print("[run_cards] 페이스북 카드뉴스 발행 완료")
    except Exception as e:
        print(f"[경고] 페이스북 카드뉴스 발행 실패 (계속 진행): {e}")

    # 4. X — 공식 캐러셀 개념은 없지만 트윗 하나에 이미지 최대 4장까지 첨부 가능해서
    # (X 자체 한도) 카드 3장을 그대로 다 첨부한다(2026-09-18, post_x.py --images 추가).
    try:
        _run_captured(["python3", str(HERE / "post_x.py"), "--text", caption, "--images", card_paths_str])
        print("[run_cards] X 카드뉴스(3장) 발행 완료")
    except Exception as e:
        print(f"[경고] X 카드뉴스 발행 실패 (계속 진행): {e}")

    # 5. 틱톡용 — API(post_tiktok.py --mode photo, PULL_FROM_URL)는 시도하지 않고
    # 처음부터 텔레그램으로 카드 이미지를 바로 전송해 사람이 직접 업로드하게 한다.
    # 2026-09-18: 같은 계정군의 coredlab(명리마스터) 코드베이스에서 이미 똑같은 걸
    # API로 시도했다가 "TikTok photo-mode direct API posting is blocked pending
    # audit/URL verification"으로 확인되어 텔레그램 전송으로 교체한 이력을 발견함
    # (commit 824e084, 2026-09-02) — 여기서도 API를 붙였다가 매번 실패하고 조용히
    # 넘어가느니, 처음부터 검증된 방식(텔레그램)을 쓰는 게 낫다고 판단.
    try:
        notify_telegram.send_photos(
            [str(p) for p in card_paths],
            f"🎵 틱톡용 카드뉴스 (수동 업로드 필요)\n\n{caption}",
        )
        print("[run_cards] 틱톡용 카드뉴스 텔레그램 전송 완료 (수동 업로드 필요)")
    except Exception as e:
        print(f"[경고] 틱톡용 텔레그램 전송 실패 (계속 진행): {e}")


if __name__ == "__main__":
    main()
