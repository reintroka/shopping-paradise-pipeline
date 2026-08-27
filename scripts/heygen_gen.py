"""HeyGen 아바타 영상(훅+CTA) 생성.

캐릭터별 목소리(2026-08-26 세션에서 확정, 재탐색 불필요):
  female(지은): Gentle Gemma - 37311b8fa31d4b0591d7f1ca012e2c59
  male(민준):  Korean Fin-Analyst - x9yUsHEv2yOPCBKlOk10

스펙 설명 구간 나레이션은 더 이상 여기서 만들지 않음 — "AI같이 들린다"는 피드백으로
2026-08-27부터 google_tts.py(Google Cloud TTS)로 교체됨. run_pipeline.py가 이 스크립트
다음에 google_tts.py를 별도로 호출한다.
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

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CHAR_HISTORY_PATH = REPO_ROOT / "character_image_history.json"


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
        # 2026-08-27: HeyGen v3 API가 "dimension":{width,height} 커스텀 객체를 더 이상
        # 안 받고(strict schema, "Extra inputs are not permitted" 400) resolution enum으로
        # 교체함. aspect_ratio만으로는 기본 해상도가 낮게 나와 최종 합성 시 ffmpeg 업스케일로
        # 화질이 뭉개지는 문제가 있었으므로, 최종 출력(1080x1920)에 맞춰 1080p를 명시.
        "resolution": "1080p",
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


def _load_char_history() -> dict:
    if CHAR_HISTORY_PATH.exists():
        return json.loads(CHAR_HISTORY_PATH.read_text(encoding="utf-8"))
    return {}


def _save_char_history(history: dict):
    CHAR_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_char_image(char_dir: Path, character: str, role: str, avoid_path=None) -> Path:
    """준비해둔 캐릭터 시트(장당 27~28장)를 전부 돌아가며 쓰도록 이력 기록.

    2026-08-27: 예전엔 키워드로 좁힌 후보군(예: hook="pointing/office/desk")에서 매번
    완전 랜덤으로 뽑아서, 실제 매칭되는 사진이 2장뿐인 경우가 있어 같은 사진이 자주
    반복되고 나머지 25장 이상이 거의 안 쓰이는 문제가 있었음("캐릭터 시트 많이 만들어
    둔거 잘 활용해서 돌아가면서, 중복으로 내보내지 말라"는 피드백). 이제 키워드 제한
    없이 전체 폴더를 대상으로, 한 사이클(전체 장수) 다 쓰기 전엔 같은 사진이 다시
    나오지 않도록 사용 이력을 `character_image_history.json`에 기록. 다 쓰면 이력을
    비우고 새 사이클 시작.

    단, 파일명에 "laptop"이 들어간 사진(노트북을 가리키거나 타이핑하는 포즈)은 후보에서
    아예 제외 — 이건 LG그램15(노트북) 리뷰용으로 만든 사진이라 그 상품일 때만 맞고,
    상품은 매번 랜덤으로 바뀌는데(공기청정기, 로봇청소기 등) 노트북을 가리키는 모습이
    나오면 상품과 안 맞아서 어색해 보인다는 피드백으로 제외함.
    """
    files = sorted(f for f in char_dir.glob("*.jpeg") if "laptop" not in f.name.lower())
    history = _load_char_history()
    key = f"{character}_{role}"
    used = set(history.get(key, []))
    candidates = [f for f in files if f.name not in used and f != avoid_path]
    if not candidates:
        used = set()
        candidates = [f for f in files if f != avoid_path]
    picked = random.choice(candidates)
    used.add(picked.name)
    history[key] = sorted(used)
    _save_char_history(history)
    return picked


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

    hook_img = pick_char_image(char_dir, args.character, "hook")
    cta_img = pick_char_image(char_dir, args.character, "cta", avoid_path=hook_img)
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


if __name__ == "__main__":
    main()
