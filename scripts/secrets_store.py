"""shopping-paradise-secrets(비공개 저장소)에서 자동 갱신 토큰을 읽고/쓴다.

shopping-paradise-pipeline 저장소 자체는 public이라 시크릿을 절대 여기 커밋하면 안 된다
(2026-09-01, 사용자 지시로 인스타/틱톡 토큰이 만료 없이 자동 갱신되도록 만드는 과정에서
분리함). 대신 별도 private 저장소(shopping-paradise-secrets)에 토큰 상태를 저장하고,
매 실행마다 clone → 필요시 갱신 → push한다. 파일이 여러 개(instagram_token.json,
tiktok_token.json)라서 shopping-paradise-media처럼 매번 새 커밋 하나로 덮어쓰면 다른
파일이 지워지므로, 여기서는 기존 파일을 보존하는 일반 clone/commit/push(+ 충돌 시
fetch/rebase 재시도)를 쓴다 — 토큰 JSON은 용량이 작아 히스토리 누적이 문제되지 않는다.

각 파일의 최초 값(bootstrap)은 클라우드 환경 변수(IG_ACCESS_TOKEN, TIKTOK_REFRESH_TOKEN)에서
가져온다 — secrets 저장소에 아직 파일이 없을 때만 환경변수를 시드로 쓰고, 그 다음부터는
항상 이 저장소의 값을 우선한다(환경변수는 갱신되지 않으므로 시간이 지나면 낡은 값이 됨).
"""
import json
import subprocess
import tempfile
from pathlib import Path

SECRETS_REPO_URL = "https://github.com/reintroka/shopping-paradise-secrets.git"


def _run(cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def load(filename: str, bootstrap: dict) -> dict:
    """secrets 저장소에서 filename을 읽는다. 없으면 bootstrap 값을 그대로 반환."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _run(["git", "clone", SECRETS_REPO_URL, tmp])
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"secrets 저장소 clone 실패: {e.stderr}") from None
        path = Path(tmp) / filename
        if not path.exists():
            return dict(bootstrap)
        return json.loads(path.read_text(encoding="utf-8"))


def _push_with_retry(repo_dir: str, max_tries: int = 3) -> None:
    for attempt in range(1, max_tries + 1):
        try:
            _run(["git", "push", "origin", "HEAD:main"], cwd=repo_dir)
            return
        except subprocess.CalledProcessError:
            if attempt == max_tries:
                raise
            _run(["git", "fetch", "origin"], cwd=repo_dir)
            _run(["git", "rebase", "origin/main"], cwd=repo_dir)


def save(filename: str, data: dict) -> None:
    """secrets 저장소에서 filename만 갱신 후 커밋+푸시 (다른 파일은 그대로 보존)."""
    with tempfile.TemporaryDirectory() as tmp:
        _run(["git", "clone", SECRETS_REPO_URL, tmp])
        (Path(tmp) / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _run(["git", "add", filename], cwd=tmp)
        _run([
            "git", "-c", "user.email=bot@shopping-paradise.local",
            "-c", "user.name=shopping-paradise-bot", "commit", "-q", "-m", f"update {filename}",
        ], cwd=tmp)
        _push_with_retry(tmp)
