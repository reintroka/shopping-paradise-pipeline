"""쇼핑의천국 새 롱폼: '같은 종류 상품 6개 가격대별 비교' (2026-10-06 사용자 확정, 기존 6편 모음 롱폼 대체).

구성(약 9~10분, 가로 1920x1080): 인트로+목차 → 고르는 기준 3~5개 → 상품 6개(특징·이런 분께·체크)
→ 한눈에 비교표 → 상황별 추천 → 오래 쓰는 관리법 → 마무리(가격 안내·쿠팡 파트너스 고지).
썸네일은 B안 'A vs B'(사용자 선택). 배경은 Pexels 사용 장면(키가 없으면 상품 사진 배경으로 대체).

CCR 루틴(shopping-paradise-longform, 매일 1회 — 마지막 발행 후 3일이 안 지났으면 바로 SKIP)이 실행:
  1. python3 scripts/longform_v2.py prepare           → 주제 선정 + 쿠팡 검색으로 상품 6개 + 작성 규칙(brief)
  2. 에이전트(Claude)가 원고 JSON 작성 → python3 scripts/longform_v2.py check --json-file F  (OK 나올 때까지 수정)
  3. python3 scripts/longform_v2.py build --json-file F  → TTS·렌더·썸네일·업로드·댓글·상태 커밋
원고 사실 근거: 쿠팡 검색 결과(상품명·가격)뿐 — 상품 설명은 상품명에 적힌 정보만, 숫자는 number_guard로 검사.
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lf2_graphics as G  # noqa: E402
import lf2_speech as S  # noqa: E402
import number_guard  # noqa: E402

REPO_ROOT = HERE.parent
WORK = REPO_ROOT / "work" / "lf2"
STATE_PATH = REPO_ROOT / "longform_v2_state.json"
KST = timezone(timedelta(hours=9))
EVERY_DAYS = 3
N_PRODUCTS = 6
TARGET_CHARS = 3900  # 2026-10-06 시안 실측 6.6자/초(호흡 포함) → 약 10분
LEN_LO, LEN_HI = 0.9, 1.15
MAX_LINE = 68  # 두 줄 자막 한도
DISCLOSURE = "이 영상은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
UA = {"User-Agent": "Mozilla/5.0"}
LINK_PAGE = "https://reintroka.github.io/sidejoblab-links/"

# (주제, 쿠팡 검색어들, 최저가) — 같은 종류를 가격대별로 비교하기 좋은 생활 카테고리 위주.
TOPICS = [
    ("밀폐용기", ["밀폐용기세트", "유리밀폐용기", "반찬통세트"], 5000),
    ("냄비·프라이팬 세트", ["프라이팬세트", "냄비세트", "인덕션냄비세트"], 10000),
    ("텀블러", ["텀블러", "보온보냉텀블러", "대용량텀블러"], 5000),
    ("도마", ["도마세트", "항균도마", "스텐도마"], 5000),
    ("식기건조대", ["식기건조대", "스텐식기건조대", "2단식기건조대"], 10000),
    ("조리도구 세트", ["조리도구세트", "실리콘조리도구", "스텐조리도구"], 5000),
    ("주방 수납정리", ["주방수납정리함", "냉장고정리용기", "양념통정리"], 5000),
    ("전기포트", ["전기포트", "무선전기포트", "스텐전기포트"], 15000),
    ("에어프라이어", ["에어프라이어", "오븐형에어프라이어", "대용량에어프라이어"], 40000),
    ("무선청소기", ["무선청소기", "가성비무선청소기", "물걸레무선청소기"], 50000),
    ("욕실 청소용품", ["욕실청소솔", "화장실청소도구세트", "욕실청소세트"], 5000),
    ("수납 선반", ["다용도선반", "주방선반", "철제선반"], 10000),
    ("캠핑의자", ["캠핑의자", "접이식캠핑의자", "릴렉스캠핑의자"], 15000),
    ("캠핑 테이블", ["캠핑테이블", "접이식캠핑테이블", "알루미늄캠핑테이블"], 15000),
    ("샴푸 세트", ["샴푸세트", "탈모샴푸세트", "헤어케어세트"], 10000),
    ("스킨케어 세트", ["스킨케어세트", "기초화장품세트", "남성스킨케어세트"], 15000),
    ("보조배터리", ["보조배터리", "고속충전보조배터리", "대용량보조배터리"], 10000),
    ("무선이어폰", ["무선이어폰", "노이즈캔슬링이어폰", "가성비무선이어폰"], 20000),
    ("가습기", ["가습기", "초음파가습기", "가열식가습기"], 20000),
    ("전기요", ["전기요", "탄소매트", "온수매트"], 30000),
    ("수건", ["호텔수건", "수건세트", "극세사수건"], 8000),
    ("베개", ["경추베개", "메모리폼베개", "호텔베개"], 10000),
]
RECENT_TOPICS = 8


def now_kst():
    return datetime.now(KST)


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"history": []}


def save_state(st):
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def notify(msg):
    try:
        import notify_telegram
        notify_telegram.send(msg)
    except Exception as e:  # noqa: BLE001
        print(f"[lf2] 텔레그램 알림 실패: {e}")


# ------------------------------------------------------------ 1. prepare
def _signature(name):
    return " ".join(name.split()[:2])


def _pick_spread(items, n):
    """가격순으로 줄 세워 저가~고가 고르게 n개."""
    items = sorted(items, key=lambda x: x["productPrice"])
    if len(items) <= n:
        return items
    idx = sorted({round(i * (len(items) - 1) / (n - 1)) for i in range(n)})
    k = 0
    while len(idx) < n:  # 반올림 중복 보충
        if k not in idx:
            idx.append(k)
        k += 1
    return [items[i] for i in sorted(idx)]


def source_products(topic, queries, min_price):
    import pick_product as PP
    seen_ids, seen_sig, cands = set(), set(), []
    for q in queries:
        try:
            res = PP.search(q, limit=10)
        except Exception as e:  # noqa: BLE001
            print(f"[lf2] 검색 실패({q}): {e}")
            continue
        for it in res.get("data", {}).get("productData", []):
            sig = _signature(it["productName"])
            if (it.get("isRocket") is True and it["productPrice"] >= min_price
                    and it["productId"] not in seen_ids and sig not in seen_sig):
                seen_ids.add(it["productId"])
                seen_sig.add(sig)
                cands.append(it)
        time.sleep(1.0)
    if len(cands) < N_PRODUCTS:
        return None
    chosen = _pick_spread(cands, N_PRODUCTS)
    out = []
    for i, it in enumerate(chosen):
        try:
            url = PP.shorten_link(it["productId"], it["productUrl"])
        except Exception as e:  # noqa: BLE001
            print(f"[lf2] 딥링크 변환 실패, 원본 URL 사용: {e}")
            url = it["productUrl"]
        out.append({"i": i, "name": it["productName"], "price": int(it["productPrice"]), "image": it["productImage"],
                    "url": url, "productId": it["productId"]})
    return out


def _download(url, out):
    for _ in range(3):
        try:
            out.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())
            Image.open(out).convert("RGB").save(out.with_suffix(".jpg"), quality=95)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[lf2] 이미지 다운로드 재시도: {e}")
            time.sleep(2)
    return False


def cmd_prepare(force=False):
    st = load_state()
    today = now_kst().date()
    last = max((h["date"] for h in st["history"]), default=None)
    if last and not force and (today - datetime.fromisoformat(last).date()).days < EVERY_DAYS:
        print(f"SKIP: 마지막 새 롱폼 {last} — {EVERY_DAYS}일이 안 지났습니다. 오늘은 할 일 없음.")
        return
    WORK.mkdir(parents=True, exist_ok=True)
    prep_path = WORK / "prepared.json"
    if prep_path.exists():
        prep = json.loads(prep_path.read_text(encoding="utf-8"))
        if prep.get("date") == today.isoformat():
            print(brief(prep))
            return
    recent = [h["topic"] for h in st["history"][-RECENT_TOPICS:]]
    order = [t for t in TOPICS if t[0] not in recent]
    random.shuffle(order)
    prep = None
    for topic, queries, min_price in order:
        prods = source_products(topic, queries, min_price)
        if prods:
            prep = {"date": today.isoformat(), "topic": topic, "products": prods}
            break
        print(f"[lf2] '{topic}' 후보 부족 — 다음 주제")
    if not prep:
        raise RuntimeError("모든 주제에서 로켓배송 후보 6개를 못 모았습니다")
    for p in prep["products"]:
        if not _download(p["image"], WORK / f"p{p['i']}.img"):
            raise RuntimeError(f"상품 사진 다운로드 실패: {p['name']}")
    prep_path.write_text(json.dumps(prep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(brief(prep))


RULES = """[새 롱폼 원고 규칙 — 쇼핑의천국 '같은 종류 6개 가격대별 비교']
아래 JSON을 파일로 쓰고 `python3 scripts/longform_v2.py check --json-file <경로>`가 OK를 낼 때까지 고친다.
그다음 `python3 scripts/longform_v2.py build --json-file <경로>` (렌더+업로드, 20~40분 — 같은 턴 안에서 끝까지 기다릴 것).

