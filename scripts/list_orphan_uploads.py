"""처리 완료가 아닌(빈 껍데기 의심) 업로드 목록 확인. 기본은 읽기 전용.

python3 scripts/list_orphan_uploads.py            # 목록만
python3 scripts/list_orphan_uploads.py --delete   # 목록의 영상 삭제
"""
import argparse

from googleapiclient.discovery import build

import upload_youtube

p = argparse.ArgumentParser()
p.add_argument("--delete", action="store_true")
args = p.parse_args()

youtube = build("youtube", "v3", credentials=upload_youtube.get_credentials())
orphans = upload_youtube.find_orphan_uploads(youtube, title=None)
print(f"처리 완료 아닌 영상 {len(orphans)}개")
for v in orphans:
    pd = v.get("processingDetails", {})
    print(f"  {v['id']} | {v['status'].get('uploadStatus')} | {v['status'].get('privacyStatus')} | "
          f"{pd.get('processingStatus')} | {v['snippet'].get('publishedAt')} | {v['snippet'].get('title')}")
    if args.delete:
        upload_youtube.execute_401_retry(lambda: youtube.videos().delete(id=v["id"]), "빈 영상 삭제")
        print("    → 삭제함")
