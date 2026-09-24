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
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KST = timezone(timedelta(hours=9))
COUPANG_DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
# run_pipeline.py 참고: 신규 쓰레드 계정은 프로필 링크가 조용히 지워지는 제약이 있어
# "프로필 링크" 문구가 무용지물이 된다 — 쓰레드는 게시물 URL을 자동 하이퍼링크
# 처리하므로 쓰레드용 캡션에만 실제 링크를 붙인다.
LINK_PAGE_URL = "https://reintroka.github.io/sidejoblab-links"

sys.path.insert(0, str(HERE))
import build_thread_cards  # noqa: E402
import notify_telegram  # noqa: E402

# 2026-09-18: 틱톡용 텔레그램 전송(5번)만 있고, 나머지 4개 플랫폼(쓰레드/인스타/
# 페북/X) 카드뉴스 발행 결과는 콘솔 경고로만 남고 텔레그램엔 전혀 안 갔음(사용자
# 지적: "발행 구조 바꾼거 텔레그램 알림은 안오나?"). run_pipeline.py와 동일하게
# 요약 알림 + 실패 알림을 추가한다.
step_results = []


def notify(text: str) -> None:
    """텔레그램 알림 전송 자체가 실패해도 파이프라인 결과에 영향을 주지 않게 감싼다."""
    try:
        notify_telegram.send(text)
    except Exception as e:
        print(f"[경고] 텔레그램 알림 전송 실패: {e}")


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


def _run(cmd, **kw):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def _push_with_retry(repo_root: Path, max_tries: int = 3) -> None:
    """run_pipeline.py의 동명 함수와 동일한 이유로 필요 — 이 CCR 세션도 레포를
    detached HEAD로 클론하므로 `git push origin HEAD:main`을 써야 하고, 그 사이
    origin이 앞서나갔으면(다른 채널/슬롯의 동시 실행) fetch+rebase 후 재시도한다."""
    for attempt in range(1, max_tries + 1):
        try:
            _run(["git", "-C", str(repo_root), "push", "origin", "HEAD:main"])
            return
        except subprocess.CalledProcessError as e:
            if attempt == max_tries:
                raise
            print(f"[push_with_retry] push 실패(시도 {attempt}/{max_tries}): {e} — fetch+rebase 후 재시도")
            _run(["git", "-C", str(repo_root), "fetch", "origin"])
            _run(["git", "-C", str(repo_root), "rebase", "origin/main"])


