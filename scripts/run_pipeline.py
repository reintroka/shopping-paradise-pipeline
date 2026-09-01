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
  8. X 포스트 (post_x, 상품 이미지 첨부 + 403 시 문구 변형 1회 재시도) — 실패해도 계속 진행(부가 기능)
  8.5. 인스타그램 Reels 발행 (post_instagram, GitHub Pages 임시 호스팅 경유) — 실패해도 계속 진행
  8.6. 틱톡 받은편지함(초안) 전달 (post_tiktok, 앱 심사 전이라 자동 공개발행 불가 —
       사람이 앱에서 최종 게시해야 함) — 실패해도 계속 진행
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
import post_instagram  # noqa: E402
import post_tiktok  # noqa: E402
import post_comment  # noqa: E402
import update_link_page  # noqa: E402
import shorts_log  # noqa: E402
import compile_longform  # noqa: E402
import notify_telegram  # noqa: E402


def run(cmd, **kw):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def run_captured(cmd):
    """soft_step으로 감싸는 부가 스텝(X 포스트, 유튜브 댓글)에서만 쓴다.

    2026-08-30: run()은 stdout/stderr를 캡처하지 않아서, 실패 시 soft_step_results에
    쌓이는 메시지가 "Command '[...]' returned non-zero exit status 1." 뿐이었다 —
    post_x.py가 실제 X API 에러 바디(403/401 사유 등)를 stdout에 자세히 찍어줘도
    CalledProcessError.__str__()엔 안 담기니 텔레그램 알림에도, 여기서도 진짜 원인이
    한 번도 보이지 않았다(트위터 실패가 반복돼도 원인을 특정 못 하던 문제의 근본 원인).
    출력을 캡처해 실패 시 예외 메시지에 꼬리 부분을 포함시킨다."""
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (result.stdout or "") + (result.stderr or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if result.returncode != 0:
        raise RuntimeError(f"exit {result.returncode}: {output[-1500:].strip()}")
    return result


def push_with_retry(repo_root: Path, max_tries: int = 3) -> None:
    """2026-08-28: 처음엔 female-noon/male-evening 두 루틴의 non-fast-forward 경합이라고
    추측하고 단순 `git push` 재시도로 고쳤었는데, 실제 클라우드 루틴 실행 로그
    (RemoteTrigger get_run_log)를 직접 열어보니 진짜 원인은 달랐다: 이 CCR 샌드박스가
    레포를 **detached HEAD**로 클론해서 `git push`가 애초에 "fatal: You are not
    currently on a branch"로 실패하고 있었다(non-fast-forward가 아니라 로컬에 붙어있는
    브랜치 자체가 없는 문제라 fetch+rebase만으로는 안 고쳐짐). `git push origin
    HEAD:main`은 로컬이 브랜치에 붙어있든 detached든 상관없이 현재 HEAD 커밋을
    origin의 main으로 밀어넣으므로 이 문제를 근본적으로 피해간다. origin이 그 사이
    앞서나간 경우(진짜 non-fast-forward)에는 fetch+rebase 후 재시도한다."""
    for attempt in range(1, max_tries + 1):
        try:
            run(["git", "-C", str(repo_root), "push", "origin", "HEAD:main"])
            return
        except subprocess.CalledProcessError as e:
            if attempt == max_tries:
                raise
            print(f"[push_with_retry] push 실패(시도 {attempt}/{max_tries}): {e} — fetch+rebase 후 재시도")
            run(["git", "-C", str(repo_root), "fetch", "origin"])
            try:
                run(["git", "-C", str(repo_root), "rebase", "origin/main"])
            except subprocess.CalledProcessError:
                # 2026-09-01: 코어디웹에서 실제로 겪은 사고 - 다른 프로세스(예: female-noon/
                # male-evening 두 루틴)가 같은 상태파일을 동시에 건드려 진짜 콘텐츠 충돌이
                # 나면 rebase가 충돌 마커만 남기고 죽고, 다음 실행이 그 마커를 그대로 읽어
                # 상태파일이 통째로 깨지는 연쇄사고로 이어질 수 있다. rebase를 즉시 abort하고
                # merge로 한 번 더 시도해 저장소를 깨진 상태로 방치하지 않는다.
                print("[push_with_retry] rebase 충돌 — abort 후 merge로 재시도")
                subprocess.run(["git", "-C", str(repo_root), "rebase", "--abort"])
                try:
                    run(["git", "-C", str(repo_root), "-c", "user.email=bot@shopping-paradise.local",
                         "-c", "user.name=shopping-paradise-bot", "merge", "origin/main", "--no-edit"])
                except subprocess.CalledProcessError:
                    subprocess.run(["git", "-C", str(repo_root), "merge", "--abort"])
                    raise


soft_step_results = []
uploaded_video_url = None  # 2026-08-28: 업로드 성공 이후(9~13단계) 실패 시 텔레그램 메시지가
# "영상 발행 안 됨"이라고 잘못 말하지 않도록, 업로드 성공 여부를 최상위 except에서도 알 수 있게 기록.


def soft_step(name, fn):
    """부가 기능 스텝: 실패해도 파이프라인 전체를 막지 않는다.

    fn()이 문자열을 반환하면 텔레그램 요약에 "성공" 대신 그 문자열을 그대로 쓴다
    (예: 롱폼 컴파일처럼 "성공"만으로는 실제 무슨 일이 있었는지 알 수 없는 단계용).
    """
    try:
        note = fn()
        soft_step_results.append((name, True, note if isinstance(note, str) else None))
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
    global uploaded_video_url
    uploaded_video_url = video_info["url"]

    # 8. X 포스트 (부가) — 2026-08-27: 쿠팡 상품 이미지 첨부 추가
    soft_step("X 포스트", lambda: run_captured([
        "python3", str(HERE / "post_x.py"),
        "--text", script_data["x_post"], "--image", str(product_image_path),
    ]))

    # 8.5. 인스타그램 Reels 발행 (부가) — IG_USER_ID/IG_ACCESS_TOKEN 미설정 시
    # post_instagram.py가 KeyError로 죽고 soft_step이 그걸 잡아 로그만 남긴다
    # (계정 연결 전까지는 파이프라인 전체에 영향 없음).
    ig_out_path = work_dir / "instagram_result.json"
    soft_step("인스타그램 Reels", lambda: run_captured([
        "python3", str(HERE / "post_instagram.py"),
        "--video", str(final_video), "--caption", script_data["x_post"], "--out", str(ig_out_path),
    ]))

    # 8.6. 틱톡 받은편지함(초안) 전달 (부가) — 앱 심사 전이라 API로 바로 공개
    # 발행은 불가, 계정 소유자가 틱톡 앱 알림에서 직접 게시해야 최종 발행됨.
    tiktok_out_path = work_dir / "tiktok_result.json"
    soft_step("틱톡 초안 전달", lambda: run_captured([
        "python3", str(HERE / "post_tiktok.py"),
        "--video", str(final_video), "--caption-hint", script_data["x_post"], "--out", str(tiktok_out_path),
    ]))

    # 9. 유튜브 댓글 (부가, 재시도 포함)
    comment_text = (
        f"영상에서 소개한 {product['productName'][:20]}, 여기서 바로 확인하세요 \U0001F449 {coupang_url}"
    )
    soft_step("유튜브 댓글", lambda: run_captured([
        "python3", str(HERE / "post_comment.py"),
        "--video-id", video_id, "--text", comment_text,
    ]))

    # 10. 링크 페이지 업데이트 (부가)
    soft_step("링크 페이지 업데이트", lambda: update_link_page.add_card(
        product["productName"][:20], f"{product['productPrice']:,}원대", coupang_url, script_data["hook_speech"],
    ))

    # 11. 발행 기록 추가 (롱폼 자동 컴파일 판단용)
    # 2026-09-01: specs 추가 — 롱폼 딥다이브 나레이션(compile_longform.py)이 스펙
    # 정보를 재사용해 더 구체적인 코멘트를 생성할 수 있게 함.
    # 2026-09-01 추가: product_image(쿠팡 원본 상품사진 URL)도 저장 — 롱폼 딥다이브
    # 배경이 영상 프레임 캡처 대신 실제 상품사진을 build_graphics와 동일한 금테+그림자+
    # 반사 처리로 예쁘게 보여줄 수 있게 함(사용자 요청: "제품 이미지 가져와서 멋지게").
    shorts_log.append_entry(
        args.character, product["productName"][:20], product["productPrice"],
        video_id, video_info["url"], coupang_url,
        product_image=product["productImage"],
        specs=[
            {"title": script_data["spec1_title"], "body": script_data["spec1_body"]},
            {"title": script_data["spec2_title"], "body": script_data["spec2_body"]},
            {"title": script_data["spec3_title"], "body": script_data["spec3_body"]},
        ],
    )

    # 12. 3일치(6개) 쌓였으면 롱폼 자동 제작+업로드
    # 2026-08-28: 숏폼 소싱/중복 문제 안정화 전까지 사용자 지시로 잠시 중단했었음.
    # 2026-09-01: pick_product.py 유사도 dedup + push_with_retry(detached HEAD) 수정 이후
    # 숏폼이 며칠간 안정적으로 발행되는 걸 확인, 사용자 확인 후 재개.
    def _compile_longform_step():
        pending_before = len([e for e in shorts_log.load_log() if not e.get("compiled_in")])
        result = compile_longform.check_and_compile()
        if result:
            return f"롱폼 완성! {result['url']}"
        return f"대기 중 ({pending_before}/6)"

    soft_step("롱폼 자동 컴파일", _compile_longform_step)

    # 13. used_products.json + shorts_log.json + character_image_history.json
    # (+longform_counter.json, 있으면) 커밋 (핵심 - 중복 방지를 위해 반드시 반영).
    # longform_counter.json/character_image_history.json은 첫 실행 전까지는 존재하지
    # 않을 수 있으므로, 존재하는 파일만 add해야 "pathspec did not match" 에러로 이
    # 필수 스텝 전체가 죽는 걸 피할 수 있다.
    trackable = [
        f for f in ("used_products.json", "shorts_log.json", "longform_counter.json", "character_image_history.json", "x_post_history.json")
        if (REPO_ROOT / f).exists()
    ]
    run(["git", "-C", str(REPO_ROOT), "add", *trackable])
    run(["git", "-C", str(REPO_ROOT), "-c", "user.email=bot@shopping-paradise.local",
         "-c", "user.name=shopping-paradise-bot", "commit", "-m",
         f"Mark product {product['productId']} as used, log short {video_id}"])
    push_with_retry(REPO_ROOT)

    print(f"\n✅ 파이프라인 완료: {video_info['url']}")

    # 14. 텔레그램 요약 알림 (부가 단계 실패가 있어도 여기 다 담아서 항상 전송)
    lines = [
        f"[쇼핑의천국] {args.character} 발행 완료",
        f"상품: {product['productName'][:20]} ({product['productPrice']:,}원대)",
        f"영상: {video_info['url']}",
    ]
    for name, ok, note in soft_step_results:
        if not ok:
            lines.append(f"- {name}: 실패 ({note})")
        elif note:
            lines.append(f"- {name}: {note}")
        else:
            lines.append(f"- {name}: 성공")
    notify("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if uploaded_video_url:
            notify(
                f"[쇼핑의천국] 영상은 발행됐지만 후처리 단계 실패\n"
                f"영상: {uploaded_video_url}\n{e}"
            )
        else:
            notify(f"[쇼핑의천국] 파이프라인 실패 (영상 발행 안 됨)\n{e}")
        raise
