"""상품 시드 적재: 두 테이블이 비었는지 확인 → 한 트랜잭션에서 design → variant COPY → 커밋."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg

from sim.common.db import SafeDatabaseError, safe_db_errors
from sim.product import params, source


class TableNotEmptyError(RuntimeError):
    pass


class TableMissingError(RuntimeError):
    pass


def copy_sql(table: str) -> str:
    return f"COPY {table} ({', '.join(source.column_names(table))}) FROM STDIN"


@dataclass
class LoadSummary:
    """값(상품 이름 등)은 담지 않고 건수만 담는다."""

    mode: str
    source: str
    batch_size: int
    rows: dict[str, int] = field(default_factory=dict)
    columns: dict[str, list[str]] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def lines(self) -> list[str]:
        out = [f"모드: {self.mode}", f"원본: {self.source}"]
        for table, count in self.rows.items():
            out.append(f"{table}: {count:,}행, 컬럼 {len(self.columns[table])}개")
            out.append(f"  {', '.join(self.columns[table])}")
        if self.mode == "load":
            out.append(f"배치 크기: {self.batch_size:,}  소요 시간: {self.elapsed_seconds:.1f}초")
        return out


def ensure_tables_empty(conn: psycopg.Connection) -> None:
    """두 테이블 중 하나라도 행이 있으면 아무것도 넣지 않고 멈춘다."""
    for table in params.TABLES:
        try:
            with safe_db_errors():
                row = conn.execute(f"SELECT EXISTS (SELECT 1 FROM {table})").fetchone()
        except SafeDatabaseError as error:
            conn.rollback()
            if "sqlstate=42P01" in str(error):
                raise TableMissingError(
                    f"{table} 테이블이 없습니다. db/schema/003_product.sql을 먼저 적용하세요 "
                    "(simulator/README.md의 '상품 적재' 참고)."
                ) from None
            raise
        if row and row[0]:
            raise TableNotEmptyError(
                f"{table} 테이블이 비어 있지 않아 아무것도 넣지 않았습니다. "
                "로컬이면 `docker compose down -v` 후 다시 실행하세요. "
                "단 회원 데이터도 함께 지워지므로 주의하세요."
            )


def run_load(
    source_path: str,
    batch_size: int,
    conn: psycopg.Connection | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> LoadSummary:
    """conn이 None이면 파일 스키마와 행 수만 확인한다 (--dry-run, DB에 접속하지 않는다)."""
    started = time.monotonic()
    found = source.inspect_source(source_path)
    summary = LoadSummary(
        mode="dry-run" if conn is None else "load",
        source=source_path,
        batch_size=batch_size,
        rows={table: found[table].rows for table in params.TABLES},
        columns={table: source.column_names(table) for table in params.TABLES},
    )
    if conn is None:
        return summary

    ensure_tables_empty(conn)
    with safe_db_errors():
        try:
            for table in params.TABLES:
                done = 0
                with conn.cursor() as cur, cur.copy(copy_sql(table)) as copy:
                    for rows in source.iter_row_batches(found[table].parquet, table, batch_size):
                        for row in rows:
                            copy.write_row(row)
                        done += len(rows)
                        if progress:
                            progress(table, done, found[table].rows)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    summary.elapsed_seconds = round(time.monotonic() - started, 2)
    return summary
