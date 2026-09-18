"""쇼핑의천국 쓰레드 텍스트 티저 — run_pipeline.py(영상 본 발행) 2시간 전에 실행해
"궁금증 유발" 텍스트만 먼저 올린다.

2026-09-18 도입: 사용자가 쓰레드를 직접 운영해보니 "텍스트로 먼저 궁금하게 하고
→ 영상으로 공개 → 카드뉴스로 정리"하는 3단계 발행이 좋겠다는 아이디어(사용자
지시). 상품/대본은 여기서 미리 만들어서 pending_release.json에 저장해두고,
run_pipeline.py가 2시간 뒤 이걸 그대로 이어받아 쓴다(상품을 두 번 고르지 않음).

사용법: python run_teaser.py --character female|male --reveal-time "낮 12시"

순서:
  1. 쿠팡 상품 선정 (pick_product) — 실패하면 중단
  2. Gemini 대본 생성 (gen_script) — 실패하면 중단
  3. 부업실험실 링크 페이지 카드 등록 (product_rank) — 실패해도 계속 진행
  4. pending_release.json에 상품+대본+순번 저장
  5. used_products.json + pending_release.json 커밋+푸시 (핵심 — 반드시 반영돼야
     2시간 뒤 run_pipeline.py가 같은 상품을 이어받을 수 있음)
  6. 쓰레드 텍스트 티저 발행 (부가, THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 시
     조용히 건너뜀) — hook_speech를 그대로 써서 상품명/가격은 공개하지 않고
     궁금증만 유발한다(스포일러 방지).
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PENDING_PATH = REPO_ROOT / "pending_release.json"
KST = timezone(timedelta(hours=9))

sys.path.insert(0, str(HERE))
import notify_telegram  # noqa: E402
import update_link_page  # noqa: E402

# 2026-09-18: run_pipeline.py(영상 발행)는 텔레그램 요약/실패 알림이 있는데
# run_teaser.py는 없어서(사용자 지적: "발행 구조 바꾼거 텔레그램 알림은
# 안오나?") 카드뉴스 단계처럼 여기도 상품 예약 실패/티저 발행 결과를
# run_pipeline.py와 동일한 패턴으로 텔레그램에 남긴다.
step_results = []


def notify(text: str) -> None:
    """텔레그램 알림 전송 자체가 실패해도 파이프라인 결과에 영향을 주지 않게 감싼다."""
    try:
        notify_telegram.send(text)
    except Exception as e:
        print(f"[경고] 텔레그램 알림 전송 실패: {e}")


def run(cmd, **kw):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def run_captured(cmd):
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (result.stdout or "") + (result.stderr or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if result.returncode != 0:
        raise RuntimeError(f"exit {result.returncode}: {output[-1500:].strip()}")
    return result


def push_with_retry(repo_root: Path, max_tries: int = 3) -> None:
    """run_pipeline.py의 동명 함수와 동일한 이유(detached HEAD 클론이라
    `git push origin HEAD:main`을 써야 함)로 동작한다."""
    for attempt in range(1, max_tries + 1):
        try:
            run(["git", "-C", str(repo_root), "push", "origin", "HEAD:main"])
            return
        except subprocess.CalledProcessError as e:
            if attempt == max_tries:
                raise
            print(f"[push_with_retry] push 실패(시도 {attempt}/{max_tries}): {e} — fetch+rebase 후 재시도")
            run(["git", "-C", str(repo_root), "fetch", "origin"])
            try:
                run(["git", "-C", str(repo_root), "rebase", "origin/main"])
            except subprocess.CalledProcessError:
                print("[push_with_retry] rebase 충돌 — abort 후 merge로 재시도")
                subprocess.run(["git", "-C", str(repo_root), "rebase", "--abort"])
                try:
                    run(["git", "-C", str(repo_root), "-c", "user.email=bot@shopping-paradise.local",
                         "-c", "user.name=shopping-paradise-bot", "merge", "origin/main", "--no-edit"])
                except subprocess.CalledProcessError:
                    subprocess.run(["git", "-C", str(repo_root), "merge", "--abort"])
                    raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--character", choices=["female", "male"], required=True)
    p.add_argument("--reveal-time", default="잠시 후", help='예: "낮 12시", "저녁 7시"')
    args = p.parse_args()

    work_dir = REPO_ROOT / "work" / args.character
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. 상품 선정 (run_pipeline.py의 1번과 동일)
    product_path = work_dir / "product.json"
    run(["python3", str(HERE / "pick_product.py"), "--out", str(product_path)])
    product = json.loads(product_path.read_text(encoding="utf-8"))

    # 2. 대본 생성 (run_pipeline.py의 2번과 동일)
    script_path = work_dir / "script.json"
    run(["python3", str(HERE / "gen_script.py"), "--product-json", str(product_path), "--out", str(script_path)])
    script_data = json.loads(script_path.read_text(encoding="utf-8"))
    coupang_url = product.get("shortUrl") or product["productUrl"]

    # 3. 링크 페이지 카드 등록 (부가) — run_pipeline.py의 2.5번과 동일
    product_rank = None
    try:
        product_rank = update_link_page.add_card(
            product["productName"][:20], f"{product['productPrice']:,}원대", coupang_url,
            script_data["hook_speech"], image_url=product["productImage"],
        )
    except Exception as e:
        print(f"[경고] 링크 페이지 업데이트 실패 (계속 진행): {e}")

    # 4. pending_release.json 저장 — run_pipeline.py가 2시간 뒤 이 파일로 상품을
    # 이어받는다. character별로 키를 나눠서 female/male 두 슬롯이 서로 안 겹치게 함.
    pending = json.loads(PENDING_PATH.read_text(encoding="utf-8")) if PENDING_PATH.exists() else {}
    pending[args.character] = {
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "product": product,
        "script_data": script_data,
        "product_rank": product_rank,
    }
    PENDING_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5. 커밋+푸시 (핵심) — used_products.json은 pick_product.py가 로컬에 이미
    # 갱신해뒀고, x_post_history.json은 gen_script.py가 갱신했을 수 있음.
    trackable = [
        f for f in ("used_products.json", "pending_release.json", "x_post_history.json")
        if (REPO_ROOT / f).exists()
    ]
    run(["git", "-C", str(REPO_ROOT), "add", *trackable])
    run(["git", "-C", str(REPO_ROOT), "-c", "user.email=bot@shopping-paradise.local",
         "-c", "user.name=shopping-paradise-bot", "commit", "-m",
         f"Teaser: reserve product {product['productId']} for {args.character}"])
    push_with_retry(REPO_ROOT)
    print(f"[run_teaser] 상품 예약 완료: {product['productName'][:20]} (2시간 뒤 run_pipeline.py가 이어받음)")

    # 6. 텍스트 티저 발행 (부가) — hook_speech만 써서 상품명/가격은 공개하지 않고
    # 궁금증만 유발한다(스포일러 방지). 2026-09-18: 쓰레드뿐 아니라 텍스트 포스팅이
    # 가능한 다른 채널(페이스북, X)에도 같은 티저를 올리기로 함(사용자 지시:
    # "쓰레드만 발행하지 말고.. 할수 있는곳에는 다 발행해"). 인스타그램은 텍스트
    # 단독 포스팅 자체가 없는 플랫폼이라 대상에서 제외.
    teaser_text = (
        f"⏰ {args.reveal_time}에 공개돼요\n\n"
        f"{script_data['hook_speech']}\n\n"
        f"오늘 쇼핑의천국이 고른 아이템, 조금 이따 여기서 공개할게요 👀"
    )

    # 6a. 쓰레드 텍스트 티저 — THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 시 조용히
    # 건너뜀(run_pipeline.py의 8.56번과 동일한 게이트, 계정을 며칠 지켜보는 중이라
    # 아직 비활성).
    if os.environ.get("THREADS_USER_ID") and os.environ.get("THREADS_ACCESS_TOKEN"):
        teaser_out = work_dir / "threads_teaser_result.json"
        try:
            run_captured([
                "python3", str(HERE / "post_threads.py"), "--mode", "text",
                "--caption", teaser_text, "--out", str(teaser_out),
            ])
            print("[run_teaser] 쓰레드 텍스트 티저 발행 완료")
            step_results.append(("쓰레드", True, None))
        except Exception as e:
            print(f"[경고] 쓰레드 텍스트 티저 발행 실패 (계속 진행, 상품 예약은 이미 완료됨): {e}")
            step_results.append(("쓰레드", False, str(e)))
    else:
        print("[run_teaser] 쓰레드 텍스트 티저 건너뜀 (THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 — 비활성화 상태)")
        step_results.append(("쓰레드", True, "비활성화(미설정) — 건너뜀"))

    # 6b. 페이스북 페이지 텍스트 티저 — FACEBOOK_ACCESS_TOKEN은 이미 활성화돼 있으므로
    # (run_pipeline.py가 매일 영상을 발행 중) 게이트 없이 바로 시도한다.
    fb_teaser_out = work_dir / "facebook_teaser_result.json"
    try:
        run_captured([
            "python3", str(HERE / "post_facebook.py"), "--mode", "text",
            "--caption", teaser_text, "--out", str(fb_teaser_out),
        ])
        print("[run_teaser] 페이스북 텍스트 티저 발행 완료")
        step_results.append(("페이스북", True, None))
    except Exception as e:
        print(f"[경고] 페이스북 텍스트 티저 발행 실패 (계속 진행): {e}")
        step_results.append(("페이스북", False, str(e)))

    # 6c. X 텍스트 티저 — post_x.py는 --image가 원래 선택 인자라 텍스트 단독
    # 트윗을 그대로 지원한다(코드 변경 불필요).
    try:
        run_captured(["python3", str(HERE / "post_x.py"), "--text", teaser_text])
        print("[run_teaser] X 텍스트 티저 발행 완료")
        step_results.append(("X", True, None))
    except Exception as e:
        print(f"[경고] X 텍스트 티저 발행 실패 (계속 진행): {e}")
        step_results.append(("X", False, str(e)))

    # 7. 텔레그램 요약 알림 (run_pipeline.py 14번 스텝과 동일 패턴) — 상품 예약은
    # 이미 커밋+푸시됐으니 여기서부터는 플랫폼별 발행 결과만 요약해서 보낸다.
    lines = [f"[쇼핑의천국] {args.character} 텍스트 티저 ({args.reveal_time} 공개 예고)"]
    for name, ok, note in step_results:
        if ok and note:
            lines.append(f"- {name}: {note}")
        elif ok:
            lines.append(f"- {name}: 성공")
        else:
            lines.append(f"- {name}: 실패 ({note})")
    notify("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        notify(f"[쇼핑의천국] 텍스트 티저 파이프라인 실패 (상품 예약 안 됐을 수 있음)\n{e}")
        raise
