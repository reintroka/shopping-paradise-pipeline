# shopping-paradise-pipeline

쇼핑의천국 유튜브 채널(쿠팡파트너스 제품추천 숏츠) 완전자동화 파이프라인.
2026-08-26 세션에서 확정된 "골드 럭셔리" 디자인 시스템(크림 배경+골드 카드+원형 프레임
제품사진+골드 라벨 타이틀)을 재현. 상세 배경은 project memory `project_shoppingparadise_youtube.md` 참고.

## 실행

```bash
pip install -r requirements.txt
apt install -y ffmpeg   # 클라우드 환경 setup script에 이미 포함되어 있어야 함
python3 scripts/run_pipeline.py --character female  # 지은 (낮 12시)
python3 scripts/run_pipeline.py --character male    # 민준 (저녁 7시)
```

## 필요한 환경변수 (클라우드 환경 "shopping-paradise-automation"에 이미 설정됨)

`HEYGEN_API_KEY`, `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`, `GEMINI_API_KEY`,
`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`,
`X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`

## 구조

- `assets/characters/{female,male}/` — 캐릭터 레퍼런스 이미지 28장씩
- `assets/fonts/NotoSansKR-Regular.ttf` — 가변폰트(클라우드 Linux엔 맑은고딕 없음)
- `assets/logo/channel_logo.png` — 쇼핑의천국 실제 로고
- `assets/sfx/` — pop.mp3(카드 등장), whoosh-short.mp3(컷 전환)
- `scripts/pick_product.py` — 쿠팡 API로 고가 전자제품 선정, 중복 방지(`used_products.json`)
- `scripts/gen_script.py` — Gemini로 훅/스펙/CTA 대본 + SEO 메타데이터 생성
- `scripts/build_graphics.py` — PIL로 골드 럭셔리 디자인 그래픽 생성
- `scripts/heygen_gen.py` — HeyGen 아바타 훅/CTA 영상 + 나레이션 TTS
- `scripts/assemble_video.py` — ffmpeg 최종 조립
- `scripts/upload_youtube.py` — 공개 업로드 (채널 ID 검증 포함)
- `scripts/post_x.py` — X 포스트 (링크 없이, 프로필 바이오 링크 유도)
- `scripts/post_comment.py` — 영상 공개 확인 후 댓글 홍보 (재시도 포함)
- `scripts/update_link_page.py` — 부업실험실 링크 페이지에 상품 카드 추가
- `scripts/run_pipeline.py` — 전체 오케스트레이터

## 알아둘 것

- HeyGen 훅+CTA 생성만 비용 발생(초당 $0.05), 나머지는 무료/저비용.
- 유튜브/X 포스트 실패는 파이프라인을 막지 않는 부가 스텝(`soft_step`)이고,
  상품 선정/대본생성/HeyGen/조립/유튜브업로드는 실패시 전체 중단.
- [[feedback-heygen-no-regenerate-without-confirm]] 원칙은 이 자동화에는 적용 안 됨
  (매번 새 상품 → 매번 새 생성이 정상, "재생성 낭비 금지"는 같은 영상 반복수정 얘기였음).
