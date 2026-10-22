"""회원 풀(누적 가중치 추첨)과 회원·상품을 읽는 원천.

회원은 member_id만 읽는다. 이름, 이메일, 전화, 생년월일, 비밀번호 해시 컬럼은 읽지 않는다.
"""

import hashlib
from bisect import bisect_right
from collections.abc import Sequence
from itertools import accumulate
from typing import Protocol

from sim.behavior import params
from sim.behavior.model import Catalog
from sim.common.db import connect, safe_db_errors
from sim.common.rng import SimRandom

MEMBER_SQL = "SELECT member_id FROM members WHERE status = 'ACTIVE' ORDER BY member_id"
CATALOG_SQL = "SELECT article_id, price FROM product_variant ORDER BY article_id"


def is_top_member(seed: int, member_id: str) -> bool:
    """DB에 저장하지 않는 결정론적 성향. 같은 시드면 같은 회원은 언제나 같은 값이다."""
    digest = hashlib.sha256(f"{seed}:{member_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < params.TOP_MEMBER_SHARE


def member_weight(seed: int, member_id: str) -> int:
    return params.TOP_MEMBER_WEIGHT if is_top_member(seed, member_id) else 1


class MemberPool:
    def __init__(self, seed: int, member_ids: Sequence[str]) -> None:
        self.seed = seed
        self.member_ids: tuple[str, ...] = ()
        self._cumulative: list[int] = []
        self.update(member_ids)

    def update(self, member_ids: Sequence[str]) -> None:
        ids = tuple(sorted(member_ids))
        if not ids:
            raise ValueError("회원이 없습니다. sim member baseline을 먼저 실행하세요.")
        if ids == self.member_ids:
            return  # 바뀐 게 없으면 가중치를 다시 계산하지 않는다
        self.member_ids = ids
        self._cumulative = list(accumulate(member_weight(self.seed, m) for m in ids))

    def __len__(self) -> int:
        return len(self.member_ids)

    def discard(self, member_id: str) -> bool:
        """목록에서 뺀다(주문 API가 ACTIVE가 아니라고 거절한 회원). 마지막 한 명은 남긴다."""
        if member_id not in self.member_ids or len(self.member_ids) == 1:
            return False
        self.update([m for m in self.member_ids if m != member_id])
        return True

    def sample(self, rng: SimRandom) -> str:
        target = rng.random.random() * self._cumulative[-1]
        return self.member_ids[bisect_right(self._cumulative, target)]


class MemberSource(Protocol):
    def read_active_members(self) -> list[str]:
        """ACTIVE 회원의 member_id 목록. 실패하면 예외를 던진다."""
        ...


class CatalogSource(Protocol):
    def read_catalog(self) -> Catalog: ...


class DbMemberSource:
    def __init__(self, database_url: str, schema: str | None = None) -> None:
        self._url, self._schema = database_url, schema

    def read_active_members(self) -> list[str]:
        with connect(self._url, self._schema) as conn, safe_db_errors():
            return [str(row[0]) for row in conn.execute(MEMBER_SQL).fetchall()]


class DbCatalogSource:
    def __init__(self, database_url: str, schema: str | None = None) -> None:
        self._url, self._schema = database_url, schema

    def read_catalog(self) -> Catalog:
        with connect(self._url, self._schema) as conn, safe_db_errors():
            rows = conn.execute(CATALOG_SQL).fetchall()
        return Catalog(tuple(str(r[0]) for r in rows), tuple(int(r[1]) for r in rows))
