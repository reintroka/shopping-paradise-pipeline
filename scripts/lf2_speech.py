"""새 롱폼(같은 종류 비교형, longform_v2.py)의 나레이션: 숫자 읽기 변환 + 쉼표/마침표 호흡 TTS.

2026-10-06 사용자 확정 사항:
- 쉼표 뒤·마침표 뒤에 호흡이 있어야 한다 → Chirp3-HD는 쉼표에서 거의 안 쉬므로 쉼표마다 끊어 따로
  합성하고 COMMA_GAP 무음을 넣는다. 문장 사이는 SENT_GAP(호출하는 쪽에서 배치).
- "2종"을 "두 종"으로 읽으면 안 된다 → 자막은 아라비아 숫자 그대로 두고, 읽을 때만 이 모듈이
  단위에 맞는 한자어/고유어로 바꾼다(종·피스·ml 등은 한자어, 개·가지·명은 고유어).
"""
import base64
import json
import os
import re
import urllib.request
import wave
from array import array
from pathlib import Path

from korean_number import number_to_korean

ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
VOICE = "ko-KR-Chirp3-HD-Aoede"
RATE = 24000
COMMA_GAP, SENT_GAP = 0.35, 0.75

_NATIVE = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉", 10: "열",
           11: "열한", 12: "열두", 13: "열세", 14: "열네", 15: "열다섯", 16: "열여섯", 17: "열일곱", 18: "열여덟",
           19: "열아홉", 20: "스무"}
_NATIVE_COUNTERS = ("개", "가지", "명", "번", "벌", "켤레", "살", "시간", "잔", "통", "병", "알", "포기")
# 단위 표기 → 읽는 말(한자어 수사와 함께). 긴 것부터 매칭.
_UNIT_READ = {"mAh": "밀리암페어", "ml": "밀리리터", "mL": "밀리리터", "ML": "밀리리터", "L": "리터", "l": "리터",
              "cm": "센티", "mm": "밀리", "kg": "킬로", "g": "그램", "GB": "기가", "TB": "테라", "W": "와트",
              "%": "퍼센트", "P": "피스", "p": "피스", "인치": "인치", "종": "종", "피스": "피스", "인용": "인용",
              "단": "단", "구": "구", "매": "매", "장": "장", "년": "년", "세트": "세트", "인분": "인분", "도": "도", "분": "분"}
_UNITS_RE = "|".join(sorted(map(re.escape, list(_UNIT_READ) + list(_NATIVE_COUNTERS)), key=len, reverse=True))
_NUM_UNIT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(" + _UNITS_RE + r")(?![a-zA-Z])")
_BARE_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _sino(num: str) -> str:
    num = num.replace(",", "")
    whole, _, frac = num.partition(".")
    s = number_to_korean(int(whole))
    if frac:
        s += "점" + "".join("영일이삼사오육칠팔구"[int(c)] for c in frac)
    return s


def read_numbers(text: str) -> str:
    """자막용 문장 → TTS용 문장. '2종'→'이 종', '240ml'→'이백사십 밀리리터', '3개'→'세 개', '1.5L'→'일점오 리터'."""
    def unit(m):
        num, u = m.group(1), m.group(2)
        n = num.replace(",", "")
        if u in _NATIVE_COUNTERS and "." not in n and 1 <= int(n) <= 20:
            return f"{_NATIVE[int(n)]} {u}"
        return f"{_sino(num)} {_UNIT_READ.get(u, u)}"
    text = _NUM_UNIT.sub(unit, text)
    return _BARE_NUM.sub(lambda m: _sino(m.group(0)), text)


def _synth_pcm(text: str) -> array:
    body = {"input": {"text": text}, "voice": {"languageCode": "ko-KR", "name": VOICE},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": RATE}}
    last = None
    for _ in range(4):
        try:
            req = urllib.request.Request(f"{ENDPOINT}?key={os.environ['GOOGLE_TTS_API_KEY']}", data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = base64.b64decode(json.loads(resp.read())["audioContent"])
            break
        except Exception as e:  # noqa: BLE001 — 일시 오류(503 등)는 재시도
            last = e
    else:
        raise RuntimeError(f"TTS 실패: {last}")
    a = array("h", raw[44:])
    # 앞뒤 무음을 잘라 호흡 길이를 정확히 맞추고, 가장자리 10ms 페이드로 '딱' 소리를 막는다
    idx = [i for i in range(0, len(a), 48) if abs(a[i]) > 350]
    if idx:
        a = a[max(0, idx[0] - 720):min(len(a), idx[-1] + 1440)]
    f = min(240, len(a) // 2)
    for i in range(f):
        a[i] = int(a[i] * i / f)
        a[-1 - i] = int(a[-1 - i] * i / f)
    return a


def synth_line(caption_text: str, out: Path) -> float:
    """자막 문장 하나를 읽어 wav로 저장하고 길이(초)를 돌려준다(실제 합성은 _synth_line_uncached).

    2026-10-08: 비교형 롱폼이 업로드 등 막판에 실패해 같은 날 다시 돌리면, 클라우드 샌드박스라
    work/가 사라져 약 4천 자를 Google TTS로 또 돈 내고 합성했다(사용자 지시: "재발행시 돈 안 들게").
    실제로 읽는 글(숫자 읽기 변환 후)+목소리+이 모듈 코드의 해시를 키로 wav를 GCS에 저장해 두고,
    같으면 받아만 온다(rerun_cache.get_bytes/put_bytes). 캐시 오류는 경고만 하고 그냥 합성한다."""
    try:
        import rerun_cache
    except Exception:  # noqa: BLE001 - 캐시 모듈이 없으면 그냥 합성
        return _synth_line_uncached(caption_text, out)
    key = "lf2_tts/" + rerun_cache.sha({
        "voice": VOICE, "rate": RATE, "comma_gap": COMMA_GAP, "text": caption_text,
        "speak": read_numbers(caption_text),
        "code": rerun_cache.sha(Path(__file__).read_bytes().decode("utf-8", "replace")),  # 이 모듈이 고쳐지면 옛 캐시 무시
    }) + ".wav"
    data = rerun_cache.get_bytes(key)
    if data:
        out.write_bytes(data)
        with wave.open(str(out), "rb") as w:
            frames = w.getnframes()
        print(f"[재실행 캐시] TTS 재사용(합성 생략): {caption_text[:24]}")
        return frames / RATE
    dur = _synth_line_uncached(caption_text, out)
    rerun_cache.put_bytes(key, out.read_bytes(), "audio/wav")
    return dur


def _synth_line_uncached(caption_text: str, out: Path) -> float:
    """자막 문장 하나를 읽어 wav로 저장하고 길이(초)를 돌려준다. 쉼표마다 끊어 COMMA_GAP을 넣는다."""
    chunks = [c.strip() for c in re.split(r"(?<=,)\s+", read_numbers(caption_text)) if c.strip()]
    pcm = array("h")
    for k, c in enumerate(chunks):
        if k:
            pcm.extend([0] * int(RATE * COMMA_GAP))
        pcm.extend(_synth_pcm(c))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return len(pcm) / RATE
