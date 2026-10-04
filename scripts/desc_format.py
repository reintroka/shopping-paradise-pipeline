"""유튜브 설명란 가독성 정리 — 업로드 직전(videos.insert/update) 한 곳에서 일괄 적용.

2026-10-04: 설명란 첫 단락이 3~4문장(플레이리스트는 400자짜리 한 문장)을 줄바꿈 없이
한 줄로 붙여 써서 모바일에서 벽돌 텍스트로 보인다는 지적 — 문장마다 줄을 바꾸고,
너무 긴 문장은 쉼표/대시 마디에서 끊고, 해시태그 줄은 맨 아래로 모은다.
타임스탬프(0:00 ...)/번호 목록/URL/이모지 머리줄은 이미 한 줄 단위라 건드리지 않는다.
실패해도 원문 그대로 반환 — 설명란 정리 때문에 업로드가 막히면 안 된다.
"""
from __future__ import annotations

import re

_SENT_END = re.compile(r"([.!?。！？।…]+[\"'”’」』)\]]*)\s+(?=\S)")
_HASHTAG_LINE = re.compile(r"^(#[^\s#]+\s*)+$")
_STRUCTURED = re.compile(
    r"^\s*(\d{1,2}:\d{2}|\d+[.)]\s|[-•·▶▷►⏱📌🎵🔁🔔✅👉※*]|https?://)"
)
_LONG_SENTENCE = 110   # 이 글자 수를 넘는 한 문장은 마디에서 나눈다
_CLAUSE_TARGET = 60    # 마디를 이어 붙일 때 한 줄 목표 길이


def _split_long_sentence(sentence: str) -> list[str]:
    if len(sentence) <= _LONG_SENTENCE:
        return [sentence]
    # " - " / " — " 앞에서 먼저 끊고(요약 꼬리 분리), 그다음 쉼표 마디로 묶는다.
    pieces = re.split(r"\s+(?=[-—–]\s)", sentence)
    out: list[str] = []
    for piece in pieces:
        if len(piece) <= _LONG_SENTENCE:
            out.append(piece)
            continue
        clauses = re.split(r"(?<=,)\s+", piece)
        line = ""
        for c in clauses:
            if line and len(line) + 1 + len(c) > _CLAUSE_TARGET:
                out.append(line)
                line = c
            else:
                line = f"{line} {c}" if line else c
        if line:
            out.append(line)
    return out


def _format_prose_line(line: str) -> list[str]:
    sentences = [s.strip() for s in _SENT_END.sub(r"\1\n", line).split("\n") if s.strip()]
    out: list[str] = []
    for s in sentences:
        out.extend(_split_long_sentence(s))
    return out


def format_description(text: str) -> str:
    try:
        return _format(text)
    except Exception:  # noqa: BLE001
        return text


def _format(text: str) -> str:
    if not text or not text.strip():
        return text
    lines = text.replace("\r\n", "\n").split("\n")
    body: list[str] = []
    hashtags: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if _HASHTAG_LINE.match(stripped):
            for tag in stripped.split():
                if tag not in hashtags:
                    hashtags.append(tag)
            continue
        if not stripped or _STRUCTURED.match(stripped) or "http" in stripped:
            # 리캡 목록에 숏폼 원제가 그대로 들어가 " #Shorts"가 줄마다 붙던 것 제거
            if re.match(r"^\s*\d+[.)]\s", stripped):
                line = re.sub(r"\s*#[Ss]horts\s*$", "", line)
            body.append(line)
            continue
        formatted = _format_prose_line(stripped)
        if len(formatted) > 1:
            # 여러 줄로 나뉜 단락은 앞뒤를 한 줄 띄워 다른 단락과 구분
            if body and body[-1].strip():
                body.append("")
            body.extend(formatted)
            body.append("")
        else:
            body.extend(formatted)
    if hashtags:
        body.append("")
        body.append(" ".join(hashtags))
    result = "\n".join(body)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result
