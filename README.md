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

**2026-09-01 추가 (인스타/틱톡)**:

- `IG_USER_ID`: shoppingparadise.kr의 Instagram 사용자 ID(`graph.instagram.com/me`
  기준, 2026-09-01 확인값 `28124947437116059`).
- `IG_ACCESS_TOKEN`: Meta 개발자 앱 "쇼핑의천국 인스타그램 자동글쓰기"(Instagram API
  with Instagram Login, App ID 1676158014013411, Instagram App ID 2137440940539520)
  에서 발급받은 `instagram_business_content_publish` 포함 장기(long-lived, 60일) 토큰.
  이건 **최초 부트스트랩 시드값일 뿐** — 실제로는 매 실행마다 `scripts/secrets_store.py`가
  비공개 저장소 `reintroka/shopping-paradise-secrets`의 `instagram_token.json`을
  읽고, 24시간 이상 지났으면 `graph.instagram.com/refresh_access_token`으로 자동
  갱신해서 다시 저장한다(사람이 60일마다 손으로 갱신할 필요 없음). 영상은
  `scripts/post_instagram.py`가 `reintroka/shopping-paradise-media`(GitHub Pages)에
  임시로 올려서 공개 URL로 넘긴다(Graph API가 로컬 파일 직접 업로드를 지원하지 않고
  video_url만 받으므로).
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`: TikTok
  개발자 앱 "쇼핑의천국 틱톡 자동발행"(App ID 7680193905014786066, Sandbox "main",
  target user `shoppingparadise_kr`)에서 발급받은 리프레시 토큰. 앱이 심사(audit)를
  통과하기 전이라 `video.publish`(바로 공개 발행) 권한은 못 쓰고, 대신 "Post to
  inbox" 방식으로 영상을 계정의 틱톡 앱 받은편지함에 초안으로 전달만 한다 — 계정
  소유자가 앱 알림에서 직접 "게시"를 눌러야 최종 발행됨. `TIKTOK_REFRESH_TOKEN`도
  마찬가지로 최초 시드값일 뿐 — 매 실행마다 회전(rotate)되는 새 리프레시 토큰을
  `secrets_store.py`가 같은 `shopping-paradise-secrets`의 `tiktok_token.json`에
  자동 반영한다.

**왜 별도 비공개 저장소가 필요한가**: 이 저장소(shopping-paradise-pipeline)는
public이라 토큰을 여기 커밋하면 그대로 노출된다. `shopping-paradise-secrets`는
private repo로 따로 만들어서 자동 갱신되는 토큰 상태만 보관한다(클라우드 환경의
git 자격증명이 같은 계정 소유의 private repo에도 push 권한이 있다는 전제 —
안 되면 `secrets_store.py`의 clone/push가 실패하고 soft_step 로그에 남는다).

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
- `scripts/post_instagram.py` — 인스타그램 Reels 발행 (GitHub Pages 임시 호스팅 경유,
  2026-09-01 추가)
- `scripts/post_tiktok.py` — 틱톡 받은편지함(초안) 전달 (앱 심사 전이라 자동 공개
  발행 불가, 2026-09-01 추가)
- `scripts/secrets_store.py` — 비공개 저장소(`shopping-paradise-secrets`)에서 자동
  갱신 토큰(인스타/틱톡)을 읽고 쓰는 공용 헬퍼 (2026-09-01 추가, public 저장소에
  시크릿을 커밋하지 않기 위함)
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
