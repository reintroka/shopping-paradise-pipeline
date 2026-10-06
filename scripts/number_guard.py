"""대본 속 '숫자+단위'가 상품 정보에 실제로 있는 숫자인지 검사한다(2026-10-06).

배경: Gemini가 나레이션을 쓰면서 숫자를 지어내거나 잘못 옮긴 사례가 실제 발행본에서 확인됨.
  - 스카이락 밀폐용기(1dzbHFuH0jE): 상품은 240ml~980ml인데 "46ml부터 980ml까지"라고 말함(460→46)
  - 빌리빈 조리도구(7ryA3cJglk8): 근거 없는 "15종이 아닌 8종"
가격은 이미 자리표시자로 코드가 채우므로, 여기서는 용량·개수·크기 같은 '숫자+단위'만 본다.
나레이션은 한글로 풀어 쓰므로("사십육 밀리리터", "십오 종") 한글 수사도 숫자로 되돌려 비교한다.
"""
import re

_SINO_DIGIT = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_SINO_UNIT = {"십": 10, "백": 100, "천": 1000}
_NATIVE = {"한": 1, "하나": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
           "열한": 11, "열두": 12, "열세": 13, "열네": 14, "열다섯": 15, "열여섯": 16, "스무": 20}

# 한 글자 단위(종·단·구·매·장)는 일반 낱말("구성", "장점", "단계", "종류")과 헷갈리므로
# 뒤에 조사/공백/끝이 올 때만 단위로 본다.
_TAIL = r"(?=$|[^가-힣]|세트|구성|짜리|으로|까지|부터|이|을|를|은|는|의|에|도|과|와|로|만|이나|나)"
_SPOKEN_UNITS = (r"(?:밀리리터|미리리터|리터|피스|인용|인치|센티미터|센티|밀리미터|미리|킬로그램|킬로|키로|그램|기가|테라|와트|퍼센트|"
                 r"개입|(?:종|단|구|매|장)" + _TAIL + ")")
_SINO_RE = re.compile(r"(?<![가-힣])([일이삼사오육칠팔구십백천만]+(?:점[영공일이삼사오육칠팔구]+)?)\s?" + _SPOKEN_UNITS)
_NATIVE_RE = re.compile(r"(?<![가-힣])(" + "|".join(sorted(_NATIVE, key=len, reverse=True)) + r")\s?(?:피스|(?:종|장|매)" + _TAIL + ")")
_DIGIT_UNITS = r"(?:ml|mL|ML|L|l|리터|종|피스|P|p|개입|개|인용|인치|cm|mm|kg|g|GB|TB|W|단|구|매|장|%|mAh|bar|입|팩|롤|매입)"
_DIGIT_RE = re.compile(r"(?<![\d.,])(\d+(?:\.\d+)?)\s?" + _DIGIT_UNITS + r"(?![a-zA-Z])")
_ANY_NUM = re.compile(r"\d+(?:\.\d+)?")


def _sino_int(s: str) -> int | None:
    total, cur = 0, 0
    for ch in s:
        if ch in _SINO_DIGIT:
            cur = cur * 10 + _SINO_DIGIT[ch] if cur and ch not in _SINO_UNIT else _SINO_DIGIT[ch]
        elif ch in _SINO_UNIT:
            total += (cur or 1) * _SINO_UNIT[ch]
            cur = 0
        else:
            return None
    return total + cur


def sino_to_number(s: str) -> float | None:
    """'사십육'→46, '구백팔십'→980, '이만'→20000, '십오점육'→15.6. 숫자가 아니면 None."""
    whole, _, frac = s.partition("점")
    if "만" in whole:
        hi, _, lo = whole.partition("만")
        h = _sino_int(hi) if hi else 1
        l_ = _sino_int(lo) if lo else 0
        if h is None or l_ is None:
            return None
        n = h * 10000 + l_
    else:
        n = _sino_int(whole)
        if n is None:
            return None
    if frac:
        return float(f"{n}." + "".join(str(_SINO_DIGIT[c]) for c in frac))
    return float(n)


def spoken_numbers(text: str) -> list[tuple[float, str]]:
    """대본에서 '숫자+단위'를 찾아 (값, 원문 조각) 목록으로 돌려준다(아라비아·한자어·고유어 모두)."""
    out = []
    for m in _DIGIT_RE.finditer(text or ""):
        out.append((float(m.group(1)), m.group(0)))
    for m in _SINO_RE.finditer(text or ""):
        frag = m.group(0)
        # '구매', '이장'처럼 한 글자 수사+한 글자 단위가 붙어 있으면 일반 낱말일 가능성이 커서 건너뛴다
        if len(m.group(1)) == 1 and " " not in frag and len(frag) == 2:
            continue
        v = sino_to_number(m.group(1))
        if v is not None:
            out.append((v, m.group(0)))
    for m in _NATIVE_RE.finditer(text or ""):
        out.append((float(_NATIVE[m.group(1)]), m.group(0)))
    return out


def allowed_numbers(*sources: str) -> set[float]:
    """상품명·스펙 등에 실제로 등장하는 숫자들. 1은 '한 개'처럼 늘 자연스러워 허용."""
    vals = {1.0}
    for s in sources:
        for m in _ANY_NUM.finditer((s or "").replace(",", "")):
            vals.add(float(m.group(0)))
    return vals


def unknown_numbers(fields: dict, *sources: str) -> list[str]:
    """fields({이름: 대본}) 중 sources에 없는 숫자를 말한 조각들. 비어 있으면 통과."""
    ok = allowed_numbers(*sources)
    bad = []
    for name, text in fields.items():
        for v, frag in spoken_numbers(text if isinstance(text, str) else ""):
            if v not in ok:
                bad.append(f"{name}: '{frag.strip()}'")
    return bad


def retry_note(bad: list[str]) -> str:
    return ("\n\n[재작성 요청] 직전 답변에 상품 정보에 없는 숫자가 들어 있었습니다: " + ", ".join(bad)
            + "\n상품명·스펙에 실제로 적힌 숫자(용량·개수·크기 등)만 쓰고, 근거 없는 숫자나 비교(예: 'N종이 아닌')는"
              " 빼고 처음부터 다시 작성하세요. 출력 형식은 그대로 JSON만.")
