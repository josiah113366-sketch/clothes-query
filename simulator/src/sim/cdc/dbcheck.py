"""DB 쪽 확인: 복제 슬롯, publication, member_id 집합, 샘플 대조. 회원 값은 출력하지 않는다."""

from dataclasses import dataclass

import psycopg

from sim.cdc import params
from sim.common.db import safe_db_errors


@dataclass(frozen=True)
class SlotInfo:
    plugin: str
    active: bool
    lag_bytes: int  # 아직 Debezium이 확인하지 않은 WAL 크기


def slot_info(conn: psycopg.Connection) -> SlotInfo | None:
    """슬롯이 없으면 None."""
    with safe_db_errors():
        row = conn.execute(
            "SELECT plugin, active, "
            "coalesce(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn), 0)::bigint "
            "FROM pg_replication_slots WHERE slot_name = %s",
            (params.SLOT_NAME,),
        ).fetchone()
    return None if row is None else SlotInfo(str(row[0]), bool(row[1]), int(row[2]))


def publication_tables(conn: psycopg.Connection) -> list[str]:
    """publication에 들어 있는 테이블 (schema.table). publication이 없으면 빈 목록."""
    with safe_db_errors():
        rows = conn.execute(
            "SELECT schemaname || '.' || tablename FROM pg_publication_tables "
            "WHERE pubname = %s ORDER BY 1",
            (params.PUBLICATION_NAME,),
        ).fetchall()
    return [str(r[0]) for r in rows]


def member_count(conn: psycopg.Connection) -> int:
    with safe_db_errors():
        row = conn.execute("SELECT count(*) FROM members").fetchone()
    return int(row[0]) if row else 0


def drop_slot(conn: psycopg.Connection) -> bool:
    """슬롯을 지운다. 지웠으면 True, 없었으면 False. 아직 쓰는 중이면 psycopg 오류(55006)."""
    if slot_info(conn) is None:
        return False
    conn.execute("SELECT pg_drop_replication_slot(%s)", (params.SLOT_NAME,))
    return True


def drop_publication(conn: psycopg.Connection) -> None:
    conn.execute(f"DROP PUBLICATION IF EXISTS {params.PUBLICATION_NAME}")
