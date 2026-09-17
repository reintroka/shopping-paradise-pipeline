"""숏츠 발행 이력 기록 (compile_longform.py가 몇 개 쌓였는지 판단하는 데 사용).

레포 루트의 shorts_log.json에 매 업로드마다 한 줄씩 append.
각 항목: {date(KST, YYYY-MM-DD), datetime_kst, character, product_name, price,
          video_id, url, coupang_url, compiled_in(없으면 아직 롱폼에 안 들어감),
          specs(2026-09-01 추가, [{"title":..,"body":..}]x3 — 롱폼 딥다이브 나레이션
          생성 시 스펙 정보를 재사용하기 위함. 이 필드 추가 이전 발행분에는 없음 —
          compile_longform.py가 없는 경우 상품명/가격만으로 대체 처리한다.),
          product_image(2026-09-01 추가, 쿠팡 원본 상품사진 URL — 롱폼 딥다이브 배경을
          영상 프레임 캡처가 아니라 실제 상품사진을 build_graphics.build_product_assets로
          금테+그림자+반사 처리해서 쓰기 위함. 이 필드 이전 발행분엔 없어서
          compile_longform.py가 영상 프레임 캡처로 폴백한다.)}
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = REPO_ROOT / "shorts_log.json"
KST = timezone(timedelta(hours=9))


def load_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    return json.loads(LOG_PATH.read_text(encoding="utf-8"))


def save_log(entries: list[dict]):
    LOG_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def append_entry(character: str, product_name: str, price: int, video_id: str, url: str, coupang_url: str,
                  specs: list[dict] | None = None, product_image: str | None = None,
                  hook_speech: str | None = None, cta_speech: str | None = None, rank: int | None = None,
                  product_name_full: str | None = None):
    now_kst = datetime.now(KST)
    entries = load_log()
    entry = {
        "date": now_kst.strftime("%Y-%m-%d"),
        "datetime_kst": now_kst.isoformat(),
        "character": character,
        "product_name": product_name,
        "price": price,
        "video_id": video_id,
        "url": url,
        "coupang_url": coupang_url,
        "compiled_in": None,
    }
    if specs:
        entry["specs"] = specs
    if product_image:
        entry["product_image"] = product_image
    # 2026-09-18 추가: hook_speech/cta_speech/rank — run_cards.py(발행 2시간 후
    # 쓰레드 카드뉴스)가 이 실행을 다시 돌리지 않고도 이 로그 항목만으로 카드뉴스를
    # 재구성할 수 있게 하기 위함(사용자 지시: 텍스트→영상→카드뉴스 3단계 발행).
    if hook_speech:
        entry["hook_speech"] = hook_speech
    if cta_speech:
        entry["cta_speech"] = cta_speech
    if rank is not None:
        entry["rank"] = rank
    # 2026-09-18: 카드뉴스(run_cards.py)의 상품명 자동 줄바꿈/말줄임이 [:20]으로
    # 잘린 이름보다 원문을 쓰는 게 더 자연스러워서(build_thread_cards.py 참고)
    # 원문도 같이 남겨둠 — 없으면(구버전 항목) run_cards.py가 잘린 이름으로 폴백.
    if product_name_full:
        entry["product_name_full"] = product_name_full
    entries.append(entry)
    save_log(entries)
    return entries
