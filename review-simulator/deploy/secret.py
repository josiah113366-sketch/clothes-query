"""Bedrock API 키를 Secrets Manager 에 넣거나 바꾼다 (2026-10-18 sim/review-ecs).

    python deploy/secret.py              # 키를 화면에 안 보이게 입력 (붙여넣기 가능)
    python deploy/secret.py --from-env   # review-simulator/.env 의 AWS_BEARER_TOKEN_BEDROCK 값을 그대로 올림
    python deploy/secret.py --check      # 값이 들어 있는지만 확인 (값은 보여 주지 않음)

secret 자체는 Terraform 이 만들고(값 없음), 값만 여기서 넣는다. 키를 바꾸면 다음에 시작하는 태스크부터 새 키를 쓴다.
키 값은 출력·로그에 남기지 않는다. 확인용으로 길이와 버전 ID 만 보여 준다.
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from aws_common import SECRET_ENV_NAME, load_config, session


def read_env_file(path: Path) -> str:
    """.env 에서 AWS_BEARER_TOKEN_BEDROCK 한 줄만 읽는다(다른 값은 보지 않음)."""
    if not path.exists():
        raise SystemExit(f"{path} 이 없습니다")
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == SECRET_ENV_NAME:
            return value.strip().strip('"').strip("'")
    return ""


def has_value(sm, secret_arn: str) -> bool:
    versions = sm.list_secret_version_ids(SecretId=secret_arn)["Versions"]
    return any("AWSCURRENT" in v.get("VersionStages", []) for v in versions)


def put_key(sm, secret_arn: str, key: str) -> str:
    if not key or any(c.isspace() for c in key):
        raise SystemExit("키가 비어 있거나 공백이 들어 있습니다. 다시 확인하세요.")
    return sm.put_secret_value(SecretId=secret_arn, SecretString=key)["VersionId"]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--from-env", action="store_true", help=".env 의 AWS_BEARER_TOKEN_BEDROCK 를 올린다"
    )
    ap.add_argument("--env-file", type=Path, default=Path(".env"))
    ap.add_argument("--check", action="store_true", help="값이 들어 있는지만 확인")
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    sess = session(args.region)
    cfg = load_config(sess)
    sm = sess.client("secretsmanager")
    if args.check:
        print("Bedrock API 키:", "들어 있음" if has_value(sm, cfg["secret_arn"]) else "비어 있음")
        return

    if args.from_env:
        key = read_env_file(args.env_file) or os.getenv(SECRET_ENV_NAME, "")
    else:
        key = getpass.getpass("Bedrock API 키 (입력은 화면에 보이지 않습니다): ").strip()
    version = put_key(sm, cfg["secret_arn"], key)
    print(f"Bedrock API 키 저장 완료 (길이 {len(key)}자, 버전 {version[:8]}…)")


if __name__ == "__main__":
    main()
