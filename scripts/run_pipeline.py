"""쇼핑의천국 숏츠 완전자동화 파이프라인 오케스트레이터.

사용법: python run_pipeline.py --character female|male

순서:
  1. 쿠팡 상품 선정 (pick_product) — 실패하면 중단
  2. Gemini 대본 생성 (gen_script) — 실패하면 중단
  2.5. 부업실험실 링크 페이지 카드 등록 (update_link_page) — 실패해도 계속 진행. 여기서
       확정된 순번(product_rank)을 화면 번호 배지(4번)와 릴스 캡션(8.5번)에 씀
       (2026-09-10, 원래 10번이었던 걸 앞당김)
  3. 상품 이미지 다운로드
  4. 그래픽 생성 (build_graphics)
  4.5. 상품 AI영상 생성 (generate_product_video, Seedance 2-mini) — 실패해도 계속 진행,
       assemble_video.py가 정지이미지로 자동 폴백 (2026-09-11 도입)
  5. HeyGen 훅/CTA 영상 생성 (heygen_gen) — 여기서부터 비용 발생
  5.5. 스펙 설명 나레이션 생성 (google_tts, Google Cloud TTS — 2026-08-27 헤이젠에서 교체)
  6. ffmpeg 최종 조립 (assemble_video)
  7. 유튜브 공개 업로드 (upload_youtube) — 실패하면 중단(핵심 산출물)
  8. X 포스트 (post_x, 상품 이미지 첨부 + 403 시 문구 변형 1회 재시도) — 실패해도 계속 진행(부가 기능)
  8.5. 인스타그램 Reels 발행 (post_instagram, GitHub Pages 임시 호스팅 경유) — 실패해도 계속 진행
  8.55. 페이스북 페이지 발행 (post_facebook, 인스타그램과 동일 캡션) — 실패해도 계속 진행
  8.56. 쓰레드 발행 (post_threads, 인스타그램과 동일 캡션) — THREADS_USER_ID/
        THREADS_ACCESS_TOKEN 클라우드 환경변수가 없으면 비활성화로 간주해 조용히
        건너뜀(2026-09-18, 신규 계정이라 며칠간 자동 발행 보류 — 사용자 지시)
  8.6. 틱톡 받은편지함(초안) 전달 (post_tiktok, 앱 심사 전이라 자동 공개발행 불가 —
       사람이 앱에서 최종 게시해야 함) — 실패해도 계속 진행
  9. 유튜브 댓글 홍보 (post_comment, 재시도 포함) — 실패해도 계속 진행
  10. (링크 페이지 업데이트는 2.5번으로 이동함)
  11. shorts_log.json에 이번 발행 기록 추가
  12. 숏츠가 6개(3일치) 쌓였으면 롱폼으로 이어붙여 별도 업로드 (compile_longform) — 실패해도 계속 진행
  13. used_products.json + shorts_log.json(+longform_counter.json) 변경사항 커밋+푸시 (파이프라인 레포 자체)
  14. 텔레그램으로 실행 요약 알림 (2026-08-27 도입, 성공/실패 무관 항상 전송)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PENDING_PATH = REPO_ROOT / "pending_release.json"
KST = timezone(timedelta(hours=9))
# 2026-09-20: 신규 쓰레드 계정은 프로필 외부 링크가 조용히 지워지는 제약이 있어(추정 —
# 메타의 신규 계정 스팸 방지, 인스타/페이스북엔 없는 문제) "프로필 링크에서 확인하세요"
# 문구가 쓰레드에서는 무용지물이 된다. 쓰레드(+X)는 게시물 본문의 URL을 자동으로
# 하이퍼링크 처리하므로, 쓰레드용 캡션에만 실제 링크를 텍스트로 덧붙인다(사용자 제안).
LINK_PAGE_URL = "https://reintroka.github.io/sidejoblab-links"
# gen_script.py의 append_disclosure()와 동일한 문구 — 쓰레드 캡션을 재조립할 때
# (링크를 맨 앞에 두려고) 기존 위치의 고지 문구를 떼어내 다시 맨 앞으로 옮기는 데 쓴다.
COUPANG_DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

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
    script_path = work_dir / "script.json"

    # 2026-09-18: run_teaser.py(2시간 전 쓰레드 텍스트 티저)가 미리 상품을 골라
    # pending_release.json에 저장해뒀으면 그걸 그대로 이어받아 쓴다 — 같은 상품을
    # 두 번 고르지 않기 위함. 오늘 날짜 것이 아니거나 파일/키가 없으면(티저를
    # 아직 안 켰거나, 티저 단계가 실패했거나) 기존처럼 새로 고른다 — 자가 치유,
    # 이 스텝이 없다고 파이프라인 전체가 막히면 안 됨.
    pending_used = False
    if PENDING_PATH.exists():
        try:
            pending_all = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
            pending = pending_all.get(args.character)
            if pending and pending.get("date") == datetime.now(KST).strftime("%Y-%m-%d"):
                product = pending["product"]
                script_data = pending["script_data"]
                product_rank = pending.get("product_rank")
                pending_used = True
                # heygen_gen.py 등 뒷단계가 --script-json 경로로 파일을 읽으므로,
                # 이어받은 script_data도 새로 생성했을 때와 같은 경로에 실제로 써둬야
                # 한다 (2026-09-18 실 발행에서 이 파일이 없어 script_path가 끝내
                # 할당되지 않는 UnboundLocalError로 파이프라인 전체가 실패했음).
                script_path.write_text(
                    json.dumps(script_data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"[run_pipeline] run_teaser.py가 예약해둔 상품을 이어받음: {product['productName'][:20]}")
        except Exception as e:
            print(f"[경고] pending_release.json 읽기 실패 (새로 고름): {e}")

    if not pending_used:
        # 1. 상품 선정
        product_path = work_dir / "product.json"
        run(["python3", str(HERE / "pick_product.py"), "--out", str(product_path)])
        product = json.loads(product_path.read_text(encoding="utf-8"))

        # 2. 대본 생성
        run(["python3", str(HERE / "gen_script.py"), "--product-json", str(product_path), "--out", str(script_path)])
        script_data = json.loads(script_path.read_text(encoding="utf-8"))

    coupang_url = product.get("shortUrl") or product["productUrl"]

    if not pending_used:
        # 2.5. 링크 페이지 카드 등록 (부가) — 2026-09-10: 원래 10번 단계(인스타 발행 이후)였던 걸
        # 여기로 앞당김. 화면 번호 배지(build_graphics)와 릴스 캡션에 "몇 번 상품"인지 적어
        # 나중에 링크 페이지에서 검색하기 쉽게 하려면, 실제로 카드가 등록되어 확정된 순번을
        # 영상/캡션을 만들기 *전에* 알아야 하기 때문. add_card()가 실패해도(권한/네트워크)
        # product_rank가 None으로 남을 뿐 파이프라인은 계속 진행되고, 배지/캡션 문구는
        # 조건부로 생략된다(아래 build_graphics 호출, 8.5 인스타 단계 참고).
        product_rank = None
        try:
            product_rank = update_link_page.add_card(
                product["productName"][:20], f"{product['productPrice']:,}원대", coupang_url,
                script_data["hook_speech"], image_url=product["productImage"],
            )
            soft_step_results.append(("링크 페이지 업데이트", True, f"{product_rank}번"))
        except Exception as e:
            print(f"[경고] 링크 페이지 업데이트 실패 (파이프라인은 계속 진행): {e}")
            soft_step_results.append(("링크 페이지 업데이트", False, str(e)))
    else:
        soft_step_results.append(("링크 페이지 업데이트", True, f"{product_rank}번 (티저에서 이미 등록)"))

    # 3. 상품 이미지 다운로드 — 쿠팡 CDN이 User-Agent 없는 요청(기본 Python-urllib UA)을
    # 403으로 차단하는 걸 실제로 겪음(다른 채널들의 Pexels/NASA/aiquickdraw.com CDN도
    # 동일 문제였음, [[project_shopping_paradise_seedance_reliability_2026-09-11]] 참고).
    product_image_path = work_dir / "product.jpg"
    req = urllib.request.Request(product["productImage"], headers={"User-Agent": "Mozilla/5.0"})
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
        rank=product_rank,
    )

    # 4.5. 상품 AI영상 생성 (부가, 2026-09-11 도입) — 정지사진 대신 Seedance 2-mini로
    # 실제 회전하는 4초 클립을 만들어 반응률을 높이려는 시도(사용자 요청, 클립당 약
    # $0.164). 실패해도(크레딧/네트워크/타임아웃 등 무엇이든) product_video_raw.mp4가
    # 안 만들어질 뿐이고, assemble_video.py가 그 파일 존재여부로 자동 판단해 기존
    # 정지이미지+크래시줌 경로로 조용히 폴백하므로 발행 자체는 절대 막히지 않는다.
    #
    # 2026-09-13: 9/12·9/13 연속 3/3 전패(재시도+이미지 리사이즈 이후에도 Task ID조차
    # 안 찍힘)로 한때 이 단계를 비활성화했었음. 오늘의 심리학의 runway_motion.py가
    # 같은 kie.ai를 클라우드에서 매번 성공시키는 걸 보고 원인을 다시 봄 — 그쪽은
    # 이미지를 먼저 업로드해서 URL만 넘기는데, 이 스크립트는 base64를 jobs/createTask
    # 요청 본문에 직접 실었었음. generate_product_video.py를 같은 업로드→URL참조
    # 방식으로 수정하고([[project_shopping_paradise_seedance_reliability_2026-09-11]]
    # 참고) 재활성화 — 다음 실 발행에서 성공 여부 확인 필요.
    product_video_path = work_dir / "product_video_raw.mp4"
    soft_step("상품 AI영상 생성", lambda: run_captured([
        "python3", str(HERE / "generate_product_video.py"),
        "--image", str(product_image_path), "--out", str(product_video_path),
    ]))

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
    tags = upload_youtube.build_tags(product)
    upload_cmd = [
        "python3", str(HERE / "upload_youtube.py"),
        "--video", str(final_video),
        "--title", script_data["youtube_title"],
        "--description", script_data["youtube_description_intro"],
        "--tags", ",".join(tags),
        "--coupang-url", coupang_url,
        "--out", str(video_id_path),
    ]
    if product_rank is not None:
        upload_cmd += ["--rank", str(product_rank)]
    run(upload_cmd)
    video_info = json.loads(video_id_path.read_text(encoding="utf-8"))
    video_id = video_info["video_id"]
    global uploaded_video_url
    uploaded_video_url = video_info["url"]
    upload_youtube.backup_product_image(video_id, product_image_path)

    # 8. X 포스트 (부가) — 2026-08-27: 쿠팡 상품 이미지 첨부 추가
    # 2026-09-10: x_post는 gen_script.py에서 이미 280자 예산에 맞춰 트림된 값이라
    # (X_POST_MAX_LEN) 뒤에 뭘 더 붙이면 넘칠 수 있음 — 과거 이 채널에서 X용 280자컷
    # 로직이 다른 캡션으로 새어들어간 사고가 있었어서(틱톡 캡션 관련) 여기선 짧은
    # 태그만 쓰고, 넘치면 본문 쪽을 줄여서라도 280자를 반드시 지킨다.
    x_post_text = script_data["x_post"]
    if product_rank is not None:
        rank_tag = f" [No.{product_rank}]"
        if len(x_post_text) + len(rank_tag) <= 280:
            x_post_text = f"{x_post_text}{rank_tag}"
        else:
            x_post_text = f"{x_post_text[:280 - len(rank_tag) - 1].rstrip()}…{rank_tag}"
    soft_step("X 포스트", lambda: run_captured([
        "python3", str(HERE / "post_x.py"),
        "--text", x_post_text, "--image", str(product_image_path),
    ]))

    # 8.5. 인스타그램 Reels 발행 (부가) — IG_USER_ID/IG_ACCESS_TOKEN 미설정 시
    # post_instagram.py가 KeyError로 죽고 soft_step이 그걸 잡아 로그만 남긴다
    # (계정 연결 전까지는 파이프라인 전체에 영향 없음).
    ig_out_path = work_dir / "instagram_result.json"
    ig_caption = script_data.get("ig_caption") or script_data["x_post"]
    # 2026-09-10: 나중에 부업실험실 링크 페이지에서 "몇 번 상품이었더라" 검색해서 찾을 수
    # 있도록 순번을 캡션에 명시(사용자 요청 — "번호를 강조해서 올려"). 끝에 덧붙이면
    # 다들 안 읽는 꼬리말이 되니, 맨 앞에 둬서 가장 먼저 보이게 함. product_rank가
    # None이면(링크 페이지 업데이트 실패) 문구를 아예 생략 — 없는 번호를 안내 금지.
    if product_rank is not None:
        ig_caption = f"\U0001F50E [No.{product_rank}] 이 번호로 프로필 링크에서 다시 찾을 수 있어요\n\n{ig_caption}"
    soft_step("인스타그램 Reels", lambda: run_captured([
        "python3", str(HERE / "post_instagram.py"),
        "--video", str(final_video), "--caption", ig_caption, "--out", str(ig_out_path),
    ]))

    # 2026-09-19: ig_caption의 "댓글에 '가격'..." 문구는 인스타그램 댓글 자동응답(DM)에만
    # 연결된 것 — 페이스북 페이지/쓰레드/틱톡엔 그 자동응답이 없어 그대로 내보내면 실제로
    # 안 되는 DM 안내가 섞여 나간다(coredlab의 saju-master/route.ts 등도 이 이유로 인스타
    # 캡션에만 DM 안내를 붙이고 페이스북/쓰레드 캡션은 별도로 구성함 — 같은 패턴).
    # 인스타 외 모든 플랫폼은 이 한 줄만 제거한 공통 캡션을 쓴다.
    no_dm_caption = re.sub(
        r"\n?댓글에 '가격'이라고 남겨주시면 DM으로 바로 알려드려요!\n?", "\n", ig_caption,
    ).strip()

    # 8.55. 페이스북 페이지 발행 (부가) — FACEBOOK_ACCESS_TOKEN 미설정 시
    # post_facebook.py가 KeyError로 죽고 soft_step이 그걸 잡아 로그만 남긴다.
    fb_out_path = work_dir / "facebook_result.json"
    soft_step("페이스북 페이지", lambda: run_captured([
        "python3", str(HERE / "post_facebook.py"),
        "--video", str(final_video), "--caption", no_dm_caption, "--out", str(fb_out_path),
    ]))

    # 8.56. 쓰레드 영상 발행 (부가) — THREADS_USER_ID/THREADS_ACCESS_TOKEN 클라우드
    # 환경변수가 둘 다 등록돼 있을 때만 시도한다. 2026-09-18: 쓰레드 계정을 막 만든
    # 상태라 며칠간 지켜본 뒤 켜기로 함(사용자 지시) — 두 환경변수를 등록하지 않는
    # 한 조용히 건너뛰어 soft_step_results/텔레그램 알림에 매번 "실패"로 쌓이지
    # 않게 한다. 계정이 안정됐다고 판단되면 클라우드 환경변수만 채우면 코드 변경
    # 없이 바로 켜진다.
    #
    # 2026-09-18 추가: 텍스트 티저는 run_teaser.py(2시간 전), 카드뉴스는
    # run_cards.py(2시간 후)로 분리했다 — 사용자가 쓰레드를 직접 운영해보니
    # "텍스트로 궁금하게 → 영상 공개 → 카드뉴스로 정리" 3단계로 하루 안에 나눠
    # 발행하는 게 좋겠다는 아이디어(사용자 지시). 이 스텝(run_pipeline.py)은 이제
    # 영상만 올린다 — shorts_log.append_entry에 hook_speech/cta_speech/rank를
    # 같이 남겨서 2시간 후 run_cards.py가 이 실행을 다시 돌리지 않고도 그 값들로
    # 카드뉴스를 재구성할 수 있게 한다(아래 11번 참고).
    if os.environ.get("THREADS_USER_ID") and os.environ.get("THREADS_ACCESS_TOKEN"):
        threads_video_out = work_dir / "threads_video_result.json"
        # 링크를 맨 앞에 둔다 — _truncate_caption()이 500자 초과 시 뒤쪽부터 자르므로,
        # 끝에 붙이면 캡션이 조금만 길어도 잘려나간다(쓰레드용 캡션은 실제로 500자를
        # 자주 넘김). 쿠팡 고지 문구도 항상 맨 앞이어야 하므로(gen_script.py 원칙과
        # 동일), no_dm_caption 중간에 있던 고지 문구를 떼어내 링크보다 먼저 오도록
        # 재배치한다 — 링크 때문에 고지 문구가 둘째 문단으로 밀려나지 않게.
        threads_caption = f"{COUPANG_DISCLOSURE}\n\n🔗 {LINK_PAGE_URL}\n\n" + (
            no_dm_caption.replace(f"{COUPANG_DISCLOSURE}\n\n", "", 1)
        )
        soft_step("쓰레드 영상", lambda: run_captured([
            "python3", str(HERE / "post_threads.py"), "--mode", "video",
            "--video", str(final_video), "--caption", threads_caption, "--out", str(threads_video_out),
        ]))
    else:
        print("[run_pipeline] 쓰레드 영상 발행 건너뜀 (THREADS_USER_ID/THREADS_ACCESS_TOKEN 미설정 — 비활성화 상태)")

    # 8.6. 틱톡 받은편지함(초안) 전달 (부가) — 앱 심사 전이라 API로 바로 공개
    # 발행은 불가, 계정 소유자가 틱톡 앱 알림에서 직접 게시해야 최종 발행됨.
    # x_post는 X(트위터) 280자 제한에 맞춰 gen_script.py에서 강제로 잘린 값이라 틱톡에
    # 쓰면 문장이 중간에 잘린다. 틱톡 캡션 제한은 2200자로 여유가 있으니, 컷 없는
    # no_dm_caption(위에서 이미 DM 안내를 제거한 공통 캡션)을 그대로 쓴다(2026-09-10).
    tiktok_caption = no_dm_caption
    tiktok_out_path = work_dir / "tiktok_result.json"
    tiktok_ok = soft_step("틱톡 초안 전달", lambda: run_captured([
        "python3", str(HERE / "post_tiktok.py"),
        "--video", str(final_video), "--caption-hint", tiktok_caption, "--out", str(tiktok_out_path),
    ]))
    # 틱톡은 API로 캡션을 못 넣어 앱에서 직접 붙여넣어야 하므로, 요약 메시지에 섞이지 않게
    # tiktok_caption(고지 문구+설명+해시태그가 다 포함된, 잘리지 않은 완성 캡션 — DM 안내만
    # 제거) 자체를 단독 메시지로 보내 그대로 복사해 붙여넣을 수 있게 한다.
    if tiktok_ok and tiktok_caption:
        notify(tiktok_caption)

    # 9. 유튜브 댓글 (부가, 재시도 포함)
    rank_prefix = f"[No.{product_rank}] " if product_rank is not None else ""
    comment_text = (
        f"{rank_prefix}영상에서 소개한 {product['productName'][:20]}, 여기서 바로 확인하세요 \U0001F449 {coupang_url}"
    )
    soft_step("유튜브 댓글", lambda: run_captured([
        "python3", str(HERE / "post_comment.py"),
        "--video-id", video_id, "--text", comment_text,
    ]))

    # 10. (2026-09-10: 링크 페이지 업데이트는 2.5번으로 옮김 — 화면 번호 배지/릴스 캡션에
    # 순번을 쓰려면 영상 만들기 전에 확정돼 있어야 하기 때문. 아래 11번에서 번호 찾기 쉽게)

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
        hook_speech=script_data["hook_speech"], cta_speech=script_data["cta_speech"], rank=product_rank,
        product_name_full=product["productName"], ig_caption=ig_caption,
    )

    # 12. 3일치(6개) 쌓였으면 롱폼 자동 제작+업로드
    # 2026-08-28: 숏폼 소싱/중복 문제 안정화 전까지 사용자 지시로 잠시 중단했었음.
    # 2026-09-01: pick_product.py 유사도 dedup + push_with_retry(detached HEAD) 수정 이후
    # 숏폼이 며칠간 안정적으로 발행되는 걸 확인, 사용자 확인 후 재개.
    def _compile_longform_step():
        # 2026-09-19: 예전엔 check_and_compile() 호출 전에 pending 개수를 미리 세어
        # 메시지에 썼는데, 시도 도중 다운로드 실패로 항목 하나가 SKIPPED_UNAVAILABLE로
        # 빠지면(compile_longform._gather_batch) 배치가 6개 밑으로 줄어 롱폼이 안
        # 만들어지는데도 "대기 중 (6/6)"처럼 다 찬 것으로 보이는 메시지가 나갔다(사용자가
        # 실제 발행 로그에서 발견해 질문). 시도 "후" 개수를 다시 세어 실제 상태를 보여준다.
        result = compile_longform.check_and_compile()
        if result:
            return f"롱폼 완성! {result['url']}"
        pending_after = len([e for e in shorts_log.load_log() if not e.get("compiled_in")])
        return f"대기 중 ({pending_after}/6)"

    soft_step("롱폼 자동 컴파일", _compile_longform_step)

    # 2026-09-18: run_teaser.py가 예약해둔 상품을 이어받아 썼다면(pending_used), 이번
    # 실행으로 소비됐으니 pending_release.json에서 이 character 키를 지운다 — 안
    # 지우면 다음 날 같은 슬롯 실행이 오늘 날짜 체크에 걸려 자연히 무시되긴 하지만,
    # 혹시 같은 날 재시도되는 경우 오래된(이미 쓴) 상품을 또 이어받는 걸 방지.
    if pending_used and PENDING_PATH.exists():
        try:
            pending_all = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
            pending_all.pop(args.character, None)
            PENDING_PATH.write_text(json.dumps(pending_all, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[경고] pending_release.json 정리 실패 (무시하고 계속): {e}")

    # 13. used_products.json + shorts_log.json + character_image_history.json
    # (+longform_counter.json, 있으면) 커밋 (핵심 - 중복 방지를 위해 반드시 반영).
    # longform_counter.json/character_image_history.json은 첫 실행 전까지는 존재하지
    # 않을 수 있으므로, 존재하는 파일만 add해야 "pathspec did not match" 에러로 이
    # 필수 스텝 전체가 죽는 걸 피할 수 있다.
    trackable = [
        f for f in ("used_products.json", "shorts_log.json", "longform_counter.json",
                     "character_image_history.json", "x_post_history.json", "pending_release.json")
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
