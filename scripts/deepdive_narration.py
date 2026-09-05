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
import korean_number

PRICE_TOKEN = "[[PRICE]]"

PROMPT_TEMPLATE = """당신은 "쇼핑의천국" 유튜브 롱폼 다이제스트의 내레이터입니다.
아래 상품에 대해 20~30초 분량(공백 포함 110~160자)의 리뷰형 코멘트를 자연스러운
구어체로 한 문단 작성하세요. 왜 이 상품이 주목받는지, 실사용 팁이나 장점을 구체적으로
설명하되 과장/허위 광고성 표현은 피하고, 자연스럽게 소비자에게 도움이 되는 정보처럼
쓰세요.

**가격은 이 코멘트 전체에서 정확히 한 번만 언급하세요** — 강조하고 싶어도 두 번
이상 반복하지 마세요(예: "이 가격에", "가격 대비" 같은 표현으로 가격을 다시
암시하는 건 괜찮지만, 실제 가격 숫자/자리표시자를 두 번 넣으면 안 됩니다).

이 코멘트는 음성 나레이션(TTS)으로 재생되는 동시에 화면 자막으로도 표시되므로,
**같은 내용을 숫자 표기만 다르게 한 두 가지 버전**으로 작성하세요:
- narration_spoken: TTS가 읽을 버전. 용량/인치 등 숫자는 한글 발음으로 풀어써야
  합니다(예: "16GB"→"십육 기가", "15.6인치"→"십오점육 인치"). 단, **가격만은 절대
  직접 숫자를 계산해서 풀어쓰지 말고, 가격이 들어갈 자리에 토씨 하나 바꾸지 말고
  literal 문자열 "{price_token}" 를 그대로 넣으세요** (예: "이 가격에 {price_token}이면
  괜찮은 구성이에요"). 큰 자릿수 가격을 직접 한글로 옮기면 자릿수를 실수하기 쉬워서
  이 부분만 코드가 별도로 정확하게 계산해 넣습니다.
- narration_caption: 화면 자막에 표시될 버전. narration_spoken과 문장 구조/내용은
  완전히 동일하되, 가격 자리에는 "{price_token}"이 아니라 원래 숫자 표기({price})를
  쓰고, 그 외 숫자(GB, 인치 등)도 원래 표기로 돌려쓰세요 — 화면에서는 풀어쓴 한글
  숫자가 오히려 어색하고 길어 보입니다.

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
    price_digits = f"{price:,}원"
    prompt = PROMPT_TEMPLATE.format(
        product_name=product_name, price=price_digits, specs_text=specs_text, price_token=PRICE_TOKEN,
    )
    narration_spoken = narration_caption = ""
    emphasis_words: list = []
    for attempt in range(3):
        text = _call_gemini(prompt)
        data = _parse_json(text)
        narration_spoken = data["narration_spoken"]
        narration_caption = data["narration_caption"]
        emphasis_words = data.get("emphasis_words", [])
        token_count = narration_spoken.count(PRICE_TOKEN)
        if token_count == 1:
            break
        print(f"  [경고] 가격 자리표시자가 {token_count}번 등장(정확히 1번이어야 함) — "
              f"재시도 {attempt + 1}/3: {narration_spoken[:80]!r}")
    else:
        # 2026-09-05: 3회 재시도에도 가격이 중복 언급되는 경우, 두 번째부터는 그냥
        # 지워서 최소한 "가격을 두 번 말하는" 사고만은 막는다(사용자가 실제 발행본
        # 43초 지점에서 가격이 두 번 나온 걸 지적해서 발견 — 재시도로도 못 고치면
        # 완전 차단하는 게 낫다는 판단, 문장이 약간 어색해질 수는 있음).
        first, *rest = narration_spoken.split(PRICE_TOKEN, 1) or [narration_spoken]
        if rest:
            narration_spoken = first + PRICE_TOKEN + rest[0].replace(PRICE_TOKEN, "")
        print(f"  [경고] 3회 재시도 후에도 가격이 중복 언급됨 — 두 번째 이후는 강제로 제거: "
              f"{narration_spoken[:80]!r}")

    # 2026-09-02: 가격을 LLM이 직접 한글로 계산해 풀어쓰다가 200만원대를 20만원대로
    # 잘못 발음하는 사고 발생(노트북 상품) — 가격 변환은 여기서 코드로 결정적으로
    # 채워 넣고, LLM에게는 자리표시자만 남기도록 프롬프트를 바꿨다.
    if PRICE_TOKEN not in narration_spoken:
        print(f"  [경고] narration_spoken에 {PRICE_TOKEN} 자리표시자가 없습니다 — "
              f"모델이 지침을 어기고 가격을 직접 풀어썼을 수 있습니다: {narration_spoken[:80]!r}")
    narration_spoken = narration_spoken.replace(PRICE_TOKEN, korean_number.price_to_korean(price))
    # narration_caption도 같은 이유로 가격 표기(숫자, "{price_digits}"로 이미 대체된
    # 형태)가 두 번 이상이면 두 번째부터 제거 — narration_spoken과 별개로 생성되므로
    # 독립적으로 확인해야 한다.
    if narration_caption.count(PRICE_TOKEN) > 1:
        first, *rest = narration_caption.split(PRICE_TOKEN, 1)
        narration_caption = first + PRICE_TOKEN + rest[0].replace(PRICE_TOKEN, "") if rest else narration_caption
    narration_caption = narration_caption.replace(PRICE_TOKEN, price_digits)

    audio_path = work_dir / f"deepdive_narration_{idx}.mp3"
    meta = google_tts.synthesize(narration_spoken, character, audio_path)
    return {
        "narration": narration_caption,
        "emphasis_words": emphasis_words,
        "audio_path": audio_path,
        "duration": meta["duration"],
    }
