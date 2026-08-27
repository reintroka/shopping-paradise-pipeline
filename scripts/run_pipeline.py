"""쇼핑의천국 숏츠 완전자동화 파이프라인 오케스트레이터.

사용법: python run_pipeline.py --character female|male

순서:
  1. 쿠팡 상품 선정 (pick_product) — 실패하면 중단
  2. Gemini 대본 생성 (gen_script) — 실패하면 중단
  3. 상품 이미지 다운로드
  4. 그래픽 생성 (build_graphics)
  5. HeyGen 훅/CTA 영상 생성 (heygen_gen) — 여기서부터 비용 발생
  5.5. 스펙 설명 나레이션 생성 (google_tts, Google Cloud TTS — 2026-08-27 헤이젠에서 교체)
  6. ffmpeg 최종 조립 (assemble_video)
  7. 유튜브 공개 업로드 (upload_youtube) — 실패하면 중단(핵심 산출물)
  8. X 포스트 (post_x) — 실패해도 계속 진행(부가 기능)
  9. 유튜브 댓글 홍보 (post_comment, 재시도 포함) — 실패해도 계속 진행
  10. 부업실험실 링크 페이지 업데이트 (update_link_page) — 실패해도 계속 진행
  11. shorts_log.json에 이번 발행 기록 추가
  12. 숏츠가 6개(3일치) 쌓였으면 롱폼으로 이어붙여 별도 업로드 (compile_longform) — 실패해도 계속 진행
  13. used_products.json + shorts_log.json(+longform_counter.json) 변경사항 커밋+푸시 (파이프라인 레포 자체)
  14. 텔레그램으로 실행 요약 알림 (2026-08-27 도입, 성공/실패 무관 항상 전송)
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

sys.path.insert(0, str(HERE))
import build_graphics  # noqa: E402
import heygen_gen  # noqa: E402
import google_tts  # noqa: E402
import assemble_video  # noqa: E402
import upload_youtube  # noqa: E402
import post_x  # noqa: E402
import post_comment  # noqa: E402
import update_link_page  # noqa: E402
import shorts_log  # noqa: E402
import compile_longform  # noqa: E402
import notify_telegram  # noqa: E402


def run(cmd, **kw):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


soft_step_results = []


def soft_step(name, fn):
    """부가 기능 스텝: 실패해도 파이프라인 전체를 막지 않는다. 텔레그램 요약용으로 결과 기록."""
    try:
        fn()
        soft_step_results.append((name, True, None))
        return True
    except Exception as e:
        print(f"[경고] {name} 실패 (파이프라인은 계속 진행): {e}")
        soft_step_results.append((name, False, str(e)))
        return False


def notify(text: str) -> None:
    """텔레그램 알림 전송 자체가 실패해도 파이프라인 결과에 영향을 주지 않게 감싼다."""
    try:
        notify_telegram.send(text)
    except Exception as e:
        print(f"[경고] 텔레그램 알림 전송 실패: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--character", choices=["female", "male"], required=True)
    args = p.parse_args()

    work_dir = REPO_ROOT / "work" / args.character
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. 상품 선정
    product_path = work_dir / "product.json"
    run(["python3", str(HERE / "pick_product.py"), "--out", str(product_path)])
    product = json.loads(product_path.read_text(encoding="utf-8"))

    # 2. 대본 생성
    script_path = work_dir / "script.json"
    run(["python3", str(HERE / "gen_script.py"), "--product-json", str(product_path), "--out", str(script_path)])
    script_data = json.loads(script_path.read_text(encoding="utf-8"))

    # 3. 상품 이미지 다운로드
    product_image_path = work_dir / "product.jpg"
    req = urllib.request.Request(product["productImage"])
    with urllib.request.urlopen(req, timeout=30) as resp:
        product_image_path.write_bytes(resp.read())

    # 4. 그래픽 생성
    build_graphics.build_all(
        work_dir,
        product["productName"][:20],
        f"{product['productPrice']:,}원대",
        product_image_path,
        (script_data["spec1_title"], script_data["spec1_body"]),
        (script_data["spec2_title"], script_data["spec2_body"]),
        (script_data["spec3_title"], script_data["spec3_body"]),
        script_data["hook_speech"],
        script_data["cta_speech"],
    )

    # 5. HeyGen 생성 (비용 발생 지점)
    char_dir = REPO_ROOT / "assets" / "characters" / args.character
    run([
        "python3", str(HERE / "heygen_gen.py"),
        "--character", args.character,
        "--char-dir", str(char_dir),
        "--script-json", str(script_path),
        "--out-dir", str(work_dir),
    ])

    # 5.5. 스펙 설명 나레이션 3개 (Google Cloud TTS, 스펙 카드 1개당 1개 — 컷 전환과 정확히 동기화하기 위함)
    for i in (1, 2, 3):
        google_tts.synthesize(script_data[f"narration_script{i}"], args.character, work_dir / f"narration{i}.mp3")
    print("나레이션 오디오 3개 생성 완료 (Google TTS)")

    # 6. 최종 조립
    final_video = work_dir / "final.mp4"
    assemble_video.assemble(work_dir, final_video)

    # 7. 유튜브 업로드 (필수)
    video_id_path = work_dir / "video_id.json"
    coupang_url = product.get("shortUrl") or product["productUrl"]
    run([
        "python3", str(HERE / "upload_youtube.py"),
        "--video", str(final_video),
        "--title", script_data["youtube_title"],
        "--description", script_data["youtube_description_intro"],
        "--tags", "쇼핑하울,제품추천,Shorts",
        "--coupang-url", coupang_url,
        "--out", str(video_id_path),
    ])
    video_info = json.loads(video_id_path.read_text(encoding="utf-8"))
    video_id = video_info["video_id"]

    # 8. X 포스트 (부가)
    soft_step("X 포스트", lambda: run(["python3", str(HERE / "post_x.py"), "--text", script_data["x_post"]]))

    # 9. 유튜브 댓글 (부가, 재시도 포함)
    comment_text = (
        f"영상에서 소개한 {product['productName'][:20]}, 여기서 바로 확인하세요 \U0001F449 {coupang_url}"
    )
    soft_step("유튜브 댓글", lambda: run([
        "python3", str(HERE / "post_comment.py"),
        "--video-id", video_id, "--text", comment_text,
    ]))

    # 10. 링크 페이지 업데이트 (부가)
    soft_step("링크 페이지 업데이트", lambda: update_link_page.add_card(
        product["productName"][:20], f"{product['productPrice']:,}원대", coupang_url, script_data["hook_speech"],
    ))

    # 11. 발행 기록 추가 (롱폼 자동 컴파일 판단용)
    shorts_log.append_entry(
        args.character, product["productName"][:20], product["productPrice"],
        video_id, video_info["url"], coupang_url,
    )

    # 12. 3일치(6개) 쌓였으면 롱폼 자동 제작+업로드 (부가 — 실패해도 숏츠 발행 자체는 이미 끝난 상태)
    soft_step("롱폼 자동 컴파일", compile_longform.check_and_compile)

    # 13. used_products.json + shorts_log.json(+longform_counter.json, 있으면) 커밋
    # (핵심 - 중복 방지를 위해 반드시 반영). longform_counter.json은 첫 롱폼이
    # 만들어지기 전까지는 존재하지 않으므로, 존재하는 파일만 add해야
    # "pathspec did not match" 에러로 이 필수 스텝 전체가 죽는 걸 피할 수 있다.
    trackable = [
        f for f in ("used_products.json", "shorts_log.json", "longform_counter.json")
        if (REPO_ROOT / f).exists()
    ]
    run(["git", "-C", str(REPO_ROOT), "add", *trackable])
    run(["git", "-C", str(REPO_ROOT), "-c", "user.email=bot@shopping-paradise.local",
         "-c", "user.name=shopping-paradise-bot", "commit", "-m",
         f"Mark product {product['productId']} as used, log short {video_id}"])
    run(["git", "-C", str(REPO_ROOT), "push"])

    print(f"\n✅ 파이프라인 완료: {video_info['url']}")

    # 14. 텔레그램 요약 알림 (부가 단계 실패가 있어도 여기 다 담아서 항상 전송)
    lines = [
        f"[쇼핑의천국] {args.character} 발행 완료",
        f"상품: {product['productName'][:20]} ({product['productPrice']:,}원대)",
        f"영상: {video_info['url']}",
    ]
    for name, ok, err in soft_step_results:
        lines.append(f"- {name}: {'성공' if ok else f'실패 ({err})'}")
    notify("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        notify(f"[쇼핑의천국] 파이프라인 실패 (영상 발행 안 됨)\n{e}")
        raise
