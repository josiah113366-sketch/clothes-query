"""Bedrock API 키를 Secrets Manager 에 넣거나 바꾼다 (2026-10-18 sim/review-ecs).

    python deploy/secret.py              # 키를 화면에 안 보이게 입력 (붙여넣기 가능)
    python deploy/secret.py --from-env   # review-simulator/.env 의 AWS_BEARER_TOKEN_BEDROCK 값을 그대로 올림
    python deploy/secret.py --check      # 값이 들어 있는지만 확인 (값은 보여 주지 않음)
    python deploy/secret.py --orders-db             # RDS 접속 주소(ORDERS_DATABASE_URL)를 안 보이게 입력 (2026-10-21)
    python deploy/secret.py --orders-db --from-env  # .env 의 ORDERS_DATABASE_URL 값을 올림
    python deploy/secret.py --orders-db --check     # RDS 접속 주소가 들어 있는지만 확인

RDS 접속 주소는 읽기 전용 계정으로 만든다: postgresql://계정:비밀번호@RDS주소:5432/DB이름
로컬 .env 에 port-forward 주소(localhost)를 넣어 두었다면 그 값은 ECS 에서 쓸 수 없다. RDS 실제 주소로 넣는다.

secret 자체는 Terraform 이 만들고(값 없음), 값만 여기서 넣는다. 키를 바꾸면 다음에 시작하는 태스크부터 새 키를 쓴다.
키 값은 출력·로그에 남기지 않는다. 확인용으로 길이와 버전 ID 만 보여 준다.
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from aws_common import ORDERS_DB_ENV_NAME, SECRET_ENV_NAME, load_config, session

# ECS 태스크 안에서 RDS 로 붙을 수 없는 호스트 (로컬 port-forward 주소를 잘못 올리는 것을 막는다)
LOCAL_HOST_MARKERS = ("@localhost", "@127.0.0.1", "host=localhost", "host=127.0.0.1")


def read_env_file(path: Path, name: str = SECRET_ENV_NAME) -> str:
    """.env 에서 name 한 줄만 읽는다(다른 값은 보지 않음). 기본은 AWS_BEARER_TOKEN_BEDROCK."""
    if not path.exists():
        raise SystemExit(f"{path} 이 없습니다")
    for line in path.read_text(encoding="utf-8").splitlines():
        key_name, sep, value = line.partition("=")
        if sep and key_name.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def has_value(sm, secret_arn: str) -> bool:
    versions = sm.list_secret_version_ids(SecretId=secret_arn)["Versions"]
    return any("AWSCURRENT" in v.get("VersionStages", []) for v in versions)


def put_key(sm, secret_arn: str, key: str) -> str:
    if not key or any(c.isspace() for c in key):
        raise SystemExit("키가 비어 있거나 공백이 들어 있습니다. 다시 확인하세요.")
    return sm.put_secret_value(SecretId=secret_arn, SecretString=key)["VersionId"]


def check_db_url(url: str) -> None:
    """RDS 접속 주소 형식만 본다. 값은 출력하지 않는다."""
    if not url or any(c.isspace() for c in url):
        raise SystemExit("접속 주소가 비어 있거나 공백이 들어 있습니다. 다시 확인하세요.")
    if not url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("접속 주소는 postgresql:// 로 시작해야 합니다")
    if any(m in url for m in LOCAL_HOST_MARKERS):
        raise SystemExit(
            "localhost 주소는 ECS 에서 RDS 로 붙지 못합니다(로컬 port-forward 용). RDS 실제 주소를 넣으세요."
        )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--from-env", action="store_true", help=".env 의 AWS_BEARER_TOKEN_BEDROCK 를 올린다"
    )
    ap.add_argument("--env-file", type=Path, default=Path(".env"))
    ap.add_argument("--check", action="store_true", help="값이 들어 있는지만 확인")
    ap.add_argument(
        "--orders-db",
        action="store_true",
        help="Bedrock 키 대신 RDS 접속 주소(ORDERS_DATABASE_URL) secret 을 다룬다",
    )
    ap.add_argument("--region", default=None)
    args = ap.parse_args(argv)

    sess = session(args.region)
    cfg = load_config(sess)
    sm = sess.client("secretsmanager")
    if args.orders_db:
        arn = cfg.get("orders_db_secret_arn")
        if not arn:
            raise SystemExit(
                "설정에 orders_db_secret_arn 이 없습니다. infra/stacks/ecs-review-simulator 를 다시 apply 하세요."
            )
        if args.check:
            print("RDS 접속 주소:", "들어 있음" if has_value(sm, arn) else "비어 있음")
            return
        if args.from_env:
            url = read_env_file(args.env_file, ORDERS_DB_ENV_NAME) or os.getenv(
                ORDERS_DB_ENV_NAME, ""
            )
        else:
            url = getpass.getpass("RDS 접속 주소 (입력은 화면에 보이지 않습니다): ").strip()
        check_db_url(url)
        version = sm.put_secret_value(SecretId=arn, SecretString=url)["VersionId"]
        print(f"RDS 접속 주소 저장 완료 (길이 {len(url)}자, 버전 {version[:8]}…)")
        return

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
