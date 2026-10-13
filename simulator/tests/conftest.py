from pathlib import Path

import pytest

from sim.common.regions import RegionTable, load_regions

REAL_REGION_FILE = Path(__file__).resolve().parents[1] / "data" / "region_weights_202609.csv"


@pytest.fixture(scope="session")
def regions() -> RegionTable:
    return load_regions(REAL_REGION_FILE)
