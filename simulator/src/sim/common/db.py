"""PostgreSQL 연결과 오류 가리기.

PostgreSQL 오류 메시지에는 행 내용이 들어 있다 (예: "Key (email)=(...) already exists").
그래서 psycopg.Error는 여기서 잡아 예외 종류, sqlstate, 제약 이름만 남긴다.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


class SafeDatabaseError(RuntimeError):
    """PII가 없는 DB 오류. 메시지는 describe_db_error가 만든 값만 담는다."""


def describe_db_error(error: psycopg.Error) -> str:
    """예외 종류, sqlstate, 제약 이름만 돌려준다. str(error)와 diag.message_detail은 쓰지 않는다."""
    parts = [type(error).__name__, f"sqlstate={error.sqlstate}"]
    constraint = error.diag.constraint_name
    if constraint:
        parts.append(f"constraint={constraint}")
    return " ".join(parts)


@contextmanager
def safe_db_errors() -> Iterator[None]:
    try:
        yield
    except psycopg.Error as error:
        raise SafeDatabaseError(describe_db_error(error)) from None


def describe_target(database_url: str) -> str:
    """접속 대상을 '호스트:포트/DB이름'으로만 보여 준다 (사용자·비밀번호 제외)."""
    info = conninfo_to_dict(database_url)
    return f"{info.get('host', 'localhost')}:{info.get('port', 5432)}/{info.get('dbname', '')}"


def target_host(database_url: str) -> str:
    return str(conninfo_to_dict(database_url).get("host", "localhost"))


def connect(database_url: str, schema: str | None = None) -> psycopg.Connection:
    """연결한다. schema를 주면 search_path를 그 스키마로 바꾼다 (통합 테스트용)."""
    with safe_db_errors():
        conn = psycopg.connect(database_url)
        if schema:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.commit()
    return conn
