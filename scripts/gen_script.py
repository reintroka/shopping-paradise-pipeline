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
  "narration_script": "인텔 코어 아이파이브에... (숫자는 반드시 한글 발음으로 풀어쓸 것)",
  "youtube_title": "...",
  "youtube_description_intro": "...",
  "x_post": "..."
}
"""
import argparse
import json
import os
import urllib.request

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
- narration_script: 스펙 설명 구간에서 나레이션으로 읽을 전체 문장(3개 스펙을 자연스럽게
  연결). **숫자는 반드시 한글 발음으로 풀어쓸 것** (예: "15.6인치"→"십오점육 인치",
  "512GB"→"오백십이 기가", "i5"→"아이파이브") — TTS가 숫자를 잘못 읽는 걸 방지하기 위함.
- youtube_title: SEO 제목 60자 이내, 후킹있게
- youtube_description_intro: 설명란 맨 위에 들어갈 1~2문장 (링크/고지문은 별도로 붙임)
- x_post: X(트위터) 홍보 문구, 60자 내외, 링크는 넣지 말 것(프로필 바이오 링크로 유도)

[출력 형식 - JSON만 출력, 다른 텍스트 없이]
{{"hook_title_line1":"","hook_title_line2":"","hook_speech":"","cta_speech":"",
"spec1_title":"","spec1_body":"","spec2_title":"","spec2_body":"","spec3_title":"","spec3_body":"",
"narration_script":"","youtube_title":"","youtube_description_intro":"","x_post":""}}
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--product-json", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    product = json.loads(open(args.product_json, encoding="utf-8").read())
    prompt = PROMPT_TEMPLATE.format(
        product_name=product["productName"],
        price=f"{product['productPrice']:,}원",
        keyword=product.get("keyword", ""),
    )
    text = call_gemini(prompt)
    data = parse_json_response(text)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"대본 생성 완료: {args.out}")


if __name__ == "__main__":
    main()