{
 "title": "유튜브 제목 60자 이내 — '{topic} 추천'·'비교' 같은 검색어 포함, 연도 넣지 말 것",
 "description_intro": "설명란 첫 2~3문장",
 "header": "화면 위 머리말 22자 이내(예: '냄비·프라이팬 세트 가격대별 추천')",
 "intro": {"kicker": "18자", "title": "14자(예: '냄비·프라이팬 세트 6종')", "sub": "28자", "toc": ["목차 4개, 각 14자"],
           "lines": ["문장 3~5개 — 공감 질문으로 시작(인사 금지), 마지막 문장은 오늘 순서 안내"], "broll": ["영어 Pexels 검색어 1~3개"]},
 "guides": [ {"kick": "16자(예: '고르는 기준 1 · 소재')", "title": "14자", "points": [{"at": 문장번호, "text": "22자"}, ...2~4개],
              "lines": ["문장 3~6개"], "broll": ["영어 검색어"]}, ...3~5개 ],
 "products": [ {"pick": 0~5(아래 상품 번호, 6개 모두 한 번씩), "short": "12자 화면용 짧은 이름", "tag": "8자 특징 꼬리표",
                "bullets": ["특징 3개, 각 20자"], "whom": "이런 분께 16자", "who2": "비교표용 10자", "check": "체크 포인트 24자",
                "lines": ["문장 4~7개 — {가격} 자리표시자를 정확히 1번"], "broll": ["영어 검색어"]}, ... 6개(가격 오름차순 권장) ],
 "compare": {"title": "20자(예: '밀폐용기 6종 한눈에 비교')", "lines": ["문장 3~5개"]},
 "situations": {"title": "16자", "cards": [{"head": "10자", "body": ["18자", "18자"]}, ...정확히 4개],
                "lines": ["문장 5개 — 첫 문장은 도입, 2~5번째가 카드 1~4"], "broll": ["영어 검색어"]},
 "care": {"title": "16자", "items": ["관리 요령 정확히 5개, 각 20자"], "lines": ["문장 6개 — 첫 문장 도입, 2~6번째가 요령 1~5"], "broll": ["영어 검색어"]},
 "outro_question": "댓글 유도 한 문장(?로 끝, 예: '여러분은 유리파이신가요, 플라스틱파이신가요?')",
 "thumbnail": {"left_label": "7자", "right_label": "7자", "left_pick": 상품번호, "right_pick": 상품번호,
               "left_broll": "영어 검색어", "right_broll": "영어 검색어", "question": "16자, ?로 끝", "chips": ["#해시태그 3개, 각 10자"]}
}
마무리(설명란·고정 댓글 안내, 가격 변동 안내, 쿠팡 파트너스 고지)는 코드가 자동으로 붙인다.

