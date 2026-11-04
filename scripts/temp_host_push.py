"""shopping-paradise-media 임시 호스팅 저장소로의 git push 재시도.

2026-11-04: GitHub Git Operations 장애(09:49Z~) 중 페이스북·쓰레드 영상 push가
`remote rejected (Internal Server Error)`로 한 번에 실패해 그대로 미게시됨.
push는 force push(같은 내용 덮어쓰기)라 여러 번 시도해도 부작용이 없다.
"""
import subprocess
import time
from pathlib import Path

RETRY_WAITS = (30, 60, 120)


def push_with_retry(repo_path: Path) -> None:
    cmd = ["git", "-C", str(repo_path), "push", "--force", "origin", "HEAD:main"]
    for attempt, wait in enumerate((*RETRY_WAITS, None), start=1):
        result = subprocess.run(cmd)
        if result.returncode == 0:
            return
        if wait is None:
            raise subprocess.CalledProcessError(result.returncode, cmd)
        print(f"  [temp_host_push] push 실패(exit {result.returncode}), {wait}초 후 재시도 "
              f"({attempt}/{len(RETRY_WAITS)})", flush=True)
        time.sleep(wait)
