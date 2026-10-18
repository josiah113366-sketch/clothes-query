from pathlib import Path

import pytest

from sim.common.regions import RegionTable, load_regions

REAL_REGION_FILE = Path(__file__).resolve().parents[1] / "data" / "region_weights_202609.csv"


@pytest.fixture(scope="session")
def regions() -> RegionTable:
    return load_regions(REAL_REGION_FILE)


@pytest.fixture(scope="session")
def member_ids() -> list[str]:
    """행동 테스트용 합성 회원 ID 2,000개 (정렬됨)."""
    from behavior_fixtures import make_member_ids

    return make_member_ids(2_000)


@pytest.fixture(scope="session")
def catalog():
    """행동 테스트용 합성 상품 1,000개."""
    from behavior_fixtures import make_catalog

    return make_catalog(1_000)
