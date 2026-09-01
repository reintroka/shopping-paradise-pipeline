"""롱폼 다이제스트용 제품별 딥다이브 나레이션 — Gemini로 확장 코멘트 생성 + Google TTS
합성 + 강조단어 추출.

숏츠의 스펙 카드(짧은 태그라인 3개)와 달리, 롱폼에서는 각 제품마다 20~30초 분량의
좀 더 풀어서 설명하는 리뷰형 코멘트를 만든다. 다른 13개 채널의 "딥다이브 확장나레이션"
패턴과 같은 역할이지만, 이 채널은 상품 소개가 본질이라 배경설명이 아니라 리뷰
코멘트로 구성한다.
"""
import json
import os
import urllib.request
from pathlib import Path

import google_tts

PROMPT_TEMPLATE = """당신은 "쇼핑의천국" 유튜브 롱폼 다이제스트의 내레이터입니다.
아래 상품에 대해 20~30초 분량(공백 포함 110~160자)의 리뷰형 코멘트를 자연스러운
구어체로 한 문단 작성하세요. 왜 이 상품이 주목받는지, 실사용 팁이나 장점을 구체적으로
설명하되 과장/허위 광고성 표현은 피하고, 자연스럽게 소비자에게 도움이 되는 정보처럼
쓰세요.

이 코멘트는 음성 나레이션(TTS)으로 재생되는 동시에 화면 자막으로도 표시되므로,
**같은 내용을 숫자 표기만 다르게 한 두 가지 버전**으로 작성하세요:
- narration_spoken: TTS가 읽을 버전. 가격/용량 등 모든 숫자를 반드시 한글 발음으로
  풀어써야 합니다(예: "722,650원"→"칠십이만이천육백오십원", "16GB"→"십육 기가",
  "15.6인치"→"십오점육 인치"). 숫자를 원래 표기 그대로 두면 TTS가 잘못 읽습니다.
- narration_caption: 화면 자막에 표시될 버전. narration_spoken과 문장 구조/내용은
  완전히 동일하되, 숫자만 원래 표기(가격 콤마, GB, 인치 등)로 돌려쓰세요 — 화면에서는
  풀어쓴 한글 숫자가 오히려 어색하고 길어 보입니다.

이 코멘트에서 시청자가 화면 자막으로 볼 때 강조되면 좋을 핵심 단어/짧은 구 3~5개도
따로 뽑아주세요(narration_caption 본문에 실제로 등장하는 표현 그대로, 토씨 하나
다르지 않게).

[상품명] {product_name}
[가격] {price}
[핵심 스펙] {specs_text}

[출력 형식 - JSON만 출력, 다른 텍스트 없이]
{{"narration_spoken": "...", "narration_caption": "...", "emphasis_words": ["...", "..."]}}
"""


def _call_gemini(prompt: str) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    model = "gemini-flash-lite-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["candidates"][0]["content"]["parts"][0]["text"]


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def generate_and_synthesize(product_name: str, price: int, specs: list[tuple] | None,
                             character: str, work_dir: Path, idx: int) -> dict:
    """Gemini로 딥다이브 코멘트+강조단어 생성 후 Google TTS로 합성.

    specs가 없으면(2026-09-01 이전 발행분, shorts_log.json에 스펙이 저장되기 전)
    상품명/가격만으로 생성한다 — 구체성은 떨어지지만 파이프라인이 막히지는 않는다.
    """
    specs_text = "; ".join(f"{t}: {v}" for t, v in specs) if specs else "(정보 없음, 상품명/가격 기준으로 일반적인 장점 위주로 작성)"
    prompt = PROMPT_TEMPLATE.format(
        product_name=product_name, price=f"{price:,}원", specs_text=specs_text,
    )
    text = _call_gemini(prompt)
    data = _parse_json(text)
    narration_spoken = data["narration_spoken"]
    narration_caption = data["narration_caption"]
    emphasis_words = data.get("emphasis_words", [])

    audio_path = work_dir / f"deepdive_narration_{idx}.mp3"
    meta = google_tts.synthesize(narration_spoken, character, audio_path)
    return {
        "narration": narration_caption,
        "emphasis_words": emphasis_words,
        "audio_path": audio_path,
        "duration": meta["duration"],
    }
