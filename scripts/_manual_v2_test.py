"""임시 테스트 스크립트 — v15 디자인 이식 후 클라우드 샌드박스에서 전체가 실제로
도는지 확인 (헤이젠 신규 생성 없음, 기존 훅/CTA 재사용). numpy 등 의존성이
실제로 설치되는지까지 포함해서 검증하는 게 목적.

테스트 끝나면 이 파일과 test_assets/는 지울 것.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import build_graphics  # noqa: E402
import google_tts  # noqa: E402
import assemble_video  # noqa: E402

work_dir = REPO_ROOT / "work" / "female"
work_dir.mkdir(parents=True, exist_ok=True)

shutil.copyfile(REPO_ROOT / "test_assets" / "hook_test.mp4", work_dir / "hook.mp4")
shutil.copyfile(REPO_ROOT / "test_assets" / "cta_test.mp4", work_dir / "cta.mp4")

print("[1/3] 그래픽 생성")
build_graphics.build_all(
    work_dir,
    "LG 그램15",
    "898,000원대",
    REPO_ROOT / "test_assets" / "product_test.jpg",
    ("성능", "인텔 i5 · 16GB RAM"),
    ("저장공간", "512GB SSD (256GB×2 듀얼)"),
    ("화면 · 무게", "15.6형 FHD IPS · 초경량"),
    "무게 하나로 후기 폭발한 노트북, 이유가 있더라고요.",
    "이 정도면 안 살 이유가 없죠. 프로필 링크에서 확인하세요.",
)

print("[2/3] Google TTS 나레이션 3개 생성")
texts = [
    "인텔 코어 아이파이브에 십육 기가 램이라 웬만한 작업은 버벅임 없이 돌아가요.",
    "저장공간은 오백십이 기가 에스에스디라 속도까지 챙겼고요.",
    "화면은 큼직한 십오점육 인치인데 무게는 정말 가벼워요.",
]
for i, t in enumerate(texts, start=1):
    meta = google_tts.synthesize(t, "female", work_dir / f"narration{i}.mp3")
    print(f"  narration{i}: {meta['duration']:.2f}초")

print("[3/3] 최종 조립")
final_video = work_dir / "final_test.mp4"
assemble_video.assemble(work_dir, final_video)
print(f"완료: {final_video}")
