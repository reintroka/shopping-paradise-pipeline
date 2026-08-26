"""영상이 공개 상태가 되면(재시도) 유튜브 댓글로 링크 홍보.

환경변수: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
"""
import argparse
import os
import time

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
]


def get_youtube():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def is_public(youtube, video_id):
    resp = youtube.videos().list(part="status", id=video_id).execute()
    items = resp.get("items", [])
    return bool(items) and items[0]["status"]["privacyStatus"] == "public"


def post_comment(youtube, video_id, text):
    body = {"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}
    resp = youtube.commentThreads().insert(part="snippet", body=body).execute()
    return resp["id"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video-id", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--max-retries", type=int, default=10)
    p.add_argument("--wait-sec", type=int, default=30)
    args = p.parse_args()

    youtube = get_youtube()
    for attempt in range(1, args.max_retries + 1):
        if is_public(youtube, args.video_id):
            comment_id = post_comment(youtube, args.video_id, args.text)
            print(f"댓글 작성 완료: {comment_id}")
            return
        print(f"[{attempt}/{args.max_retries}] 아직 비공개 — {args.wait_sec}초 대기")
        time.sleep(args.wait_sec)
    raise RuntimeError("영상이 공개로 전환되지 않아 댓글 작성 실패")


if __name__ == "__main__":
    main()
