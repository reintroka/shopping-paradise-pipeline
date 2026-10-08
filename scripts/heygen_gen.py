"""HeyGen 아바타 영상(훅+CTA) 생성.

캐릭터별 목소리(2026-08-26 세션에서 확정, 재탐색 불필요):
  female(지은): Gentle Gemma - 37311b8fa31d4b0591d7f1ca012e2c59
  male(민준):  Korean Fin-Analyst - x9yUsHEv2yOPCBKlOk10

스펙 설명 구간 나레이션은 더 이상 여기서 만들지 않음 — "AI같이 들린다"는 피드백으로
2026-08-27부터 google_tts.py(Google Cloud TTS)로 교체됨. run_pipeline.py가 이 스크립트
다음에 google_tts.py를 별도로 호출한다.
"""
import argparse
import http.client
import json
import os
import random
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

VOICE_IDS = {
    "female": "37311b8fa31d4b0591d7f1ca012e2c59",
    "male": "x9yUsHEv2yOPCBKlOk10",
}

API_KEY_ENV = "HEYGEN_API_KEY"

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CHAR_HISTORY_PATH = REPO_ROOT / "character_image_history.json"

# 2026-09-15: CTA 영상 상태를 poll_video()에서 폴링하던 도중 HeyGen API와의 연결이
# ConnectionResetError로 끊겨(일시적 네트워크 블립) 예외가 그대로 전파되며 파이프라인
# 전체가 크래시한 사고 발생 — 상품 선정/대본/그래픽/상품영상까지 이미 만든 작업이
# 통째로 날아갔었다. 이 스크립트의 HTTP 호출엔 재시도가 전혀 없었던 게 근본 원인이라
# (HTTPError 4xx/5xx는 재시도해도 소용없으니 그대로 올리고) 일시적 연결 오류만 재시도.
_TRANSIENT_ERRORS = (URLError, socket.error, http.client.RemoteDisconnected, ConnectionResetError, TimeoutError)


# 2026-10-05: 남성 저녁편이 create_video에서 "HTTP Error 404: NOT FOUND"만 남기고 죽음.
# urllib의 HTTPError는 HeyGen 응답 본문(error.code: asset_not_found/voice_not_found 등)을
# 버려서 텔레그램 알림만으론 무엇이 404였는지 알 수 없었다 — 본문을 예외 메시지에 담는다.
class HeyGenHTTPError(Exception):
    def __init__(self, code, label, body):
        self.code = code
        self.body = body
        super().__init__(f"HeyGen {label} 실패 HTTP {code}: {body}")


def _read_error_body(e):
    try:
        return e.read().decode("utf-8", errors="replace")[:500]
    except Exception:
        return "(응답 본문 읽기 실패)"


def _headers(extra=None):
    h = {"x-api-key": os.environ[API_KEY_ENV]}
    if extra:
        h.update(extra)
    return h


