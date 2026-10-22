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
NAMES = ("payment_conflicts", "payment_attempts", "malformed_messages")


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
