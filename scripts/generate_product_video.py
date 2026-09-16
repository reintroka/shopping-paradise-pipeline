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
import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

API_BASE = "https://api.kie.ai/api/v1"
CREATE_TASK_URL = f"{API_BASE}/jobs/createTask"
RECORD_INFO_URL = f"{API_BASE}/jobs/recordInfo"
UPLOAD_URL = "https://kieai.redpandaai.co/api/file-base64-upload"

# 2026-09-12: 실 발행 3/3 전패(매번 code=500 Server exception, kie.ai 로그엔
# Task ID조차 안 남음) 이후 도입. 쿠팡 원본 이미지는 리사이즈/압축 없이 그대로
# base64 인코딩해 JSON body에 실었는데, 원본이 큰 경우 게이트웨이 단에서
# 요청 자체가 거부될 가능성을 배제 못 해 안전하게 상한을 둠(사용자 로컬
# 수동테스트 이미지는 이 크기를 넘지 않았을 수 있음).
MAX_IMAGE_SIDE = 1280
JPEG_QUALITY = 88

# 같은 이유로 createTask 1회 실패를 바로 최종 실패로 처리하지 않고 짧게 재시도한다
# (일시적 5xx일 가능성 배제 못 함).
CREATE_TASK_MAX_ATTEMPTS = 3
CREATE_TASK_RETRY_DELAY_S = 5

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
# 2026-09-16: 180초는 너무 짧아서 실제로는 성공(211초, 919초 실측)한 작업까지
# 정지이미지로 버려지고 있었다 — kie.ai Logs에서 직접 확인(두 작업 다 status:success,
# 32.8 크레딧 정상 소모, 즉 이미 돈은 나갔는데 결과물만 버려짐). 업로드 URL을
# uuid4 기반 고유 파일명으로 바꿔(위 커밋) 느린 작업이 다른 실행에 덮어써지는
# 위험을 없앤 뒤 20분으로 상향 — 실측 최댓값(919초)보다 충분한 여유를 둠. 이
# 단계 자체는 soft_step으로 감싸여 있어 결국 타임아웃 나도 정지이미지 폴백으로
# 발행은 막히지 않지만, 20분을 다 쓰면 뒤따르는 HeyGen/조립/멀티플랫폼 발행
# 단계들의 세션 시간 예산을 많이 잡아먹을 수 있다는 점은 감수한 트레이드오프.
MAX_WAIT_S = 1200


