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
import urllib.request

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


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--text", required=True)
    args = p.parse_args()
    send(args.text)