def _urlopen_with_retry(build_request, timeout, label, retries=3, wait_sec=5):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urlreq.urlopen(build_request(), timeout=timeout) as resp:
                return resp.read()
        except HTTPError as e:
            raise HeyGenHTTPError(e.code, label, _read_error_body(e)) from None
        except _TRANSIENT_ERRORS as e:
            last_err = e
            print(f"[heygen_gen] {label} 네트워크 오류 (시도 {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(wait_sec)
    raise last_err


def _post_json(url, body, extra_headers=None):
    data = json.dumps(body).encode("utf-8")
    req = lambda: urlreq.Request(url, data=data, headers=_headers({"Content-Type": "application/json", **(extra_headers or {})}), method="POST")
    return json.loads(_urlopen_with_retry(req, 30, f"POST {url}"))


def _get_json(url):
    req = lambda: urlreq.Request(url, headers=_headers())
    return json.loads(_urlopen_with_retry(req, 30, f"GET {url}"))


def upload_image(image_path: Path) -> str:
    boundary = "----heygenboundary"
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{image_path.name}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = lambda: urlreq.Request(
        "https://api.heygen.com/v3/assets",
        data=body,
        headers=_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
        method="POST",
    )
    result = json.loads(_urlopen_with_retry(req, 60, "이미지 업로드"))
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


def create_video_with_retry(image_path: Path, asset_id: str, script: str, voice_id: str, title: str, retries=3) -> str:
    """create_video가 404면 잠깐 기다렸다 재시도, 마지막 시도 전엔 이미지를 다시 올린다.

    2026-10-05: 남성 저녁편에서 훅 생성은 받아들여졌는데 바로 이어진 CTA 생성이 404로
    거절돼 파이프라인 전체가 죽었다. 같은 목소리·같은 요청이 전날과 직전 훅에선 정상이라
    업로드 직후 에셋이 아직 조회되지 않는 등 HeyGen 쪽 일시 404로 판단 — 404만 재시도하고
    다른 4xx(잘못된 요청)는 재시도해도 소용없으니 그대로 올린다.
    """
    for attempt in range(1, retries + 1):
        try:
            return create_video(asset_id, script, voice_id, title)
        except HeyGenHTTPError as e:
            if e.code != 404 or attempt == retries:
                raise
            print(f"[heygen_gen] {title} 생성 404 (시도 {attempt}/{retries}): {e.body}")
            time.sleep(10 * attempt)
            if attempt == retries - 1:
                asset_id = upload_image(image_path)
                print(f"[heygen_gen] {title} 이미지 재업로드 후 재시도")


def poll_video(video_id: str, max_tries=90, wait_sec=5) -> str:
    # 2026-09-12: 기존 200초(40*5) 예산으로는 HeyGen이 평소보다 느려질 때 완료 전에
    # 타임아웃되어(RuntimeError) 파이프라인 전체가 크래시하고 영상이 유실됐음. 450초(90*5)로 상향.
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
    req = lambda: urlreq.Request(url)
    out_path.write_bytes(_urlopen_with_retry(req, 60, f"다운로드 {out_path.name}"))


# 2026-10-08: female 낮 편(QipaoOn_Ko4) 인트로가 "…아직도 손으로"에서 끊기고 "하시나요?"가
# 빠진 채 발행됨. 코드에는 자르는 곳이 없고, HeyGen이 받은 훅 클립 자체가 2.74초로 대사보다
# 짧았다(대사 글자 20자 → 초당 7.3자; 정상 발행분 5편은 초당 4.8~5.6자). 그래서 내려받은 클립
# 길이를 대사 글자 수와 비교해, 비정상적으로 짧으면(끝부분 잘림) 그 클립만 한 번 다시 만든다.
MAX_CHARS_PER_SEC = 6.5


def _speech_chars(text: str) -> int:
    return len(re.findall(r"[가-힣A-Za-z0-9]", text))


def _clip_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _clip_cut_short(path: Path, script: str) -> tuple[bool, float, float]:
    """(잘림 의심 여부, 실제 길이, 최소 기대 길이)"""
    need = _speech_chars(script) / MAX_CHARS_PER_SEC
    try:
        dur = _clip_duration(path)
    except Exception as e:  # noqa: BLE001 — 길이를 못 재면 검사 생략(발행은 막지 않음)
        print(f"[heygen_gen] {path.name} 길이 측정 실패, 잘림 검사 생략: {e}")
        return False, 0.0, need
    return dur < need, dur, need


def ensure_full_clip(out_path: Path, image_path: Path, asset_id: str, script: str, voice_id: str, title: str) -> None:
    cut, dur, need = _clip_cut_short(out_path, script)
    if not cut:
        return
    print(f"[heygen_gen] ⚠ {title} 영상이 대사보다 짧음({dur:.2f}초 < 최소 {need:.2f}초) — 끝부분 잘림 의심, 한 번 다시 생성")
    vid = create_video_with_retry(image_path, asset_id, script, voice_id, f"{title}-retry")
    download(poll_video(vid), out_path)
    cut, dur, need = _clip_cut_short(out_path, script)
    if cut:
        print(f"[heygen_gen] ⚠ {title} 재생성도 짧음({dur:.2f}초 < {need:.2f}초) — 그대로 진행(대사 끝이 잘렸을 수 있음)")
    else:
        print(f"[heygen_gen] {title} 재생성 정상({dur:.2f}초)")


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

    단, 노트북이 화면에 나오는 사진은 후보에서 아예 제외 — LG그램15(노트북) 리뷰용으로
    찍은 사진들이라 그 상품일 때만 맞고, 상품은 매번 랜덤으로 바뀌는데(공기청정기,
    로봇청소기 등) 노트북이 보이면 상품과 안 맞아서 어색하다는 피드백으로 제외함.
    파일명에 "laptop"이 없어도 실제로는 노트북이 나오는 사진(예: "sitting_at_desk")이
    있어서, 파일명 필터만으론 못 잡고 직접 이미지를 확인해서 찾은 목록으로 제외함 —
    새 캐릭터 시트를 추가할 땐 이 목록도 다시 확인할 것.
    """
    EXCLUDE_LAPTOP_VISIBLE = {"person_sitting_at_desk_202608261740.jpeg"}
    files = sorted(
        f for f in char_dir.glob("*.jpeg")
        if "laptop" not in f.name.lower() and f.name.lower() not in EXCLUDE_LAPTOP_VISIBLE
    )
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

    hook_vid_id = create_video_with_retry(hook_img, hook_asset, script_data["hook_speech"], voice_id, "auto-hook")
    cta_vid_id = create_video_with_retry(cta_img, cta_asset, script_data["cta_speech"], voice_id, "auto-cta")

    hook_url = poll_video(hook_vid_id)
    download(hook_url, out_dir / "hook.mp4")
    print("훅 영상 다운로드 완료")

    cta_url = poll_video(cta_vid_id)
    download(cta_url, out_dir / "cta.mp4")
    print("CTA 영상 다운로드 완료")

    ensure_full_clip(out_dir / "hook.mp4", hook_img, hook_asset, script_data["hook_speech"], voice_id, "auto-hook")
    ensure_full_clip(out_dir / "cta.mp4", cta_img, cta_asset, script_data["cta_speech"], voice_id, "auto-cta")


if __name__ == "__main__":
    main()
