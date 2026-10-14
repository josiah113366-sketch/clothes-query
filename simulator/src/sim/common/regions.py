"""지역 가중치 CSV 로더. 읽을 때 형식과 값을 검증한다."""

import csv
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

from sim.member.params import REGION_COLUMNS, REGION_ROW_COUNT, REGION_WEIGHT_TOLERANCE


class RegionFileError(ValueError):
    """지역 파일 검증 실패. 어떤 검증이 실패했는지 메시지에 담는다."""


@dataclass(frozen=True)
class RegionTable:
    names: tuple[str, ...]
    sidos: tuple[str, ...]
    weights: tuple[float, ...]
    cum_weights: tuple[float, ...]
    source_name: str

    def __len__(self) -> int:
        return len(self.names)

    def sido_of(self, name: str) -> str:
        """시도 = region_sigungu의 첫 공백 앞."""
        return name.split(" ", 1)[0]

    def sido_weights(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for name, weight in zip(self.names, self.weights, strict=True):
            sido = self.sido_of(name)
            totals[sido] = totals.get(sido, 0.0) + weight
        return totals


def load_regions(path: Path) -> RegionTable:
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            rows = [row for row in reader if row]
    except FileNotFoundError:
        raise RegionFileError(f"지역 파일이 없습니다: {path.name}") from None

    if header is None or tuple(header) != REGION_COLUMNS:
        raise RegionFileError(f"[컬럼] {', '.join(REGION_COLUMNS)} 이어야 합니다: {path.name}")
    if any(len(row) != len(REGION_COLUMNS) for row in rows):
        raise RegionFileError(f"[컬럼] 열 수가 맞지 않는 행이 있습니다: {path.name}")
    if len(rows) != REGION_ROW_COUNT:
        raise RegionFileError(f"[행 수] {REGION_ROW_COUNT}행이어야 하는데 {len(rows)}행입니다.")

    names = tuple(row[0] for row in rows)
    if len(set(names)) != len(names):
        raise RegionFileError("[중복] region_sigungu에 중복이 있습니다.")

    try:
        weights = tuple(float(row[3]) for row in rows)
    except ValueError:
        raise RegionFileError("[가중치] weight에 숫자가 아닌 값이 있습니다.") from None
    if any(w <= 0 for w in weights):
        raise RegionFileError("[가중치] weight는 모두 양수여야 합니다.")
    total = sum(weights)
    if abs(total - 1.0) > REGION_WEIGHT_TOLERANCE:
        raise RegionFileError(f"[가중치] weight 합이 1이 아닙니다 (합계 {total:.9f}).")

    return RegionTable(
        names=names,
        sidos=tuple(row[1] for row in rows),
        weights=weights,
        cum_weights=tuple(accumulate(weights)),
        source_name=path.name,
    )
