"""행동 테스트용 합성 데이터와 가짜 원천 (DB 없이)."""

import uuid

from sim.behavior.model import Catalog


def make_member_ids(count: int) -> list[str]:
    return sorted(str(uuid.UUID(int=i + 1)) for i in range(count))


def make_catalog(count: int) -> Catalog:
    article_ids = tuple(f"{i:010d}" for i in range(100_000_001, 100_000_001 + count))
    prices = tuple(5_900 + 500 * (i % 60) for i in range(count))
    return Catalog(article_ids, prices)


class StaticMembers:
    def __init__(self, member_ids: list[str]) -> None:
        self.member_ids = member_ids
        self.reads = 0
        self.fail = False

    def read_active_members(self) -> list[str]:
        self.reads += 1
        if self.fail:
            raise OSError("읽기 실패")
        return list(self.member_ids)


class StaticCatalog:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def read_catalog(self) -> Catalog:
        return self.catalog
