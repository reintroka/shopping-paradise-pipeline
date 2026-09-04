"""상품 정보를 받아서 Gemini로 훅/스펙/CTA 대본 + 유튜브 SEO 메타데이터 + X 포스트를 한 번에 생성.

출력 JSON 예시:
{
  "hook_title_line1": "무게 하나로",
  "hook_title_line2": "후기 폭발 노트북",
  "hook_speech": "무게 하나로 후기 폭발한 노트북, 이유가 있더라고요.",
  "cta_speech": "이 정도면 안 살 이유가 없죠. 프로필 링크에서 확인하세요.",
  "spec1_title": "성능", "spec1_body": "인텔 i5 · 16GB RAM",
  "spec2_title": "저장공간", "spec2_body": "512GB SSD (256GB×2 듀얼)",
  "spec3_title": "화면 · 무게", "spec3_body": "15.6형 FHD IPS · 초경량",
  "narration_script1": "인텔 코어 아이파이브에... (숫자는 한글 발음으로 풀어쓸 것)",
  "narration_script2": "저장공간은 오백십이 기가...",
  "narration_script3": "화면은 큼직한 십오점육 인치인데...",
  "youtube_title": "...",
  "youtube_description_intro": "...",
  "x_post": "...",
  "ig_caption": "..."
}
"""
import argparse
import json
import os
import random
import urllib.request
from pathlib import Path

X_POST_HISTORY_PATH = Path(__file__).resolve().parent.parent / "x_post_history.json"
X_POST_HISTORY_MAX = 12

# 2026-08-31: 저사양 모델(gemini-flash-lite-latest)이 "CTA 문구를 매번 다르게
# 써라" 같은 느슨한 지침을 잘 안 따르고 거의 매번 "지금 프로필에서 바로 확인
# 가능해요" 류의 동일한 CTA를 반복해서(+ 고정된 해시태그 개수) X가 스팸/중복
# 콘텐츠로 판단, 게시 403을 낸 사례가 있었다. LLM의 자율적 다양성에 맡기지 않고
# 파이썬이 결정론적으로 CTA 문구/해시태그 개수를 뽑아 프롬프트에 강제 주입한다.
CTA_PHRASES = [
    "프로필 링크에서 바로 확인하세요.",
    "지금 프로필 클릭 한 번이면 끝!",
    "더 궁금하면 프로필 들러보세요~",
    "놓치지 마시고 프로필에서 확인하세요!",
    "자세한 내용은 프로필 링크를 참고해주세요.",
    "지금 프로필 가서 득템하세요.",
    "관심 있으면 프로필 확인 필수예요!",
    "프로필에 다 있어요, 구경 가보세요.",
]

