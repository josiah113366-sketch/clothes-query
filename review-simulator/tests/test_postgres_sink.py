"""PostgresSink 통합 테스트. TEST_DATABASE_URL 이 있을 때만 돈다(없으면 건너뜀).

로컬에서 돌리는 법 (simulator/ 에서 docker compose up -d 로 postgres 를 띄운 뒤):
  TEST_DATABASE_URL=postgresql://sim:sim@localhost:5432/clothes pytest tests/test_postgres_sink.py
테스트용 스키마를 새로 만들어 그 안에서만 쓰고 끝나면 지운다(기존 reviews 테이블은 건드리지 않는다).
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from rsim.review.sinks import PostgresSink

URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL 없음")
DDL = Path(__file__).resolve().parents[2] / "db" / "schema" / "003_review.sql"


@pytest.fixture
def sink(tmp_path: Path):
    psycopg = pytest.importorskip("psycopg")
    schema = f"rsim_test_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(URL, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    admin.execute(f"SET search_path TO {schema}")
    admin.execute(DDL.read_text(encoding="utf-8"))
    # 테스트 스키마만 보이게 접속 옵션으로 search_path 를 준다
    s = PostgresSink(
        f"{URL}{'&' if '?' in URL else '?'}options=-csearch_path%3D{schema}", tmp_path / "t.jsonl"
    )
    yield s
    s.close()
    admin.execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


def _review(review_id: str, order_id: str | None) -> dict:
    return {
        "review_id": review_id,
        "order_id": order_id,
        "member_id": "C-0000000001",
        "product_id": "W-0001",
        "product_name": "OO 니트",
        "category": "여성의류",
        "age_group": "30대",
        "rating": 4,
        "text": "괜찮아요",
        "source": "simulator",
        "created_at": "2026-10-02T10:00:00+09:00",
    }


def test_insert_and_skip_duplicate_order(sink: PostgresSink, tmp_path: Path) -> None:
    sink.send(_review("R-1", "O-1"), {"review_id": "R-1"})
    sink.send(_review("R-2", "O-1"), {"review_id": "R-2"})  # 같은 주문 → 넣지 않음
    sink.send(_review("R-3", None), {"review_id": "R-3"})  # 주문 없는 리뷰는 여러 개 가능
    assert sink.reviewed_order_ids() == {"O-1"}
    assert (sink.inserted, sink.duplicated) == (2, 1)
    sink.truth_fh.flush()
    truth = [json.loads(x)["review_id"] for x in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert truth == ["R-1", "R-3"]  # 넣지 않은 리뷰의 정답은 쓰지 않는다
