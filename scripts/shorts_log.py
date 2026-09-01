"""숏츠 발행 이력 기록 (compile_longform.py가 몇 개 쌓였는지 판단하는 데 사용).

레포 루트의 shorts_log.json에 매 업로드마다 한 줄씩 append.
각 항목: {date(KST, YYYY-MM-DD), datetime_kst, character, product_name, price,
          video_id, url, coupang_url, compiled_in(없으면 아직 롱폼에 안 들어감),
          specs(2026-09-01 추가, [{"title":..,"body":..}]x3 — 롱폼 딥다이브 나레이션
          생성 시 스펙 정보를 재사용하기 위함. 이 필드 추가 이전 발행분에는 없음 —
          compile_longform.py가 없는 경우 상품명/가격만으로 대체 처리한다.)}
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
                  specs: list[dict] | None = None):
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
    entries.append(entry)
    save_log(entries)
    return entries
