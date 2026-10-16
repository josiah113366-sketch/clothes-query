"""시드(말투 예시) 리뷰 풀.

.local/seeds.jsonl (rsim seeds 결과)을 읽어 두고, 프롬프트에 넣을 예시를 뽑아 준다.

예시를 뽑는 원칙
- 같은 카테고리 예시를 우선 쓰되(신발 리뷰엔 신발 말투), 카테고리 없는 합성 리뷰도 섞는다.
- 출처(합성/AI Hub/직접 작성)를 SOURCE_WEIGHTS 비율로 섞는다.
  직접 작성 리뷰는 "실제 말투"에 가장 가까워서 수가 적어도 자주 뽑히도록 가중치를 높게 둔다.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

# 출처별 뽑힐 비율(상대값). 예: 8개를 뽑으면 대략 aihub 3, synth 2, handwritten 3 개.
# 어느 출처의 말투를 더 따르게 할지 여기서 조절한다. 해당 출처 시드가 없으면 자동으로 빠진다.
SOURCE_WEIGHTS = {"aihub": 0.4, "synth": 0.25, "handwritten": 0.35}


class SeedPool:
    def __init__(self, rows: list[dict], rng: random.Random):
        self.rng = rng
        self.rows = rows
        # (출처, 카테고리) 별로 미리 나눠 둔다. 카테고리 None = 어느 카테고리에도 쓸 수 있는 공통 예시
        self._index: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
        for r in rows:
            self._index[(r["source"], r.get("category"))].append(r)
        self.sources = sorted({r["source"] for r in rows})

    @classmethod
    def load(cls, path: Path, rng: random.Random) -> SeedPool:
        if not path.exists():
            raise FileNotFoundError(
                f"시드 파일이 없습니다: {path}\n먼저 `rsim seeds` 를 실행하세요."
            )
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        return cls(rows, rng)

    def product_names(self) -> dict[str, list[str]]:
        """카테고리별 상품명 목록 (catalog.py 가 기본 상품 목록을 만들 때 사용)."""
        names: dict[str, set[str]] = defaultdict(set)
        for r in self.rows:
            if r.get("category") and r.get("product_name"):
                names[r["category"]].add(r["product_name"])
        return {k: sorted(v) for k, v in names.items()}

    def sample(self, k: int, category: str | None) -> list[dict]:
        """프롬프트용 예시 k개를 뽑는다(중복 없이)."""
        weights = {s: w for s, w in SOURCE_WEIGHTS.items() if s in self.sources}
        if not weights:
            return self.rng.sample(self.rows, min(k, len(self.rows)))

        picked: list[dict] = []
        seen: set[int] = set()
        attempts = 0
        while len(picked) < k and attempts < k * 10:
            attempts += 1
            source = self.rng.choices(list(weights), weights=list(weights.values()))[0]
            # 같은 카테고리 후보 + 공통(카테고리 없음) 후보를 합쳐서 고른다
            candidates = self._index.get((source, category), []) + self._index.get(
                (source, None), []
            )
            if not candidates:
                continue
            row = self.rng.choice(candidates)
            if id(row) in seen:
                continue
            seen.add(id(row))
            picked.append(row)
        return picked
