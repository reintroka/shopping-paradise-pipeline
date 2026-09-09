"""정수를 한글 발음(한자어 숫자)으로 결정적으로 변환한다.

2026-09-02: 롱폼 딥다이브 나레이션(deepdive_narration.py)이 가격을 한글로 풀어쓰는
작업을 전부 Gemini에게 맡겼는데, 노트북처럼 자릿수가 큰 가격(200만원대)에서 자릿수를
하나 통째로 빼먹고 "20만원대"로 잘못 발음하는 사고가 실제로 발생했다. LLM에게 자유
텍스트로 숫자 변환(사실상 산술 문제)을 맡기면 언제든 재발할 수 있으므로, 코드로
결정적으로 계산해 LLM은 "가격이 들어갈 자리"만 표시하도록 분리한다.
"""

_DIGITS = "일이삼사오육칠팔구"
_SMALL_UNITS = ["", "십", "백", "천"]
_BIG_UNITS = ["", "만", "억", "조"]


def _four_digit_to_korean(n: int) -> str:
    """0~9999를 한글로 변환한다 (십/백/천 앞의 "일"은 관례대로 생략)."""
    if n == 0:
        return ""
    digits = [int(d) for d in str(n).zfill(4)]
    parts = []
    for i, d in enumerate(digits):
        if d == 0:
            continue
        unit = _SMALL_UNITS[3 - i]
        parts.append(unit if (d == 1 and unit) else f"{_DIGITS[d - 1]}{unit}")
    return "".join(parts)


def number_to_korean(n: int) -> str:
    """0 이상의 정수를 한글 발음 문자열로 변환한다 (예: 722650 -> "칠십이만이천육백오십")."""
    if n < 0:
        return f"마이너스{number_to_korean(-n)}"
    if n == 0:
        return "영"

    groups = []
    temp = n
    while temp > 0:
        groups.append(temp % 10000)
        temp //= 10000

    parts = []
    for i in reversed(range(len(groups))):
        group = groups[i]
        if group == 0:
            continue
        chunk = _four_digit_to_korean(group)
        big_unit = _BIG_UNITS[i]
        # 만/억/조 앞의 "일"도 관례상 생략한다 (10000 -> "만원", "일만원" 아님).
        if chunk == "일" and big_unit:
            chunk = ""
        parts.append(chunk + big_unit)
    return "".join(parts)


def price_to_korean(price: int) -> str:
    """가격(원)을 TTS가 자연스럽게 읽을 한글 문자열로 변환한다 (예: 722650 -> "칠십이만이천육백오십원")."""
    return f"{number_to_korean(int(price))}원"


def strip_duplicate_won(text: str, price_string: str) -> str:
    """가격 플레이스홀더 자리에 price_string(항상 "원"으로 끝남)을 채워 넣었는데,
    LLM이 그 자리 바로 뒤에 "원"을 관성적으로 또 붙여 쓴 경우("...원원") 중복분을
    제거한다 (2026-09-09, 쇼핑의천국 릴스 실제 발행분에서 "원원" 확인됨 — 프롬프트가
    플레이스홀더 삽입만 지시하고 "이미 원이 포함돼 있으니 뒤에 원을 더 붙이지
    말라"는 점을 명시하지 않아 발생)."""
    if price_string.endswith("원"):
        return text.replace(price_string + "원", price_string)
    return text