[문장 규칙]
- 문장 하나가 한 줄, 68자 이내, 반드시 . ? ! 로 끝. 같은 어미 반복 금지. 친근한 존댓말 리뷰 톤, 과장 금지.
- 숫자는 아라비아 숫자로 쓴다(240ml, 2종, 26cm, 3개). 읽기는 코드가 자동으로 바꾼다. 한글 수사로 풀어 쓰지 말 것.
- 가격은 절대 직접 쓰지 말고 상품 구간에서만 {가격} 자리표시자를 쓴다(예: '가격은 {가격}대로, ...'). 다른 구간에서 가격·합계 금액 언급 금지.
- 상품 설명은 아래 상품명에 실제로 적힌 정보(브랜드·용량·구성·소재·색상)만 근거로. 상품명에 없는 숫자·기능·인증·후기·판매량 날조 금지
  (코드가 상품명에 없는 '숫자+단위'를 찾아 반려한다). 확실하지 않으면 '상품 설명에 따르면' 대신 그냥 빼라.
- 고르는 기준·상황별 추천·관리법은 이 카테고리의 일반적인 정보로 채운다(특정 제품 주장 아님). 확실한 상식만.
- 체크 포인트는 솔직한 아쉬운 점/확인할 점(예: '인덕션 사용 가능 여부 확인')으로 신뢰를 준다.
- broll 검색어는 사람 얼굴보다 손·제품·장면 위주(예: "glass food container fridge", "frying pan omelette").
- 분량: 모든 lines 합계 약 {target}자(허용 {lo}~{hi}자).
"""


def brief(prep):
    t = TARGET_CHARS
    head = RULES.replace("{topic}", prep["topic"]).replace("{target}", str(t)).replace("{lo}", str(int(t * LEN_LO))).replace("{hi}", str(int(t * LEN_HI)))
    rows = "\n".join(f"  {p['i']}. {p['name']} — {p['price']:,}원" for p in prep["products"])
    return f"{head}\n[오늘 주제] {prep['topic']}\n[상품 6개 — 상품명·가격만 사실 근거]\n{rows}\n"


# ------------------------------------------------------------ 2. check
def _len_ok(errs, where, s, n, required=True):
    if not s:
        if required:
            errs.append(f"{where}: 비어 있음")
        return
    if len(str(s)) > n:
        errs.append(f"{where}: '{s}'가 {n}자를 넘음({len(str(s))}자)")


def _lines_ok(errs, where, lines, lo, hi):
    if not isinstance(lines, list) or not lo <= len(lines) <= hi:
        errs.append(f"{where}.lines는 {lo}~{hi}문장")
        return []
    for k, ln in enumerate(lines):
        ln = str(ln).strip()
        if len(ln.replace("{가격}", "00,000원")) > MAX_LINE:
            errs.append(f"{where}.lines[{k}] {len(ln)}자 — {MAX_LINE}자 이내로 나눌 것: {ln}")
        if not ln.endswith((".", "?", "!")):
            errs.append(f"{where}.lines[{k}] . ? ! 로 끝내기: {ln}")
        if re.search(r"[일이삼사오육칠팔구십백천만]{2,}\s?(원|밀리|센티|리터|종|피스|개)", ln):
            errs.append(f"{where}.lines[{k}] 숫자는 아라비아 숫자로(한글 수사 금지): {ln}")
        if re.search(r"\d[\d,]*\s?(만\s?)?원", ln):
            errs.append(f"{where}.lines[{k}] 가격 직접 표기 금지 — 상품 구간에서 {{가격}}만 사용: {ln}")
    return lines


def validate(spec, prep):
    errs = []
    P = prep["products"]
    names = [p["name"] for p in P] + [f"{N_PRODUCTS}종 {N_PRODUCTS}가지 {N_PRODUCTS}개"]  # 상품 개수 언급은 허용
    _len_ok(errs, "title", spec.get("title"), 60)
    _len_ok(errs, "header", spec.get("header"), 22)
    _len_ok(errs, "description_intro", spec.get("description_intro"), 300)
    it = spec.get("intro") or {}
    for f, n in (("kicker", 18), ("title", 14), ("sub", 28)):
        _len_ok(errs, f"intro.{f}", it.get(f), n)
    toc = it.get("toc") or []
    if len(toc) != 4:
        errs.append("intro.toc는 4개")
    for k, t in enumerate(toc):
        _len_ok(errs, f"intro.toc[{k}]", t, 14)
    all_lines = list(_lines_ok(errs, "intro", it.get("lines"), 3, 5))
    gs = spec.get("guides") or []
    if not 3 <= len(gs) <= 5:
        errs.append("guides는 3~5개")
    for gi, g in enumerate(gs):
        w = f"guides[{gi}]"
        _len_ok(errs, f"{w}.kick", g.get("kick"), 16)
        _len_ok(errs, f"{w}.title", g.get("title"), 14)
        ls = _lines_ok(errs, w, g.get("lines"), 3, 6)
        all_lines += ls
        pts = g.get("points") or []
        if not 2 <= len(pts) <= 4:
            errs.append(f"{w}.points는 2~4개")
        for k, pt in enumerate(pts):
            _len_ok(errs, f"{w}.points[{k}]", (pt or {}).get("text"), 22)
            if not isinstance((pt or {}).get("at"), int) or not 0 <= pt["at"] < max(1, len(ls)):
                errs.append(f"{w}.points[{k}].at이 문장 범위 밖")
    prods = spec.get("products") or []
    picks = [p.get("pick") for p in prods]
    if sorted(picks) != list(range(N_PRODUCTS)):
        errs.append(f"products는 상품 0~{N_PRODUCTS - 1}을 한 번씩(현재 pick: {picks})")
    for k, p in enumerate(prods):
        w = f"products[{k}]"
        for f, n in (("short", 12), ("tag", 8), ("whom", 16), ("who2", 10), ("check", 24)):
            _len_ok(errs, f"{w}.{f}", p.get(f), n)
        bl = p.get("bullets") or []
        if len(bl) != 3:
            errs.append(f"{w}.bullets는 3개")
        for b in bl:
            _len_ok(errs, f"{w}.bullets", b, 20)
        ls = _lines_ok(errs, w, p.get("lines"), 4, 7)
        all_lines += ls
        if sum(str(x).count("{가격}") for x in ls) != 1:
            errs.append(f"{w}.lines에 {{가격}}을 정확히 1번")
        if isinstance(p.get("pick"), int) and 0 <= p["pick"] < len(P):
            src = P[p["pick"]]
            fields = {f"{w}.{f}": p.get(f) for f in ("short", "tag", "whom", "check")}
            fields.update({f"{w}.bullets[{j}]": b for j, b in enumerate(bl)})
            fields.update({f"{w}.lines[{j}]": x for j, x in enumerate(ls)})
            errs += [f"상품명에 없는 숫자 — {b}" for b in number_guard.unknown_numbers(fields, src["name"])]
    cp = spec.get("compare") or {}
    _len_ok(errs, "compare.title", cp.get("title"), 20)
    ls = _lines_ok(errs, "compare", cp.get("lines"), 3, 5)
    all_lines += ls
    errs += [f"상품명에 없는 숫자 — {b}" for b in number_guard.unknown_numbers({f"compare.lines[{j}]": x for j, x in enumerate(ls)}, *names)]
    si = spec.get("situations") or {}
    _len_ok(errs, "situations.title", si.get("title"), 16)
    cards = si.get("cards") or []
    if len(cards) != 4:
        errs.append("situations.cards는 4개")
    for k, c in enumerate(cards):
        _len_ok(errs, f"situations.cards[{k}].head", c.get("head"), 10)
        b = c.get("body") or []
        if len(b) != 2:
            errs.append(f"situations.cards[{k}].body는 2줄")
        for x in b:
            _len_ok(errs, f"situations.cards[{k}].body", x, 18)
    ls = _lines_ok(errs, "situations", si.get("lines"), 5, 5)
    all_lines += ls
    errs += [f"상품명에 없는 숫자 — {b}" for b in number_guard.unknown_numbers({f"situations.lines[{j}]": x for j, x in enumerate(ls)}, *names)]
    ca = spec.get("care") or {}
    _len_ok(errs, "care.title", ca.get("title"), 16)
    items = ca.get("items") or []
    if len(items) != 5:
        errs.append("care.items는 5개")
    for x in items:
        _len_ok(errs, "care.items", x, 20)
    all_lines += _lines_ok(errs, "care", ca.get("lines"), 6, 6)
    q = str(spec.get("outro_question") or "")
    if not q.endswith("?") and not q.endswith("요."):
        errs.append("outro_question은 질문 한 문장")
    _len_ok(errs, "outro_question", q, MAX_LINE)
    th = spec.get("thumbnail") or {}
    for f, n in (("left_label", 7), ("right_label", 7), ("question", 16), ("left_broll", 60), ("right_broll", 60)):
        _len_ok(errs, f"thumbnail.{f}", th.get(f), n)
    if not str(th.get("question", "")).endswith("?"):
        errs.append("thumbnail.question은 ?로 끝")
    for f in ("left_pick", "right_pick"):
        if th.get(f) not in range(N_PRODUCTS):
            errs.append(f"thumbnail.{f}는 0~{N_PRODUCTS - 1}")
    chips = th.get("chips") or []
    if len(chips) != 3:
        errs.append("thumbnail.chips는 3개")
    for c in chips:
        _len_ok(errs, "thumbnail.chips", c, 10)
    errs += [f"상품명에 없는 숫자 — {b}" for b in number_guard.unknown_numbers(
        {"title": spec.get("title"), "thumbnail.question": th.get("question"), **{f"chips[{j}]": c for j, c in enumerate(chips)}}, *names)]
    total = sum(len(str(x).replace("{가격}", "00,000원")) for x in all_lines)
    if not TARGET_CHARS * LEN_LO <= total <= TARGET_CHARS * LEN_HI:
        errs.append(f"전체 분량 {total}자 — {int(TARGET_CHARS * LEN_LO)}~{int(TARGET_CHARS * LEN_HI)}자로 맞출 것")
    return errs, total


def _load(json_file):
    spec = json.loads(Path(json_file).read_text(encoding="utf-8"))
    prep = json.loads((WORK / "prepared.json").read_text(encoding="utf-8"))
    return spec, prep


def cmd_check(json_file):
    spec, prep = _load(json_file)
    errs, total = validate(spec, prep)
    if errs:
        print(f"반려 {len(errs)}건 (분량 {total}자):")
        for e in errs:
            print(" -", e)
        sys.exit(1)
    print(f"OK ({total}자)")


# ------------------------------------------------------------ 3. build
def _pexels(query, n=2):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    cache = WORK / "broll"
    cache.mkdir(exist_ok=True)
    try:
        url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({"query": query, "orientation": "landscape", "per_page": 10})
        res = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": key, **UA}), timeout=30))
    except Exception as e:  # noqa: BLE001
        print(f"[lf2] Pexels 검색 실패({query}): {e}")
        return []
    out = []
    for v in res.get("videos", []):
        if v.get("duration", 0) < 8:
            continue
        fs = [f for f in v["video_files"] if f.get("height") and 720 <= f["height"] <= 1440 and f["width"] > f["height"]]
        if not fs:
            continue
        f = min(fs, key=lambda f: abs(f["height"] - 1080))
        p = cache / f"{v['id']}.mp4"
        if not p.exists():
            for attempt in range(3):  # 2026-10-06 로컬 시험에서 502 일시 오류 확인 → 재시도
                try:
                    p.write_bytes(urllib.request.urlopen(urllib.request.Request(f["link"], headers=UA), timeout=180).read())
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"[lf2] Pexels 다운로드 실패({attempt + 1}/3): {e}")
                    time.sleep(3)
            else:
                continue
        out.append(p)
        if len(out) >= n:
            break
    return out


_used_clips = set()


def broll(queries, fallback_photo, n=2):
    """검색어별로 아직 안 쓴 클립을 n개 모은다. 하나도 없으면 상품 사진 배경으로 대체."""
    got = []
    for q in queries or []:
        for p in _pexels(q, n + 2):
            if p not in _used_clips and len(got) < n:
                got.append(p)
                _used_clips.add(p)
        if len(got) >= n:
            break
    return got or [("image", fallback_photo)]


def seg_audio(key, lines):
    """문장별 합성 + 문장 사이 SENT_GAP. 반환: (wav, 길이, [(시작, 끝, 자막문장)])."""
    parts, times, t = [], [], 0.5
    for i, ln in enumerate(lines):
        p = WORK / "out" / f"{key}_{i}.wav"
        d = S.synth_line(ln, p)
        parts.append(p)
        times.append((t, t + d, ln))
        t += d + S.SENT_GAP
    total = t - S.SENT_GAP + 0.9
    ins, fc = [], ""
    for i, p in enumerate(parts):
        ins += ["-i", str(p)]
        fc += f"[{i}]adelay={int(times[i][0] * 1000)}|{int(times[i][0] * 1000)}[a{i}];"
    fc += "".join(f"[a{i}]" for i in range(len(parts))) + f"amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total:.2f}[o]"
    wav = WORK / "out" / f"{key}.wav"
    G.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", fc, "-map", "[o]", "-ar", "44100", "-ac", "2", str(wav)])
    return wav, total, times


def _fill_price(line, price):
    return line.replace("{가격}", f"{price:,}원")


def _frame(path, t, out):
    G.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-q:v", "2", str(out)])
    return Image.open(out)


def cmd_build(json_file):
    spec, prep = _load(json_file)
    errs, total = validate(spec, prep)
    if errs:
        print("check 반려 상태라 build하지 않습니다:", *errs, sep="\n - ")
        sys.exit(1)
    out = WORK / "out"
    out.mkdir(parents=True, exist_ok=True)
    P = prep["products"]
    photo = {p["i"]: WORK / f"p{p['i']}.jpg" for p in P}
    hdr = G.save(G.header(spec["header"]), out / "h.png")
    ranks = register_link_cards(spec, prep)  # 상품 n(원고 순서) → 링크 페이지 검색번호, 실패 시 전부 None
    plan = []  # (챕터명, key, lines, bg, layers_fn, kw)

    it = spec["intro"]
    plan.append(("인트로", "intro", it["lines"], broll(it.get("broll"), photo[0], 3),
                 lambda st, it=it: [(hdr, 0.0), (G.save(G.title_block(it["kicker"], it["title"], it["sub"]), out / "intro_t.png"), 0.3),
                                    (G.save(G.toc(it["toc"]), out / "toc.png"), st[-1])], {}))
    for gi, g in enumerate(spec["guides"]):
        def gl(st, g=g, gi=gi):
            ls = [(hdr, 0.0), (G.save(G.title_block(g["kick"], g["title"], None, 230), out / f"g{gi}_t.png"), 0.2)]
            prev = None
            for k, pt in enumerate(g["points"]):
                t0 = st[min(pt["at"], len(st) - 1)] + (0.8 if prev == pt["at"] else 0)
                ls.append((G.save(G.bullet(k + 1, pt["text"], 450 + k * 100), out / f"g{gi}_p{k}.png"), t0))
                prev = pt["at"]
            return ls
        plan.append((g["kick"].replace(" · ", " — ") + " " + g["title"], f"g{gi}", g["lines"], broll(g.get("broll"), photo[gi % N_PRODUCTS]), gl, {}))
    for n, p in enumerate(spec["products"]):
        src = P[p["pick"]]
        lines = [_fill_price(x, src["price"]) for x in p["lines"]]

        def pl(st, p=p, n=n, src=src):
            ls = [(hdr, 0.0), (G.save(G.rank_badge(n + 1, N_PRODUCTS), out / f"rk{n}.png"), 0.2),
                  (G.save(G.product_card(photo[src["i"]], p["short"], src["price"], ranks[n]), out / f"pc{n}.png"), 0.2),
                  (G.save(G.title_block(f"추천 {n + 1} · {p['tag']}", p["short"], None, 220, 1000), out / f"pt{n}.png"), 0.2)]
            for b in range(3):
                ls.append((G.save(G.bullet(b + 1, p["bullets"][b], 440 + b * 90, max_w=950), out / f"pb{n}_{b}.png"), st[min(b + 1, len(st) - 1)]))
            ls.append((G.save(G.for_whom(p["whom"]), out / f"pw{n}.png"), st[-2] if len(st) > 4 else st[-1]))
            ls.append((G.save(G.check_chip(p["check"]), out / f"pk{n}.png"), st[-1]))
            return ls
        plan.append((f"추천 {n + 1}. {p['short']} ({src['price']:,}원대)", f"p{n}", lines, broll(p.get("broll"), photo[src["i"]]), pl, {}))
    cp = spec["compare"]
    rows = [((f"No.{ranks[n]} " if ranks[n] else "") + p["short"], P[p["pick"]]["price"], p["tag"], p["who2"]) for n, p in enumerate(spec["products"])]
    plan.append(("한눈에 비교", "compare", cp["lines"], broll(spec["products"][0].get("broll"), photo[0], 1),
                 lambda st: [(hdr, 0.0), (G.save(G.compare_table(cp["title"], rows), out / "cmp.png"), 0.3)], {"shade": False, "blur": True}))
    si = spec["situations"]
    plan.append(("상황별 추천", "situ", si["lines"], broll(si.get("broll"), photo[1]),
                 lambda st: [(hdr, 0.0), (G.save(G.title_block("상황별 추천", si["title"], None, 200), out / "situ_t.png"), 0.2)]
                 + [(G.save(G.situ_card(k, c["head"], c["body"]), out / f"sc{k}.png"), st[min(k + 1, len(st) - 1)]) for k, c in enumerate(si["cards"])],
                 {"shade": False, "blur": True}))
    ca = spec["care"]
    plan.append(("오래 쓰는 관리법", "care", ca["lines"], broll(ca.get("broll"), photo[2]),
                 lambda st: [(hdr, 0.0), (G.save(G.title_block("오래 쓰는 관리법", ca["title"], None, 210), out / "care_t.png"), 0.2)]
                 + [(G.save(G.bullet(k + 1, x, 400 + k * 88), out / f"cp{k}.png"), st[min(k + 1, len(st) - 1)]) for k, x in enumerate(ca["items"])], {}))
    outro = [f"오늘 소개한 {N_PRODUCTS}가지 제품 정보는 설명란과 고정 댓글에 정리해 두었어요." if not ranks[0] else
             "제품 링크는 설명란과 고정 댓글, 그리고 링크 페이지에서 화면 속 검색번호로 찾으실 수 있어요.",
             "화면 속 가격은 영상 제작 시점 기준이라, 구매 전에 꼭 다시 확인해 주세요.", spec["outro_question"], DISCLOSURE]
    plan.append(("마무리", "outro", outro, broll(it.get("broll"), photo[3], 1),
                 lambda st: [(hdr, 0.0), (G.save(G.title_block("구매 전 확인하세요", "링크는 설명란 · 고정 댓글",
                        f"검색번호 No.{ranks[0]}~{ranks[-1]} · 링크 페이지" if ranks[0] else "가격은 제작 시점 기준 · 바뀔 수 있어요"), out / "out_t.png"), 0.2)], {}))

    segs, chapters, t = [], [], 0.0
    for idx, (chap, key, lines, bg, layer_fn, kw) in enumerate(plan):
        wav, dur, times = seg_audio(key, lines)
        st = [a for a, _b, _l in times]
        seg = G.render_segment(bg, wav, dur, times, layer_fn(st), out / f"seg{idx:02d}.mp4", out, key, **kw)
        segs.append(seg)
        if not (key.startswith("g") and key != "g0"):
            chapters.append((t, "고르는 기준" if key == "g0" else chap))
        t += dur
        print(f"[lf2] {idx + 1}/{len(plan)} {key} {dur:.1f}s", flush=True)
    lst = out / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs))
    raw = out / "raw.mp4"
    G.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(raw)])
    final = WORK / "longform.mp4"
    G.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", str(final)])

    th = spec["thumbnail"]
    thumb = WORK / "thumb.png"
    try:
        _ensure_rembg()
        lb, rb = broll([th["left_broll"]], photo[th["left_pick"]], 1)[0], broll([th["right_broll"]], photo[th["right_pick"]], 1)[0]
        # 배경 영상이 없어 상품 사진으로 대체되면, 위에 얹는 누끼와 겹쳐 보이지 않게 크게 흐린다
        blur = lambda im: im.convert("RGB").filter(ImageFilter.GaussianBlur(28))  # noqa: E731
        lbg = blur(Image.open(lb[1])) if isinstance(lb, tuple) else _frame(lb, 3, out / "tl.jpg")
        rbg = blur(Image.open(rb[1])) if isinstance(rb, tuple) else _frame(rb, 3, out / "tr.jpg")
        G.thumbnail_vs(lbg, rbg, G.cutout(photo[th["left_pick"]], out / "cutL.png"), G.cutout(photo[th["right_pick"]], out / "cutR.png"),
                       th["left_label"], th["right_label"], th["question"], th["chips"], thumb)
    except Exception as e:  # noqa: BLE001
        print(f"[lf2] 썸네일 생성 실패(업로드는 계속): {e}")
        thumb = None

    chap_txt = "\n".join(f"{int(a // 60)}:{int(a % 60):02d} {c}" for a, c in chapters)
    links = "\n".join(f"- {'No.' + str(ranks[n]) + ' ' if ranks[n] else ''}{p['short']} ({P[p['pick']]['price']:,}원대): {P[p['pick']]['url']}"
                      for n, p in enumerate(spec["products"]))
    if ranks[0]:
        links += f"\n\n🔎 링크 페이지에서 검색번호로도 찾을 수 있어요: {LINK_PAGE}"
    desc = (f"{spec['description_intro']}\n\n[제품 링크]\n{links}\n\n[목차]\n{chap_txt}\n\n"
            f"※ 가격은 영상 제작 시점 기준이며 바뀔 수 있습니다.\n이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.\n"
            f"이 영상은 AI를 활용해 제작한 콘텐츠입니다.\n\n#{prep['topic'].replace('·', '').replace(' ', '')}추천 #가성비 #살림템 #쇼핑의천국")
    topic = prep["topic"].replace("·", " ")
    tags = list(dict.fromkeys([f"{topic} 추천", f"{topic} 비교", topic, "가성비", "살림템", "제품추천", "쿠팡추천", "쇼핑의천국"]
                              + [p["short"] for p in spec["products"]]))
    import compile_longform as CL
    res = CL.upload_longform(final, spec["title"], desc, tags, thumb)
    print(f"[lf2] 업로드 완료: {res['url']}")

    comment = "이 영상에서 소개한 제품 링크예요 👇\n" + links + "\n\n※ 가격은 시점에 따라 달라질 수 있어요.\n이 댓글은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
    try:
        subprocess.run(["python3", str(HERE / "post_comment.py"), "--video-id", res["video_id"], "--text", comment], check=True)
    except Exception as e:  # noqa: BLE001
        print(f"[lf2] 댓글 등록 실패(무시): {e}")

    st = load_state()
    st["history"].append({"date": prep["date"], "topic": prep["topic"], "video_id": res["video_id"], "title": spec["title"]})
    save_state(st)
    _commit_state()
    mins = t / 60
    notify(f"✅ [쇼핑의천국] 새 롱폼 발행: {spec['title']}\n{res['url']}\n{mins:.1f}분 · 상품 {N_PRODUCTS}개 · 주제 {prep['topic']}")
    print(f"DONE {res['url']}")


def register_link_cards(spec, prep):
    """링크 페이지(부업실험실)에 6개를 항상 새 번호로 연속 등록(2026-10-06 사용자 확정).
    옛 쇼츠 카드와 구분되도록 한 줄 소개에 '주제 6종 비교 · M/D 기준'을 넣는다. 실패하면 번호 없이 진행."""
    P = prep["products"]
    d = datetime.fromisoformat(prep["date"])
    items = [{"title": P[p["pick"]]["name"][:20], "price": f"{P[p['pick']]['price']:,}원대", "url": P[p["pick"]]["url"],
              "image": P[p["pick"]].get("image", ""),
              "sub": f"{prep['topic']} {N_PRODUCTS}종 비교 · {d.month}/{d.day} 기준 · {p['whom']}"} for p in spec["products"]]
    try:
        import update_link_page
        return update_link_page.add_cards(items)
    except Exception as e:  # noqa: BLE001
        notify(f"⚠️ [쇼핑의천국] 새 롱폼 링크 페이지 등록 실패 — 검색번호 없이 진행합니다: {e}")
        return [None] * len(items)


def _ensure_rembg():
    try:
        import rembg  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "rembg", "onnxruntime"], check=False)


def _commit_state():
    g = ["git", "-C", str(REPO_ROOT)]
    subprocess.run(g + ["add", str(STATE_PATH)], check=True)
    subprocess.run(g + ["-c", "user.email=bot@shopping-paradise.local", "-c", "user.name=shopping-paradise-bot",
                        "commit", "-m", "Record new comparison longform"], check=False)
    for _ in range(3):
        if subprocess.run(g + ["push", "origin", "HEAD:main"]).returncode == 0:
            return
        subprocess.run(g + ["pull", "--rebase", "origin", "main"])
    notify("⚠️ [쇼핑의천국] 새 롱폼 상태 파일 push 실패 — 다음 실행이 같은 날짜를 모를 수 있음")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "check", "build"])
    ap.add_argument("--json-file")
    ap.add_argument("--force", action="store_true", help="3일 간격 무시(수동 실행용)")
    a = ap.parse_args()
    try:
        if a.cmd == "prepare":
            cmd_prepare(a.force)
        elif a.cmd == "check":
            cmd_check(a.json_file)
        else:
            cmd_build(a.json_file)
    except SystemExit:
        raise
    except Exception as e:
        notify(f"⚠️ [쇼핑의천국] 새 롱폼 {a.cmd} 단계 실패: {e}")
        raise
