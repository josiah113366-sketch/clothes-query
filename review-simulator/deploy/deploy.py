"""이미지를 빌드해 ECR 에 올리고 새 태스크 정의 리비전을 등록한다 (2026-10-18 sim/review-ecs).

    python deploy/deploy.py --dry-run          # 무엇을 할지만 출력
    python deploy/deploy.py                    # 빌드 → ECR push → 리비전 등록
    python deploy/deploy.py --tag 0.2.0-abc1234 --skip-build   # 이미 올린 이미지로 리비전만 다시 등록

순서
  1. 이미지 태그 = <버전>-<커밋 7자리>. 커밋 안 한 변경이 있으면 -dirty<시각>을 붙인다.
     ECR 은 같은 태그 덮어쓰기를 막아 두었으므로(IMMUTABLE) 태그만 보면 어떤 코드인지 알 수 있다.
  2. docker build (review-simulator/ 폴더, linux/amd64) → ECR 로그인 → docker push
  3. 새 리비전 등록. 이미지만 바뀌고 실행 비율(REVIEW_RATE) 등은 이전 리비전 값을 그대로 쓴다.
  4. 스케줄이 켜져 있으면 스케줄도 새 리비전으로 바꾼다.

필요한 것: Docker Desktop, .local/seeds.jsonl (rsim seeds 로 만든 말투 예시. 이미지에 들어간다),
AWS 로그인(aws login / aws configure sso). 버전은 src/rsim/__init__.py, 바뀐 내용은 CHANGELOG.md 에 적는다.
"""

from __future__ import annotations

import argparse
import base64
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from aws_common import follow_new_revision, image_tag_of, load_config, register_revision, session

ROOT = Path(__file__).resolve().parent.parent  # review-simulator/


def read_version(root: Path = ROOT) -> str:
    """src/rsim/__init__.py 의 __version__ (rsim 을 import 하지 않고 읽는다)."""
    text = (root / "src/rsim/__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("src/rsim/__init__.py 에서 __version__ 을 찾지 못했습니다")
    return m.group(1)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def make_tag(version: str, commit: str, dirty: bool, now: datetime | None = None) -> str:
    tag = f"{version}-{commit}"
    if dirty:
        tag += f"-dirty{(now or datetime.now(UTC)).strftime('%Y%m%d%H%M')}"
    return tag


def current_tag() -> str:
    commit = _git("rev-parse", "--short=7", "HEAD")
    # review-simulator/ 아래 변경만 본다 (다른 폴더 작업 중이어도 이미지 내용과는 무관)
    dirty = bool(_git("status", "--porcelain", "--", "."))
    return make_tag(read_version(), commit, dirty)


def image_exists(ecr, repo_name: str, tag: str) -> bool:
    try:
        ecr.describe_images(repositoryName=repo_name, imageIds=[{"imageTag": tag}])
        return True
    except ecr.exceptions.ImageNotFoundException:
        return False


def docker(*args: str, stdin: str | None = None) -> None:
    print("$ docker", " ".join(args))
    subprocess.run(["docker", *args], cwd=ROOT, input=stdin, text=True, check=True)


def ecr_login(ecr, registry: str) -> None:
    """ECR 로그인. 비밀번호는 표준입력으로만 넘긴다(화면·명령줄에 안 남게)."""
    data = ecr.get_authorization_token()["authorizationData"][0]
    user, password = base64.b64decode(data["authorizationToken"]).decode().split(":", 1)
    docker("login", "--username", user, "--password-stdin", registry, stdin=password)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--tag", help="이미지 태그 (기본: <버전>-<커밋>)")
    ap.add_argument(
        "--skip-build", action="store_true", help="빌드·push 없이 이미 올린 --tag 로 등록만"
    )
    ap.add_argument("--dry-run", action="store_true", help="실행하지 않고 계획만 출력")
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    sess = session(args.region)
    cfg = load_config(sess)
    repo_url = cfg["ecr_repository_url"]
    registry, repo_name = repo_url.split("/", 1)
    tag = args.tag or current_tag()
    image = f"{repo_url}:{tag}"
    ecr = sess.client("ecr")
    exists = image_exists(ecr, repo_name, tag)

    print(f"이미지: {repo_name}:{tag} ({'ECR 에 있음' if exists else '새로 올림'})")
    if args.dry_run:
        print("--dry-run: 빌드·등록하지 않았습니다")
        return

    if args.skip_build:
        if not exists:
            raise SystemExit(f"ECR 에 {tag} 이미지가 없습니다. --skip-build 없이 실행하세요.")
    else:
        if exists:
            raise SystemExit(
                f"ECR 에 {tag} 이 이미 있습니다(태그 덮어쓰기 금지). 코드를 바꿨다면 커밋하거나,"
                " 같은 이미지로 다시 등록만 하려면 --skip-build 를 쓰세요."
            )
        if not (ROOT / ".local/seeds.jsonl").exists():
            raise SystemExit(
                ".local/seeds.jsonl 이 없습니다. 먼저 rsim seeds 로 만드세요(이미지에 들어감)."
            )
        docker("build", "--platform", "linux/amd64", "-t", image, ".")
        ecr_login(ecr, registry)
        docker("push", image)

    ecs = sess.client("ecs")
    td = register_revision(ecs, cfg, image=image)
    print(f"태스크 정의 등록: {td['family']}:{td['revision']} (이미지 {image_tag_of(td)})")
    if follow_new_revision(sess, cfg, td["taskDefinitionArn"]):
        print("스케줄이 켜져 있어 다음 예약 실행부터 이 리비전을 씁니다")
    else:
        print("스케줄은 꺼져 있습니다. 한 번 돌려 보려면: python deploy/onoff.py once --fake")


if __name__ == "__main__":
    main()