def _request_json(url, headers, method="GET", payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _prepare_image_data_uri(path: Path) -> str:
    """원본 크기와 무관하게 긴 변 MAX_IMAGE_SIDE 이하로 리사이즈 + JPEG 재압축한다
    (게이트웨이 단 500 거부의 원인일 수 있는 큰 body를 예방)."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, MAX_IMAGE_SIDE / max(w, h))
        if scale < 1.0:
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=JPEG_QUALITY)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


def _upload_image(headers, data_uri: str, file_name: str) -> str:
    """2026-09-13: 오늘의 심리학의 runway_motion.py가 쓰는 것과 같은 방식 — 이미지를
    jobs/createTask 요청 본문에 직접 싣는 대신, 먼저 이 업로드 전용 엔드포인트로
    올려서 URL만 받아온다. 심리학 채널은 이 방식(업로드 후 URL참조)으로 클라우드
    루틴(CCR)에서도 매번 성공하는데, 쇼핑의천국은 jobs/createTask에 base64를
    직접 실어서 클라우드에서만 매번 code=500으로 거부당함
    ([[project_shopping_paradise_seedance_reliability_2026-09-11]]) — 큰 인라인
    payload 자체가 게이트웨이에 걸릴 가능성을 시험해보기 위한 변경."""
    # urlretrieve/urllib 기본 User-Agent(Python-urllib/x.y)를 kie.ai 업로드 게이트웨이가
    # 403으로 막는다(다운로드 단계에서 이미 확인한 것과 같은 패턴, 아래 참고) — 브라우저처럼
    # UA를 붙인다.
    resp = _request_json(
        UPLOAD_URL, {**headers, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST",
        payload={"base64Data": data_uri, "uploadPath": "shopping-paradise-product-video", "fileName": file_name},
        timeout=60,
    )
    if not resp.get("success"):
        raise RuntimeError(f"kie.ai 이미지 업로드 실패: {resp.get('msg')}")
    data = resp.get("data") or {}
    file_url = data.get("fileUrl") or data.get("downloadUrl")
    if not file_url:
        raise RuntimeError(f"kie.ai 업로드 응답에 fileUrl/downloadUrl이 없음: {resp}")
    return file_url


def _create_task(headers, payload):
    """일시적 5xx일 가능성을 배제 못 해 짧게 재시도(같은 요청 그대로)한다."""
    last_err = "알 수 없는 오류"
    for attempt in range(1, CREATE_TASK_MAX_ATTEMPTS + 1):
        try:
            resp = _request_json(CREATE_TASK_URL, headers, method="POST", payload=payload, timeout=60)
            if isinstance(resp.get("data"), dict) and "taskId" in resp["data"]:
                return resp["data"]["taskId"], None
            last_err = f"code={resp.get('code')} msg={resp.get('msg')}"
        except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as e:
            last_err = str(e)
        if attempt < CREATE_TASK_MAX_ATTEMPTS:
            print(
                f"[generate_product_video] 작업 생성 실패({attempt}/{CREATE_TASK_MAX_ATTEMPTS}): "
                f"{last_err}, {CREATE_TASK_RETRY_DELAY_S}초 후 재시도"
            )
            time.sleep(CREATE_TASK_RETRY_DELAY_S)
    return None, last_err


def generate(product_image_path: Path, out_path: Path) -> bool:
    key = os.environ.get("KIE_API_KEY")
    if not key:
        print("[generate_product_video] KIE_API_KEY 미설정, 정지이미지로 폴백")
        return False

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        data_uri = _prepare_image_data_uri(product_image_path)
    except Exception as e:  # PIL이 지원 못 하는 포맷 등 예상 못 한 실패도 폴백으로 흡수
        print(f"[generate_product_video] 이미지 준비 실패: {e}")
        return False

    # 2026-09-16: run_pipeline.py가 로컬 파일을 항상 work_dir/product.jpg로 저장해서
    # (work_dir는 실행마다 다르지만 .name은 매번 "product.jpg"로 동일) 업로드 파일명도
    # 매번 똑같았다 — uploadPath+fileName이 고정이라 원격 URL이 고정되고, 그 결과
    # 모든 실행(남/여 슬롯 등)이 같은 URL을 덮어쓰는 공유 슬롯이 됐다. 폴링 대기가
    # 최대 180초(그마저 실측상 최대 900초 넘게도 걸림)라 그 사이 다른 실행이 같은
    # URL에 새 이미지를 덮어쓰면, 먼저 시작한 느린 작업이 kie.ai에서 실제 처리될
    # 시점엔 완전히 다른 상품 이미지를 참조하게 된다(실제 사고: 청소도구 세트
    # 요청했는데 영상엔 공기청정기가 나옴). 요청마다 고유한 파일명을 써서 이 공유
    # 슬롯 자체를 없앤다.
    unique_file_name = f"{uuid.uuid4().hex}_{product_image_path.name}"
    try:
        image_url = _upload_image(headers, data_uri, unique_file_name)
    except (urllib.error.URLError, RuntimeError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as e:
        print(f"[generate_product_video] 이미지 업로드 실패: {e}")
        return False

    payload = {
        "model": "bytedance/seedance-2-mini",
        "input": {
            "prompt": PROMPT,
            "first_frame_url": image_url,
            "duration": 4,
            "resolution": "720p",
            "generate_audio": False,
        },
    }
    task_id, err = _create_task(headers, payload)
    if task_id is None:
        print(f"[generate_product_video] 작업 생성 실패(재시도 {CREATE_TASK_MAX_ATTEMPTS}회 모두 실패): {err}")
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
