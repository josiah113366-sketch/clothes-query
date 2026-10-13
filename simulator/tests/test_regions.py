from pathlib import Path

import pytest

from sim.common.regions import RegionFileError, load_regions

HEADER = "region_sigungu,sido,population,weight"


def write_csv(path: Path, rows: list[str], header: str = HEADER, newline: str = "\r\n") -> Path:
    path.write_bytes((newline.join([header, *rows]) + newline).encode("utf-8"))
    return path


def make_rows(n: int = 256) -> list[str]:
    return [f"시도{i % 17} 구{i},시도{i % 17},{1000 + i},{1 / n:.10f}" for i in range(n)]


def test_real_file_loads(regions) -> None:
    assert len(regions) == 256
    assert abs(sum(regions.weights) - 1) < 1e-6
    assert abs(sum(regions.sido_weights().values()) - 1) < 1e-6


def test_crlf_and_lf_files_load(tmp_path: Path) -> None:
    assert len(load_regions(write_csv(tmp_path / "a.csv", make_rows()))) == 256
    assert len(load_regions(write_csv(tmp_path / "b.csv", make_rows(), newline="\n"))) == 256


@pytest.mark.parametrize("case", ["rows", "dup", "sum", "columns", "negative"])
def test_invalid_files_rejected(tmp_path: Path, case: str) -> None:
    rows, header = make_rows(), HEADER
    if case == "rows":
        rows = rows[:-1]
    elif case == "dup":
        rows[1] = rows[0]
    elif case == "sum":
        rows[0] = rows[0].rsplit(",", 1)[0] + ",0.5"
    elif case == "columns":
        header = "region,sido,population,weight"
    elif case == "negative":
        rows[0] = rows[0].rsplit(",", 1)[0] + ",-0.1"
    with pytest.raises(RegionFileError):
        load_regions(write_csv(tmp_path / "x.csv", rows, header))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RegionFileError):
        load_regions(tmp_path / "none.csv")
