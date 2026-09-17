"""파이프라인 실행 결과를 텔레그램으로 알림 (2026-08-27 도입).

매 실행(성공/실패 무관)마다 run_pipeline.py 끝에서 호출됨. 부가 단계(X 포스트,
유튜브 댓글, 링크페이지 업데이트 등)가 실패해도 파이프라인 자체는 계속 진행되는
soft_step 구조라, 그런 실패를 놓치지 않으려고 요약 메시지에 다 담아서 보낸다.

필요한 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
(텔레그램에서 @BotFather로 봇 생성 -> 토큰 발급 -> 그 봇에게 메시지 한 번 보낸 뒤
 https://api.telegram.org/bot<토큰>/getUpdates 로 chat_id 확인)
"""
import json
import os
import time
import urllib.request
from pathlib import Path

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


def send(text: str) -> None:
    token = os.environ[TOKEN_ENV]
    chat_id = os.environ[CHAT_ID_ENV]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def send_photos(image_paths: list, caption: str = "") -> None:
    """이미지 여러 장을 한 메시지(media group)로 전송 — 틱톡 카드뉴스를 API로 자동
    발행하는 대신 사람이 직접 업로드하도록 텔레그램으로 넘길 때 씀(2026-09-18).

    coredlab(명리마스터) 코드베이스에서 이미 같은 문제를 겪고 정리한 패턴을 그대로
    가져옴 — 틱톡 포토모드 API(PULL_FROM_URL)를 시도했다가 "TikTok photo-mode direct
    API posting is blocked pending audit/URL verification"로 확인되어 텔레그램 전송으로
    교체한 이력이 있음(commit 824e084, 2026-09-02). shopping-paradise-pipeline의
    post_tiktok.py --mode photo도 같은 API를 쓰므로 동일하게 막혀있을 가능성이 높아
    처음부터 이 방식을 기본으로 씀.

    캡션은 사진에 안 붙이고(텔레그램 media group 캡션 1024자 제한 + 복사 시 안내문까지
    같이 잡히는 불편함) 뒤이어 별도 텍스트 메시지로 보낸다.
    """
    token = os.environ[TOKEN_ENV]
    chat_id = os.environ[CHAT_ID_ENV]
    boundary = f"----shoppingparadise{int(time.time())}"
    media_json = [{"type": "photo", "media": f"attach://photo{i}"} for i in range(len(image_paths))]

    body_parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode("utf-8"),
        f'--{boundary}\r\nContent-Disposition: form-data; name="media"\r\n\r\n'
        f'{json.dumps(media_json, ensure_ascii=False)}\r\n'.encode("utf-8"),
    ]
    for i, path in enumerate(image_paths):
        header = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="photo{i}"; filename="photo{i}.png"\r\n'
            f'Content-Type: image/png\r\n\r\n'
        ).encode("utf-8")
        body_parts.append(header + Path(path).read_bytes() + b"\r\n")
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(body_parts)

    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()

    if caption:
        send(caption)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    args = p.parse_args()
    send(args.text)
