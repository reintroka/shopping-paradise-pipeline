"""같은 날 같은 상품을 다시 돌릴 때 유료 생성물을 재사용하는 캐시.

2026-10-08: female 낮 편이 유튜브 업로드 단계(맨 끝)에서 410 → 401로 연달아 실패해
같은 상품으로 세 번 재실행했는데, 클라우드 샌드박스는 실행이 끝나면 work/가 통째로
사라지므로 HeyGen 훅/CTA 영상(유료)과 kie.ai 상품영상(유료)을 매번 새로 만들어 비용이
세 번 나갔다(사용자 지적: "재실행시 비용 안 들게 고쳐"). 유료 단계가 끝나는 즉시 결과
파일을 GCS(기존 백업 버킷, 라이프사이클로 자동삭제)에 올려두고, 재실행 때 날짜·캐릭터·
상품ID가 같으면 그걸 내려받아 유료 단계를 건너뛴다.

캐시는 부가 기능이다 — GCS 오류가 나면 경고만 찍고 원래대로 새로 생성한다.
"""
from pathlib import Path

GCS_BUCKET = "shopping-paradise-daily-raw-luith"


def _prefix(date: str, character: str, product_id) -> str:
    return f"rerun_cache/{date}/{character}/{product_id}"


def fetch(date: str, character: str, product_id, work_dir: Path, names: list[str]) -> bool:
    """names가 전부 캐시에 있으면 work_dir로 내려받고 True. 하나라도 없으면 False."""
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
