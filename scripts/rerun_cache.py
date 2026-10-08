"""같은 날 같은 상품을 다시 돌릴 때 유료 생성물을 재사용하는 캐시.

2026-10-08: female 낮 편이 유튜브 업로드 단계(맨 끝)에서 410 → 401로 연달아 실패해
같은 상품으로 세 번 재실행했는데, 클라우드 샌드박스는 실행이 끝나면 work/가 통째로
사라지므로 HeyGen 훅/CTA 영상(유료)과 kie.ai 상품영상(유료)을 매번 새로 만들어 비용이
세 번 나갔다(사용자 지적: "재실행시 비용 안 들게 고쳐"). 유료 단계가 끝나는 즉시 결과
파일을 GCS(기존 백업 버킷, 라이프사이클로 자동삭제)에 올려두고, 재실행 때 날짜·캐릭터·
상품ID가 같으면 그걸 내려받아 유료 단계를 건너뛴다.

캐시는 부가 기능이다 — GCS 오류가 나면 경고만 찍고 원래대로 새로 생성한다.
"""
import hashlib
import json
import os
from pathlib import Path

GCS_BUCKET = "shopping-paradise-daily-raw-luith"


def _disabled() -> bool:
    # 2026-10-08: 끄는 스위치(RERUN_CACHE_DISABLE=1) — 쇼츠 채널 rerun_cache.py와 같은 이름
    return os.environ.get("RERUN_CACHE_DISABLE") == "1"


def _prefix(date: str, character: str, product_id) -> str:
    return f"rerun_cache/{date}/{character}/{product_id}"


def fetch(date: str, character: str, product_id, work_dir: Path, names: list[str]) -> bool:
    """names가 전부 캐시에 있으면 work_dir로 내려받고 True. 하나라도 없으면 False."""
    if _disabled():
        return False
    try:
        from google.cloud import storage

        bucket = storage.Client().bucket(GCS_BUCKET)
        blobs = [bucket.blob(f"{_prefix(date, character, product_id)}/{n}") for n in names]
        if not all(b.exists() for b in blobs):
            return False
        for b, n in zip(blobs, names):
            b.download_to_filename(str(work_dir / n))
        print(f"[재실행 캐시] {', '.join(names)} 재사용 (새로 생성 안 함)")
        return True
    except Exception as exc:
        print(f"[경고] 재실행 캐시 조회 실패, 새로 생성합니다: {exc}")
        return False


def store(date: str, character: str, product_id, work_dir: Path, names: list[str]) -> None:
    if _disabled():
        return
    try:
        from google.cloud import storage

        bucket = storage.Client().bucket(GCS_BUCKET)
        for n in names:
            p = work_dir / n
            if p.exists():
                bucket.blob(f"{_prefix(date, character, product_id)}/{n}").upload_from_filename(str(p))
        print(f"[재실행 캐시] {', '.join(names)} 저장")
    except Exception as exc:
        print(f"[경고] 재실행 캐시 저장 실패 (발행엔 영향 없음): {exc}")


# ---------------------------------------------------------------- 키 단위 캐시 (새 비교형 롱폼 longform_v2용)
# 2026-10-08: 비교형 롱폼(longform_v2.py)은 상품ID 하나로 묶이지 않아서(상품 6개 + 원고 + 문장별 TTS)
# 키 하나에 파일 하나씩 따로 저장한다. 원고·상품 선정은 날짜 키, TTS는 "읽는 글+목소리"의 해시 키.
# 실패는 경고만 하고 None/False — 원래대로 새로 만든다.
def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def get_bytes(key: str):
    """gs://<버킷>/rerun_cache/<key> 를 읽는다. 없거나 꺼져 있거나 오류면 None."""
    if _disabled():
        return None
    try:
        from google.cloud import storage

        blob = storage.Client().bucket(GCS_BUCKET).blob(f"rerun_cache/{key}")
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception as exc:
        print(f"[경고] 재실행 캐시 읽기 실패({key}), 새로 만듭니다: {exc}")
        return None


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> bool:
    """gs://<버킷>/rerun_cache/<key> 에 저장. 성공하면 True (실패해도 발행엔 영향 없음)."""
    if _disabled():
        return False
    try:
        from google.cloud import storage

        storage.Client().bucket(GCS_BUCKET).blob(f"rerun_cache/{key}").upload_from_string(data, content_type=content_type)
        return True
    except Exception as exc:
        print(f"[경고] 재실행 캐시 저장 실패({key}, 발행엔 영향 없음): {exc}")
        return False
