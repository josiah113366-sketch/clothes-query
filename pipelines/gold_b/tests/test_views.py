"""정리 뷰 SQL 파일(views/)이 설계 문서의 SQL과 같은지 확인한다.

설계 문서가 원본이고, 파일은 Athena에서 실행할 복사본이다. 둘 중 하나만 고치면 이 시험이 실패한다.
Athena에서 실제로 만들고 샘플로 결과를 확인하는 것은 권한이 생긴 뒤에 한다 (views/README.md).
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

HERE = Path(__file__).resolve().parent
VIEWS = HERE.parent / "views"
DESIGN = HERE.parents[2] / "docs" / "design" / "gold-b" / "README.md"
NAMES = ("payment_states", "payment_conflicts", "payment_attempts", "malformed_messages")


def design_sql() -> dict[str, str]:
    doc = DESIGN.read_text(encoding="utf-8")
    return {name: sql for sql, name in
            re.findall(r"```sql\n(CREATE OR REPLACE VIEW gold_b\.(\w+) AS\n.*?)```", doc, re.S)}


def file_sql(name: str) -> str:
    """파일 맨 위의 설명 주석 줄을 뺀 SQL."""
    lines = (VIEWS / f"{name}.sql").read_text(encoding="utf-8").splitlines(keepends=True)
    while lines and lines[0].startswith("--"):
        lines.pop(0)
    return "".join(lines)


def test_design_has_exactly_these_views():
    assert sorted(design_sql()) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_view_file_matches_design(name):
    assert file_sql(name) == design_sql()[name]


def test_malformed_messages_keeps_time_folders():
    """판정·조사 쿼리가 dt·hour 조건으로 그 폴더만 읽을 수 있게, 시간 폴더를 칸으로 내보내고 묶음 기준에도 넣는다."""
    sql = design_sql()["malformed_messages"]
    select, group_by = sql.split("FROM", 1)[0], sql.split("GROUP BY", 1)[1]
    for column in ("dt", "hour"):
        assert re.search(rf"\b{column}\b", select), column
        assert re.search(rf"\b{column}\b", group_by), column


def select_columns(sql: str) -> list[str]:
    """맨 바깥 SELECT의 칸 이름 (AS 뒤 이름 또는 칸 이름)."""
    select = sql.split("SELECT", 1)[1].rsplit("FROM", 1)[0]
    depth, parts, current = 0, [], ""
    for char in select:
        depth += char == "("
        depth -= char == ")"
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [re.split(r"\s+AS\s+|\s+", part.strip())[-1] for part in parts]


def test_payment_attempts_keeps_columns_for_detection():
    """판정 잡이 읽는 payment_attempts의 칸은 결제 UPDATE 처리 뒤에도 같다 (2026-10-23). 판정 SQL을 바꾸지 않아도 된다."""
    assert select_columns(design_sql()["payment_attempts"]) == [
        "payment_id", "order_id", "attempt_no", "pg", "status", "failure_code", "failure_cause",
        "completed_at", "loaded_at"]


def test_payment_views_read_one_state_view():
    """보류 판단은 payment_states 한 곳에서 하고, 두 뷰가 나눠 읽는다 (같은 판단을 따로 계산해 어긋나지 않게)."""
    sql = design_sql()
    assert "FROM gold_b.payment_states" in sql["payment_attempts"] and "hold_reason IS NULL" in sql["payment_attempts"]
    assert "FROM gold_b.payment_states" in sql["payment_conflicts"] and "hold_reason IS NOT NULL" in sql["payment_conflicts"]
    assert "gold_b.payment_events" not in sql["payment_attempts"] + sql["payment_conflicts"]
