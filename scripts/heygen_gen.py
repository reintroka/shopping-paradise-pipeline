"""HeyGen 아바타 영상(훅+CTA) + TTS 나레이션(스펙 설명 구간) 생성.

캐릭터별 목소리(2026-08-26 세션에서 확정, 재탐색 불필요):
  female(지은): Gentle Gemma - 37311b8fa31d4b0591d7f1ca012e2c59
  male(민준):  Korean Fin-Analyst - x9yUsHEv2yOPCBKlOk10
"""
import argparse
import json
import os
import random
import time
from pathlib import Path
from urllib import request as urlreq

VOICE_IDS = {
    "female": "37311b8fa31d4b0591d7f1ca012e2c59",
    "male": "x9yUsHEv2yOPCBKlOk10",
}

API_KEY_ENV = "HEYGEN_API_KEY"


def _headers(extra=None):
    h = {"x-api-key": os.environ[API_KEY_ENV]}
    if extra:
        h.update(extra)
    return h


def _post_json(url, body, extra_headers=None):
    data = json.dumps(body).encode("utf-8")
    req = urlreq.Request(url, data=data, headers=_headers({"Content-Type": "application/json", **(extra_headers or {})}), method="POST")
    with urlreq.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_json(url):
    req = urlreq.Request(url, headers=_headers())
    with urlreq.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def upload_image(image_path: Path) -> str:
    boundary = "----heygenboundary"
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{image_path.name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urlreq.Request(
        "https://api.heygen.com/v3/assets",
        data=body,
        headers=_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
        method="POST",
    )
    with urlreq.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    return result["data"]["asset_id"]


def create_video(asset_id: str, script: str, voice_id: str, title: str) -> str:
    body = {
        "type": "image",
        "image": {"type": "asset_id", "asset_id": asset_id},
        "script": script,
        "voice_id": voice_id,
        "voice_settings": {"locale": "ko-KR"},
        "aspect_ratio": "9:16",
        "title": title,
    }
    result = _post_json("https://api.heygen.com/v3/videos", body)
    return result["data"]["video_id"]


def poll_video(video_id: str, max_tries=40, wait_sec=5) -> str:
    for _ in range(max_tries):
        result = _get_json(f"https://api.heygen.com/v1/video_status.get?video_id={video_id}")
        status = result.get("data", {}).get("status")
        if status == "completed":
            return result["data"]["video_url"]
        if status == "failed":
            raise RuntimeError(f"HeyGen 영상 생성 실패: {result}")
        time.sleep(wait_sec)
    raise RuntimeError("HeyGen 영상 생성 타임아웃")


def download(url: str, out_path: Path):
    req = urlreq.Request(url)
    with urlreq.urlopen(req, timeout=60) as resp:
        out_path.write_bytes(resp.read())


def tts_speech(text: str, voice_id: str, out_path: Path) -> dict:
    result = _post_json(
        "https://api.heygen.com/v3/voices/speech",
        {"text": text, "voice_id": voice_id, "locale": "ko-KR"},
    )
    audio_url = result["data"]["audio_url"]
    download(audio_url, out_path)
    meta_path = out_path.with_suffix(".json")
    meta_path.write_text(json.dumps(result["data"], ensure_ascii=False, indent=2), encoding="utf-8")
    return result["data"]


def pick_char_image(char_dir: Path, prefer_keywords, avoid_path=None):
    files = list(char_dir.glob("*.jpeg"))
    preferred = [f for f in files if any(k in f.name.lower() for k in prefer_keywords) and f != avoid_path]
    pool = preferred if preferred else [f for f in files if f != avoid_path]
    return random.choice(pool)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--character", choices=["female", "male"], required=True)
    p.add_argument("--char-dir", required=True, help="캐릭터 이미지 폴더")
    p.add_argument("--script-json", required=True, help="gen_script.py 출력 JSON")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    char_dir = Path(args.char_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    script_data = json.loads(open(args.script_json, encoding="utf-8").read())
    voice_id = VOICE_IDS[args.character]

    hook_img = pick_char_image(char_dir, ["pointing", "office", "desk"])
    cta_img = pick_char_image(char_dir, ["smiling", "sitting"], avoid_path=hook_img)
    print(f"훅 이미지: {hook_img.name}, CTA 이미지: {cta_img.name}")

    hook_asset = upload_image(hook_img)
    cta_asset = upload_image(cta_img)

    hook_vid_id = create_video(hook_asset, script_data["hook_speech"], voice_id, "auto-hook")
    cta_vid_id = create_video(cta_asset, script_data["cta_speech"], voice_id, "auto-cta")

    hook_url = poll_video(hook_vid_id)
    download(hook_url, out_dir / "hook.mp4")
    print("훅 영상 다운로드 완료")

    cta_url = poll_video(cta_vid_id)
    download(cta_url, out_dir / "cta.mp4")
    print("CTA 영상 다운로드 완료")

    tts_speech(script_data["narration_script"], voice_id, out_dir / "middle_narration.mp3")
    print("나레이션 오디오 생성 완료")


if __name__ == "__main__":
    main()
