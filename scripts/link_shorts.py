"""비교 롱폼 ↔ 같은 상품군 쇼츠 자동 연결(2026-10-10 사용자 요청 "자동으로 해").

롱폼이 올라가면:
  1. shorts_log.json 에서 같은 상품군 쇼츠(최근 60일, 최대 8편)를 찾는다 — 주제 단어가 상품 원문 이름에 들어 있으면 같은 군.
  2. 각 쇼츠 설명란 맨 위에 "📺 ○○ 가격대별 6종 비교 👉 롱폼 링크"를 넣는다(이미 있으면 건너뜀).
  3. 각 쇼츠에 같은 내용의 댓글을 단다(쿠팡 링크 댓글과 별개).
  4. 롱폼 설명란 끝에 [관련 쇼츠] 링크를 붙인다.
  5. API로 안 되는 '관련 동영상' 지정·댓글 고정은 텔레그램으로 스튜디오 링크 목록을 보낸다.
유튜브 API: videos.list 1 + videos.update 50 + commentThreads.insert 50 단위/편 — 8편이면 약 900 단위(하루 한도 1만).
실패해도 롱폼 발행은 막지 않는다(호출부에서 예외를 삼킴).
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from post_comment import get_youtube, post_comment
from upload_youtube import execute_401_retry

REPO_ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
GENERIC = {"주방", "세트", "수납", "용품", "가성비", "대용량"}
MAX_SHORTS = 8
DAYS = 60


def _tokens(topic, queries):
    out = []
    for w in re.split(r"[·\s]+", topic) + list(queries or []):
        w = w.replace(" ", "")
        for g in ("세트", "가성비", "대용량"):
            w = w.replace(g, "") if len(w) > len(g) + 1 else w
        if len(w) >= 2 and w not in GENERIC and w not in out:
            out.append(w)
    return out


def related_shorts(topic, queries, log=None):
    log = log if log is not None else json.loads((REPO_ROOT / "shorts_log.json").read_text(encoding="utf-8"))
    toks = _tokens(topic, queries)
    since = (datetime.now(KST) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    hits = []
    for e in reversed(log):
        if not e.get("video_id") or (e.get("date") or "") < since:
            continue
        name = (e.get("product_name_full") or e.get("product_name") or "").replace(" ", "")
        if any(t in name for t in toks):
            hits.append(e)
        if len(hits) >= MAX_SHORTS:
            break
    return hits, toks


def _prepend_desc(yt, vid, line, marker):
    r = execute_401_retry(lambda: yt.videos().list(part="snippet", id=vid), "쇼츠 조회")
    items = r.get("items") or []
    if not items:
        return "없음"
    sn = items[0]["snippet"]
    desc = sn.get("description") or ""
    if marker in desc:
        return "이미 있음"
    body = {"id": vid, "snippet": {"title": sn["title"], "categoryId": sn.get("categoryId", "22"),
                                   "description": (line + "\n\n" + desc)[:4900], "tags": sn.get("tags") or []}}
    if sn.get("defaultLanguage"):
        body["snippet"]["defaultLanguage"] = sn["defaultLanguage"]
    execute_401_retry(lambda: yt.videos().update(part="snippet", body=body), "쇼츠 설명란 수정")
    return "추가"


def _append_longform_desc(yt, lf_id, shorts):
    r = execute_401_retry(lambda: yt.videos().list(part="snippet", id=lf_id), "롱폼 조회")
    items = r.get("items") or []
    if not items:
        return False
    sn = items[0]["snippet"]
    desc = sn.get("description") or ""
    if "[관련 쇼츠]" in desc:
        return False
    rows = "\n".join(f"- {(e.get('product_name') or '')[:24]} https://youtube.com/shorts/{e['video_id']}" for e in shorts)
    body = {"id": lf_id, "snippet": {"title": sn["title"], "categoryId": sn.get("categoryId", "22"),
                                     "description": (desc + "\n\n[관련 쇼츠]\n" + rows)[:4900], "tags": sn.get("tags") or []}}
    execute_401_retry(lambda: yt.videos().update(part="snippet", body=body), "롱폼 설명란 수정")
    return True


def link(topic, queries, lf_id, lf_title, notify=print):
    shorts, toks = related_shorts(topic, queries)
    if not shorts:
        print(f"[link] '{topic}' 관련 쇼츠 없음(찾은 단어: {toks})")
        return []
    url = f"https://youtu.be/{lf_id}"
    line = f"📺 {topic} 가격대별 6종 비교 영상 👉 {url}"
    yt = get_youtube()
    done = []
    for e in shorts:
        vid = e["video_id"]
        try:
            st = _prepend_desc(yt, vid, line, url)
            if st == "추가":
                post_comment(yt, vid, f"같은 종류 6개를 가격대별로 비교한 영상도 있어요 👇\n{lf_title}\n{url}")
            done.append((e, st))
            print(f"[link] {vid} {e.get('product_name', '')[:20]} — 설명란 {st}")
        except Exception as exc:  # noqa: BLE001
            print(f"[link] {vid} 실패(무시): {exc}")
    try:
        _append_longform_desc(yt, lf_id, [e for e, _ in done])
    except Exception as exc:  # noqa: BLE001
        print(f"[link] 롱폼 설명란 관련 쇼츠 추가 실패(무시): {exc}")
    if done:
        rows = "\n".join(f"• {e.get('product_name', '')[:20]} — https://studio.youtube.com/video/{e['video_id']}/edit" for e, _ in done)
        notify(f"🔗 [쇼핑의천국] 새 비교 롱폼과 같은 상품군 쇼츠 {len(done)}편에 설명란 링크·댓글을 자동으로 달았어요.\n"
               f"유튜브 API로 안 되는 2가지만 직접 해 주세요(1~2분): 각 쇼츠 스튜디오에서 ① '관련 동영상'에 이 롱폼 지정, "
               f"② 롱폼 링크 댓글 고정.\n롱폼: {url}\n{rows}")
    return [e["video_id"] for e, _ in done]


if __name__ == "__main__":
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--queries", default="")
    ap.add_argument("--video-id")
    ap.add_argument("--title", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    qs = [q for q in a.queries.split(",") if q]
    if a.dry:
        hs, toks = related_shorts(a.topic, qs)
        print(toks)
        for e in hs:
            print(e["date"], e["video_id"], e.get("product_name_full", e.get("product_name", ""))[:50])
    else:
        import notify_telegram
        link(a.topic, qs, a.video_id, a.title, notify_telegram.send)
