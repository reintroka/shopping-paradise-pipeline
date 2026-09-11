# -*- coding: utf-8 -*-
"""쿠팡 상품 정지사진을 Seedance 2-mini(kie.ai) image-to-video로 4초 회전영상으로
바꾼다 (2026-09-11 도입, 사용자 요청 — 반응 저조한 크래시줌 정지이미지 대신 실제 모션).

절대 예외를 던지지 않고 성공/실패를 exit code로만 알린다. run_pipeline.py가 이걸
soft_step으로 감싸서, 실패(크레딧 소진/네트워크/컨텐츠필터/타임아웃 등 무엇이든)해도
product_video_raw.mp4가 안 만들어질 뿐 발행 자체는 막히지 않고 기존 정지이미지+
크래시줌 경로로 조용히 폴백한다(assemble_video._build_product_video_cell 참고).

API 필드명 주의(직접 검증함, 2026-09-10 세션): 이미지는 반드시 first_frame_url이며
`image`가 아니다 — `image`로 넣으면 에러 없이 조용히 text-to-video로 돌아가 버려서
전혀 엉뚱한 제품이 나온다. generate_audio를 명시적으로 false로 안 주면 가끔
"Content security audit did not pass"로 실패한다(오디오 저작권 오탐).

3개 카테고리(노트북/커피머신/스킨케어병)로 스트레스테스트해서 제품 정체성 드리프트
없음을 확인했다. 같은 테스트에서 Runway Gen-4 Turbo는 회전 도중 다른 브랜드 제품으로
바뀌는 사고가 있어 제외했고, Seedance 2-mini만 쓴다.
"""
import argparse
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.kie.ai/api/v1"
CREATE_TASK_URL = f"{API_BASE}/jobs/createTask"
RECORD_INFO_URL = f"{API_BASE}/jobs/recordInfo"

PROMPT = (
    "the exact same product shown in the reference image slowly rotates on a "
    "turntable, soft studio light sweep, subtle smooth camera motion, plain "
    "background, e-commerce product shot, keep product design, colors, "
    "proportions and any printed text or logo exactly identical to the "
    "reference image, no added text, no watermark"
)

POLL_INTERVAL_S = 8
# 2026-09-11: CCR 루틴 자체 timeout kill 전례(심리학 채널에서 겪음)가 있어서 너무
# 오래 기다리지 않게 상한을 둠 — 실측상 대부분 60~150초 안에 끝났음(3회 테스트로 확인).
MAX_WAIT_S = 180


def _request_json(url, headers, method="GET", payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def generate(product_image_path: Path, out_path: Path) -> bool:
    key = os.environ.get("KIE_API_KEY")
    if not key:
        print("[generate_product_video] KIE_API_KEY 미설정, 정지이미지로 폴백")
        return False

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    mime = mimetypes.guess_type(str(product_image_path))[0] or "image/jpeg"
    b64 = base64.b64encode(product_image_path.read_bytes()).decode()
    data_uri = f"data:{mime};base64,{b64}"

    payload = {
        "model": "bytedance/seedance-2-mini",
        "input": {
            "prompt": PROMPT,
            "first_frame_url": data_uri,
            "duration": 4,
            "resolution": "720p",
            "generate_audio": False,
        },
    }
    try:
        resp = _request_json(CREATE_TASK_URL, headers, method="POST", payload=payload, timeout=60)
        if not isinstance(resp.get("data"), dict):
            print(f"[generate_product_video] 작업 생성 실패: code={resp.get('code')} msg={resp.get('msg')}")
            return False
        task_id = resp["data"]["taskId"]
    except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as e:
        print(f"[generate_product_video] 작업 생성 실패: {e}")
        return False

    waited = 0
    while waited < MAX_WAIT_S:
        time.sleep(POLL_INTERVAL_S)
        waited += POLL_INTERVAL_S
        try:
            info = _request_json(f"{RECORD_INFO_URL}?taskId={task_id}", headers, timeout=30)
            data = info["data"]
            if not isinstance(data, dict):
                print(f"[generate_product_video] 상태조회 실패(재시도 대기): code={info.get('code')} msg={info.get('msg')}")
                continue
        except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as e:
            print(f"[generate_product_video] 상태조회 실패(재시도 대기): {e}")
            continue

        state = data.get("state")
        if state == "success":
            try:
                result = json.loads(data["resultJson"])
                video_url = result["resultUrls"][0]
                # urlretrieve는 User-Agent를 안 보내서 결과 CDN(tempfile.aiquickdraw.com)이
                # 403으로 막음(실측 확인, 2026-09-11) — 브라우저처럼 UA를 붙여 직접 요청한다.
                dl_req = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(dl_req, timeout=60) as resp, open(out_path, "wb") as f:
                    f.write(resp.read())
            except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError, OSError) as e:
                print(f"[generate_product_video] 결과 다운로드 실패: {e}")
                return False
            print(f"[generate_product_video] 성공 ({waited}초 소요): {out_path}")
            return True
        if state in ("fail", "failed"):
            print(f"[generate_product_video] 생성 실패: {data.get('failMsg')}")
            return False
        # state == "waiting" / "generating" 등이면 계속 폴링

    print(f"[generate_product_video] {MAX_WAIT_S}초 타임아웃, 정지이미지로 폴백")
    return False


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    ok = generate(Path(args.image), Path(args.out))
    raise SystemExit(0 if ok else 1)