def _mark_cards_published(character: str) -> None:
    """오늘자 shorts_log.json 항목에 cards_published_at을 찍어 커밋+푸시한다.

    2026-09-24: 저녁 9시 카드뉴스가 같은 날 두 번 발행되는 사고 발생(사용자 보고) —
    이 스크립트엔 "오늘 이미 발행했는지" 확인하는 장치가 전혀 없어서, 같은 슬롯이
    재시도/재트리거되면(예: CCR 세션 재실행, 사람의 수동 재실행) shorts_log.json의
    같은 항목을 또 읽어 4개 플랫폼에 그대로 재발행했다. 이 스크립트는 매번 새
    CCR 세션(fresh clone)이라 로컬 work_dir 상태로는 중복을 막을 수 없으므로(
    docstring 참고), git으로 커밋되는 shorts_log.json 자체에 마커를 남겨 다음
    실행(다른 세션이어도)이 읽을 수 있게 한다 — mystery-records의 cross-slot
    duplicate-publish 가드와 동일한 패턴."""
    log_path = REPO_ROOT / "shorts_log.json"
    entries = json.loads(log_path.read_text(encoding="utf-8"))
    today = datetime.now(KST).strftime("%Y-%m-%d")
    matches = [e for e in entries if e.get("date") == today and e.get("character") == character]
    if not matches:
        return
    matches[-1]["cards_published_at"] = datetime.now(KST).isoformat()
    log_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    _run(["git", "-C", str(REPO_ROOT), "add", "shorts_log.json"])
    _run(["git", "-C", str(REPO_ROOT), "-c", "user.email=bot@shopping-paradise.local",
          "-c", "user.name=shopping-paradise-bot", "commit", "-m",
          f"Mark {character} card news published for {today}"])
    _push_with_retry(REPO_ROOT)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--character", choices=["female", "male"], required=True)
    args = p.parse_args()

    entry = _find_todays_entry(args.character)

    if entry.get("cards_published_at"):
        # 2026-09-24: 같은 슬롯이 재트리거되면(재시도/수동 재실행) 여기서 조용히
        # 막는다 — 아래에서 계속 진행하면 4개 플랫폼에 오늘자 카드뉴스를 그대로
        # 다시 올리게 된다(실제 사고: 9시 발행에서 카드뉴스 2번 발행).
        msg = (f"[쇼핑의천국] {args.character} 카드뉴스 중복 실행 감지 — 건너뜀 "
               f"(이미 {entry['cards_published_at']}에 발행됨)")
        print(f"[run_cards] {msg}")
        notify(msg)
        return

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
            # 쿠팡 고지 문구를 맨 앞으로 재배치(run_pipeline.py와 동일 이유) —
            # 링크 때문에 고지 문구가 둘째 문단으로 밀려나지 않게.
            threads_caption = f"{COUPANG_DISCLOSURE}\n\n🔗 {LINK_PAGE_URL}\n\n" + (
                caption.replace(f"{COUPANG_DISCLOSURE}\n\n", "", 1)
            )
            _run_captured([
                "python3", str(HERE / "post_threads.py"), "--mode", "carousel",
                "--images", card_paths_str, "--caption", threads_caption, "--out", str(threads_out),
            ])
            print("[run_cards] 쓰레드 카드뉴스 발행 완료")
            step_results.append(("쓰레드", True, None))
        except Exception as e:
            print(f"[경고] 쓰레드 카드뉴스 발행 실패 (계속 진행): {e}")
            step_results.append(("쓰레드", False, str(e)))
    else:
        print("[run_cards] 쓰레드 카드뉴스 건너뜀 (THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 — 비활성화 상태)")
        step_results.append(("쓰레드", True, "비활성화(미설정) — 건너뜀"))

    # 2. 인스타그램 캐러셀 — IG_USER_ID/IG_ACCESS_TOKEN은 이미 활성화돼 있으므로
    # (run_pipeline.py가 매일 릴스를 발행 중) 게이트 없이 바로 시도한다.
    try:
        ig_out = work_dir / "instagram_cards_result.json"
        _run_captured([
            "python3", str(HERE / "post_instagram.py"), "--mode", "carousel",
            "--images", card_paths_str, "--caption", caption, "--out", str(ig_out),
        ])
        print("[run_cards] 인스타그램 카드뉴스 발행 완료")
        step_results.append(("인스타그램", True, None))
    except Exception as e:
        print(f"[경고] 인스타그램 카드뉴스 발행 실패 (계속 진행): {e}")
        step_results.append(("인스타그램", False, str(e)))

    # 3. 페이스북 카드뉴스(멀티포토) — FACEBOOK_ACCESS_TOKEN도 이미 활성화 상태.
    try:
        fb_out = work_dir / "facebook_cards_result.json"
        _run_captured([
            "python3", str(HERE / "post_facebook.py"), "--mode", "carousel",
            "--images", card_paths_str, "--caption", caption, "--out", str(fb_out),
        ])
        print("[run_cards] 페이스북 카드뉴스 발행 완료")
        step_results.append(("페이스북", True, None))
    except Exception as e:
        print(f"[경고] 페이스북 카드뉴스 발행 실패 (계속 진행): {e}")
        step_results.append(("페이스북", False, str(e)))

    # 4. X — 공식 캐러셀 개념은 없지만 트윗 하나에 이미지 최대 4장까지 첨부 가능해서
    # (X 자체 한도) 카드 3장을 그대로 다 첨부한다(2026-09-18, post_x.py --images 추가).
    try:
        _run_captured(["python3", str(HERE / "post_x.py"), "--text", caption, "--images", card_paths_str])
        print("[run_cards] X 카드뉴스(3장) 발행 완료")
        step_results.append(("X", True, None))
    except Exception as e:
        print(f"[경고] X 카드뉴스 발행 실패 (계속 진행): {e}")
        step_results.append(("X", False, str(e)))

    # 5. 틱톡용 — API(post_tiktok.py --mode photo, PULL_FROM_URL)는 시도하지 않고
    # 처음부터 텔레그램으로 카드 이미지를 바로 전송해 사람이 직접 업로드하게 한다.
    # 2026-09-18: 같은 계정군의 coredlab(명리마스터) 코드베이스에서 이미 똑같은 걸
    # API로 시도했다가 "TikTok photo-mode direct API posting is blocked pending
    # audit/URL verification"으로 확인되어 텔레그램 전송으로 교체한 이력을 발견함
    # (commit 824e084, 2026-09-02) — 여기서도 API를 붙였다가 매번 실패하고 조용히
    # 넘어가느니, 처음부터 검증된 방식(텔레그램)을 쓰는 게 낫다고 판단.
    #
    # 캡션은 위에서 새로 지은 짧은 recap 문구(caption) 대신, 그날 인스타그램에 이미
    # 발행됐던 ig_caption 원문을 그대로 재사용한다 — 훅/셀링포인트/CTA는 물론 해시태그
    # 8~12개까지 이미 다 포함돼 있어서, 사람이 텔레그램에서 그대로 복사해 틱톡에
    # 붙여넣기만 하면 된다(사용자 요청: "텔레그램으로 이미지 설명글 태그 보내").
    # ig_caption이 없는 구버전 로그 항목이면 recap 캡션(태그 없음)으로 폴백.
    # ig_caption의 "댓글에 '가격'..." 문구는 인스타그램 댓글 자동응답(DM)에 연결된
    # 것이라 틱톡에는 적용되지 않는다(틱톡은 자동 DM 자체가 없음) — 그대로 두면
    # 사람이 복붙할 때마다 매번 지워야 해서, 여기서 미리 제거해 캡션을 바로
    # 복사-붙여넣기 가능한 상태로 만든다(2026-09-19, 사용자 요청).
    tiktok_caption = entry.get("ig_caption") or caption
    tiktok_caption = re.sub(
        r"\n?댓글에 '가격'이라고 남겨주시면 DM으로 바로 알려드려요!\n?", "\n", tiktok_caption,
    ).strip()
    try:
        notify_telegram.send("🎵 틱톡용 카드뉴스 (수동 업로드 필요)")
        notify_telegram.send_photos([str(p) for p in card_paths], tiktok_caption)
        print("[run_cards] 틱톡용 카드뉴스 텔레그램 전송 완료 (수동 업로드 필요)")
        step_results.append(("틱톡(텔레그램 전송)", True, None))
    except Exception as e:
        print(f"[경고] 틱톡용 텔레그램 전송 실패 (계속 진행): {e}")
        step_results.append(("틱톡(텔레그램 전송)", False, str(e)))

    # 5.5. shorts_log.json에 cards_published_at 마커를 남겨 같은 슬롯의 재트리거를
    # 막는다(위 중복 가드 참고). 개별 플랫폼 성공/실패와 무관하게 여기까지 왔다는 건
    # 이미 4개 플랫폼에 발행을 "시도"했다는 뜻이므로, 마커 기록 자체가 실패해도
    # 발행 결과에 영향을 주면 안 된다(콘솔 경고만 남기고 계속 진행).
    try:
        _mark_cards_published(args.character)
    except Exception as e:
        print(f"[경고] cards_published_at 마커 기록 실패 (무시하고 계속): {e}")

    # 6. 텔레그램 요약 알림 (run_pipeline.py 14번 스텝과 동일 패턴) — 틱톡 카드
    # 이미지/캡션은 5번에서 이미 별도 메시지로 갔으니, 여기서는 플랫폼별 성공/
    # 실패 결과만 한 번 더 요약해서 보낸다(개별 실패가 콘솔 경고로만 남고
    # 조용히 묻히지 않게).
    lines = [f"[쇼핑의천국] {args.character} 카드뉴스 마무리 발행 ({product_name})"]
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
        notify(f"[쇼핑의천국] 카드뉴스 마무리 발행 파이프라인 실패\n{e}")
        raise
