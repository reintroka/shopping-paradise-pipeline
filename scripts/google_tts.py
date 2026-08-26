"""Google Cloud Text-to-Speech로 스펙 설명 구간 나레이션 생성 (2026-08-27 도입).

기존엔 heygen_gen.py의 tts_speech()가 헤이젠 TTS로 만들었으나 "AI같이 들린다"는
피드백으로 교체. 클라우드 샌드박스가 CPU-only라 로컬 CosyVoice(D:\\tts_test, GPU
전제)를 그대로 옮길 수 없어서 내린 결정 — project memory
`project_shoppingparadise_youtube.md` 2026-08-27 항목 참고.

**알려진 트레이드오프**: 훅/CTA는 여전히 헤이젠 아바타 목소리(voice_id 고정)이고,
이 나레이션만 구글 스톡 보이스로 바뀌므로 두 목소리가 정확히 같지는 않다
(제로샷 클로닝이 아니라 사전정의된 보이스 선택이라 완전한 통일은 불가능).

필요한 환경변수: GOOGLE_TTS_API_KEY
  (Google Cloud Console에서 프로젝트 생성 → "Cloud Text-to-Speech API" 활성화 →
   그 API로 제한된 API 키 발급 → shopping-paradise-automation 클라우드 환경의
   시크릿에 등록)
"""
import base64
import json
import os
import subprocess
from pathlib import Path
from urllib import request as urlreq

API_KEY_ENV = "GOOGLE_TTS_API_KEY"
ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"

# 캐릭터별 보이스 — 훅/CTA(헤이젠) 성별에 맞춰서만 고른 것이고 완전히 같은
# 목소리는 아님(위 트레이드오프 참고). Chirp3-HD가 더 자연스러우면 이 값만
# 바꾸면 됨(다른 코드 수정 불필요).
VOICE_NAMES = {
    "female": "ko-KR-Neural2-A",
    "male": "ko-KR-Neural2-C",
}


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def synthesize(text: str, character: str, out_path: Path) -> dict:
    api_key = os.environ[API_KEY_ENV]
    voice_name = VOICE_NAMES[character]
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "ko-KR", "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0},
    }
    req = urlreq.Request(
        f"{ENDPOINT}?key={api_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlreq.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    audio_bytes = base64.b64decode(result["audioContent"])
    out_path.write_bytes(audio_bytes)

    duration = _ffprobe_duration(out_path)
    meta = {"duration": duration, "voice_name": voice_name, "engine": "google-tts"}
    out_path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    p.add_argument("--character", choices=["female", "male"], required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    meta = synthesize(args.text, args.character, Path(args.out))
    print(f"나레이션 생성 완료: {args.out} ({meta['duration']:.2f}초, 보이스: {meta['voice_name']})")
