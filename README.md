# shopping-paradise-pipeline

쇼핑의천국 유튜브 채널(쿠팡파트너스 제품추천 숏츠) 완전자동화 파이프라인.
2026-08-27 로컬 편집 세션에서 확정된 v15 디자인(골드 포일 타이틀+유리질감 카드+
아이콘+스텝배지+제품 그림자/리플렉션+비네트+크래시줌 컷 전환+세이프존 자막)을
재현. 상세 배경은 project memory `project_shoppingparadise_youtube.md` 참고.

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
`X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`,
`GOOGLE_TTS_API_KEY` **(2026-08-27 추가 — 아직 등록 안 됐으면 아래대로 발급해서
"shopping-paradise-automation" 환경 시크릿에 추가해야 나레이션 생성이 성공함)**:
Google Cloud Console에서 프로젝트 생성(또는 기존 프로젝트 사용) → "Cloud
Text-to-Speech API" 활성화 → 그 API로 제한(restrict)한 API 키 발급.

## 구조

- `assets/characters/{female,male}/` — 캐릭터 레퍼런스 이미지 28장씩
- `assets/fonts/NotoSansKR-Regular.ttf` — v1 디자인에서 쓰던 가변폰트(현재 미사용, 참고용 보관)
- `assets/fonts/NotoSerifKR-VF.ttf` — v15 골드 포일 타이틀/카드/자막에 쓰는 세리프 가변폰트
- `assets/logo/channel_logo.png` — 쇼핑의천국 실제 로고
- `assets/sfx/` — pop.mp3(카드 등장), whoosh-short.mp3(컷 전환)
- `scripts/pick_product.py` — 쿠팡 API로 고가 전자제품 선정, 중복 방지(`used_products.json`)
- `scripts/gen_script.py` — Gemini로 훅/스펙/CTA 대본 + SEO 메타데이터 생성.
  나레이션은 스펙 1개당 문장 1개(`narration_script1/2/3`)로 분리되어 있어서
  컷 전환이 문장 경계와 정확히 맞음(2026-08-27, 기존엔 1개 통짜를 3등분했었음).
- `scripts/build_graphics.py` — PIL로 v15 골드 럭셔리 디자인 그래픽 생성 (2026-08-27 로컬 세션에서 확정된 디자인 이식)
- `scripts/heygen_gen.py` — HeyGen 아바타 훅/CTA 영상 생성
- `scripts/google_tts.py` — 스펙 설명 나레이션 생성 (Google Cloud TTS, 2026-08-27
  헤이젠 TTS에서 교체 — "AI같이 들린다"는 피드백 때문. 클라우드 샌드박스가 GPU가
  없어서 로컬 CosyVoice(zero-shot 보이스클로닝)를 그대로 옮길 수 없었던 게 이유.
  **트레이드오프**: 훅/CTA는 여전히 헤이젠 목소리라 나레이션과 완전히 같은 목소리는
  아님 — Google TTS는 사전정의된 보이스 선택이라 클로닝이 안 됨.
- `scripts/assemble_video.py` — ffmpeg 최종 조립
- `scripts/upload_youtube.py` — 공개 업로드 (채널 ID 검증 포함)
- `scripts/post_x.py` — X 포스트 (링크 없이, 프로필 바이오 링크 유도)
- `scripts/post_comment.py` — 영상 공개 확인 후 댓글 홍보 (재시도 포함)
- `scripts/update_link_page.py` — 부업실험실 링크 페이지에 상품 카드 추가
- `scripts/shorts_log.py` — 발행 이력 기록(`shorts_log.json`), 롱폼 컴파일 판단용
- `scripts/compile_longform.py` — 숏츠 6개(하루 2개 x 3일)가 쌓이면 유튜브에서
  yt-dlp로 다시 받아 이어붙여 롱폼으로 별도 업로드 (2026-08-27 추가)
- `scripts/run_pipeline.py` — 전체 오케스트레이터

## 알아둘 것

- HeyGen 훅+CTA 생성만 비용 발생(초당 $0.05), 나머지는 무료/저비용.
- 유튜브/X 포스트 실패는 파이프라인을 막지 않는 부가 스텝(`soft_step`)이고,
  상품 선정/대본생성/HeyGen/조립/유튜브업로드는 실패시 전체 중단.
- [[feedback-heygen-no-regenerate-without-confirm]] 원칙은 이 자동화에는 적용 안 됨
  (매번 새 상품 → 매번 새 생성이 정상, "재생성 낭비 금지"는 같은 영상 반복수정 얘기였음).
- 롱폼 컴파일은 로컬에 숏츠 mp4를 안 남겨두는 클라우드 실행 특성상 유튜브에
  이미 올라간 영상을 yt-dlp로 재다운로드해서 이어붙이는 방식이다. 하드컷으로만
  연결하는 1차 버전이라, 상품별 타이틀 카드나 전환 효과음을 넣는 건 다음 개선 여지.