PROMPT_TEMPLATE = """당신은 "쇼핑의천국" 유튜브 쇼츠 채널(쿠팡파트너스 제품 추천)의 카피라이터입니다.
아래 상품 정보를 보고 45초짜리 숏츠 대본을 JSON으로 만드세요.

[상품명]
{product_name}

[가격]
{price}

[카테고리 키워드]
{keyword}

[구조]
- 훅(8초): 화면에 큰 골드 라벨로 뜨는 2줄 짧은 문구(hook_title_line1/2, 각 6~10자) +
  아바타가 실제로 말하는 문장(hook_speech, 자연스러운 구어체 1~2문장)
- 스펙 설명(22초): 이 상품의 핵심 특징 3가지를 스펙카드용 제목(2~5자)+본문(15자 내외)으로.
  실제 상품명/카테고리에서 합리적으로 추론 가능한 특징만 쓰고 없는 스펙을 지어내지 마세요.
- CTA(6초): 아바타가 말하는 마무리 멘트(cta_speech, "프로필 링크"를 언급하며 구매 유도)
- narration_script1/2/3: 스펙1/2/3 각각을 설명하는 나레이션 한 문장씩(스펙카드 1개당
  하나, 각 8~20자 내외 짧은 구어체 — 카드가 바뀔 때마다 화면이 컷 전환되므로 문장도
  그 타이밍에 맞춰 각각 독립적으로 완결되어야 함. 3개를 이어 읽으면 자연스러운
  설명이 되도록). **이 세 필드만 숫자를 한글 발음으로 풀어쓸 것** (예: "15.6인치"→
  "십오점육 인치", "512GB"→"오백십이 기가", "i5"→"아이파이브") — TTS가 숫자를 잘못
  읽는 걸 방지하기 위함. 이 세 필드는 화면에 절대 글자로 표시되지 않고 음성으로만
  재생됨.
- **주의: narration_script1/2/3을 제외한 모든 필드(spec1~3_title/body, hook_title_line1/2,
  hook_speech, cta_speech, youtube_title, youtube_description_intro, x_post)는 화면에
  글자 그대로 표시되거나 HeyGen 아바타 TTS(숫자를 정상적으로 읽음)가 읽으므로, 숫자를
  절대 한글로 풀어쓰지 말고 원래 숫자+단위 표기를 그대로 쓸 것** (예: "12.1인치", "512GB",
  "i5" 그대로 — "십이점일인치" 같은 표기 금지).
- youtube_title: SEO 제목 60자 이내, 후킹있게
- youtube_description_intro: 설명란 맨 위에 들어갈 1~2문장 (링크/고지문은 별도로 붙임)
- x_post: X(트위터) 홍보 문구. 140~220자 분량으로 충분히 길게 써서 훅 문장 + 핵심 셀링포인트
  2~3개(가격/스펙 등 구체적으로) + 유도 문구(CTA) + 해시태그를 포함할 것 (X 게시글
  글자수 한도는 280자). 너무 짧고 밋밋한 한 줄짜리 문구 금지. 링크 URL 자체는 절대
  넣지 말 것(프로필 바이오 링크로 유도).
  **이번 CTA 문구는 절대 새로 짓지 말고, 아래 문구를 토씨 하나 바꾸지 말고 그대로
  x_post의 마지막 문장으로 포함시킬 것: "{cta_phrase}"**
  **해시태그는 정확히 {hashtag_count}개만 쓸 것 (더 많거나 적게 쓰지 말 것).**
  **X가 반복되는 문장 구조를 스팸/중복 콘텐츠로 판단해 게시를 거부하는 사례가 있었음
  (2026-08-28) — 아래 [최근 X 포스트]와 겹치지 않도록 반드시 다음을 매번 바꿀 것:**
  1) 첫 문장의 문형(예: 매번 "~하셨죠?"로 시작하는 질문형 반복 금지 — 감탄사로 시작,
     상황 묘사로 시작, 숫자/가격으로 시작 등 다양하게), 2) 해시태그 구성과 순서
     (#쇼핑의천국을 항상 맨 끝 고정 위치에 기계적으로 반복하지 말고, 상품 관련 태그와
     브랜드 태그의 조합 순서를 매번 바꿀 것).

[최근 X 포스트 (이 구조/표현과 겹치지 않게 새로 쓸 것, 없으면 빈 목록)]
{recent_x_posts}

- ig_caption: 인스타그램 릴스용 캡션. x_post와는 완전히 별도로, 인스타그램 사용자가 읽기 편하도록
  **반드시 문단 사이를 실제 줄바꿈 두 번(\\n\\n)으로 구분**해서 다음 순서로 작성할 것 —
  절대 줄바꿈 없이 한 문단으로 쭉 이어 쓰지 말 것:
  1) 훅 문장 1~2줄 (이모지 1개로 시작해도 좋음)
  2) 핵심 셀링포인트 2~3가지를 짧은 문장으로, 필요하면 이 부분도 문장마다 줄바꿈(\\n)
  3) CTA 한 문장 ("프로필 링크"를 언급하며 구매/확인 유도, 링크 URL 자체는 넣지 말 것)
  4) 빈 줄(\\n\\n) 하나 띄운 뒤, 마지막 줄에 해시태그 8~12개를 띄어쓰기로 나열한 블록
     (상품/카테고리 관련 태그 위주로 다양하게 구성하고, 맨 끝에 #쇼핑의천국 태그를 포함할 것)

[출력 형식 - JSON만 출력, 다른 텍스트 없이]
{{"hook_title_line1":"","hook_title_line2":"","hook_speech":"","cta_speech":"",
"spec1_title":"","spec1_body":"","spec2_title":"","spec2_body":"","spec3_title":"","spec3_body":"",
"narration_script1":"","narration_script2":"","narration_script3":"",
"youtube_title":"","youtube_description_intro":"","x_post":"","ig_caption":""}}
"""


def call_gemini(prompt: str) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    model = "gemini-flash-lite-latest"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["candidates"][0]["content"]["parts"][0]["text"]


def parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def load_x_post_history() -> list[str]:
    if X_POST_HISTORY_PATH.exists():
        return json.loads(X_POST_HISTORY_PATH.read_text(encoding="utf-8"))
    return []


def save_x_post_history(history: list[str], new_post: str) -> None:
    history = (history + [new_post])[-X_POST_HISTORY_MAX:]
    X_POST_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--product-json", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    product = json.loads(open(args.product_json, encoding="utf-8").read())
    history = load_x_post_history()
    recent_x_posts = "\n".join(f"- {h}" for h in history[-5:]) or "(없음)"
    cta_phrase = random.choice(CTA_PHRASES)
    hashtag_count = random.choice([1, 2, 3])
    prompt = PROMPT_TEMPLATE.format(
        product_name=product["productName"],
        price=f"{product['productPrice']:,}원",
        keyword=product.get("keyword", ""),
        recent_x_posts=recent_x_posts,
        cta_phrase=cta_phrase,
        hashtag_count=hashtag_count,
    )
    text = call_gemini(prompt)
    data = parse_json_response(text)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if data.get("x_post"):
        save_x_post_history(history, data["x_post"])
    print(f"대본 생성 완료: {args.out}")


if __name__ == "__main__":
    main()
