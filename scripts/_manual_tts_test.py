"""임시 테스트 스크립트 — Google TTS 교체가 잘 되는지, 기존(재사용) 훅/CTA 영상 +
새 나레이션으로 조립까지 되는지만 확인. 헤이젠 신규 생성 없음(비용 안 씀).

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
    "무게 하나로", "후기 폭발 노트북",
    hook_speech="무게 하나로 후기 폭발한 노트북, 이유가 있더라고요.",
    cta_speech="이 정도 가벼움이면 안 살 이유가 없죠.",
)

print("[2/3] Google TTS 나레이션 생성")
narration_script = (
    "인텔 코어 아이파이브에 십육 기가 램이라 웬만한 작업은 버벅임 없이 돌아가요. "
    "저장공간은 오백십이 기가 에스에스디라 속도까지 챙겼고요. "
    "화면은 큼직한 십오점육 인치인데 무게는 정말 가벼워요."
)
meta = google_tts.synthesize(narration_script, "female", work_dir / "middle_narration.mp3")
print(f"  나레이션 길이: {meta['duration']:.2f}초, 보이스: {meta['voice_name']}")

print("[3/3] 최종 조립")
final_video = work_dir / "final_test.mp4"
assemble_video.assemble(work_dir, final_video)
print(f"완료: {final_video}")
