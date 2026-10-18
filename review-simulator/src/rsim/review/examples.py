"""생성 프롬프트 예시 세트(ex-vN) 읽기 (지시서 sim/review-product-import 2단계, 2026-10-16).

예시는 코드 상수가 아니라 data/examples/ex-vN.md 파일로 둔다. 사람이 직접 쓴 가상 리뷰 예시를 버전별로
남기고, 같은 시드로 `rsim bench --examples ex-vN` 을 돌려 버전끼리 성능을 비교하기 위해서다.
결과는 docs/examples-scorecard.md (점검표) 에 한 줄씩 적는다.

파일 형식 (마크다운)
--------------------
- 첫 번째 ```text 코드블록 안의 줄들이 그대로 시스템 프롬프트 "예시" 칸에 들어간다.
  코드블록 밖의 글(작성 안내, 메모)은 프롬프트에 들어가지 않는다.
- `seed_sources: aihub, handwritten` 줄(코드블록 밖)이 있으면, 명세 앞에 넣는 말투 예시(.local/seeds.jsonl)를
  그 출처에서만 뽑는다. 없으면 모든 출처(aihub, synth, handwritten)를 쓴다.
  ex-v1 부터는 Gemini 로 만든 합성 예시(synth)를 뺀다 (2026-10-16 lemin 결정: 사람이 쓴 예시로 대체).
- 코드블록 안에 아직 채우지 않은 칸(`____`)이 남아 있으면 읽지 않고 멈춘다.
  덜 쓴 예시로 Bedrock 을 불러 비용만 쓰는 일을 막는다.

예시는 실제 쇼핑몰 후기를 옮겨 적지 말고 새로 쓴 가상 리뷰만 넣는다(공개 저장소 + Bedrock 으로 전송).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 아직 채우지 않은 칸 표시. 템플릿(ex-v1.md 초안)에서 쓴다.
PLACEHOLDER = "____"
# 말투 예시 출처 이름 (seeds_prep.py 가 만드는 source 값)
KNOWN_SEED_SOURCES = ("aihub", "synth", "handwritten")

_FENCE_RE = re.compile(r"^```text[ \t]*\r?\n(.*?)^```", re.MULTILINE | re.DOTALL)
_SOURCES_RE = re.compile(r"^seed_sources:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class ExampleSet:
    version: str  # 파일 이름에서 온 버전 (예: "ex-v1"). 정답 이벤트 generator.examples_version 으로 남는다
    lines: str  # 시스템 프롬프트 예시 칸에 그대로 넣을 글
    seed_sources: tuple[str, ...] | None  # 말투 예시 출처 제한. None = 모든 출처


def parse_example_set(version: str, body: str) -> ExampleSet:
    """예시 파일 본문을 읽는다. 형식이 틀리면 SystemExit (무엇을 고칠지 한국어로 알려 준다)."""
    m = _FENCE_RE.search(body)
    if not m:
        raise SystemExit(f"예시 {version}: ```text 코드블록이 없습니다 (data/examples/README 참고)")
    lines = "\n".join(line.rstrip() for line in m.group(1).splitlines()).strip("\n")
    if not lines.strip():
        raise SystemExit(f"예시 {version}: 코드블록이 비어 있습니다")
    blanks = [i for i, line in enumerate(lines.splitlines(), 1) if PLACEHOLDER in line]
    if blanks:
        raise SystemExit(
            f"예시 {version}: 아직 채우지 않은 칸({PLACEHOLDER})이 코드블록 {blanks}번째 줄에 있습니다"
        )

    sources = None
    # 코드블록 밖에서만 seed_sources 를 찾는다 (예시 문장 안의 글자와 헷갈리지 않게)
    outside = body[: m.start()] + body[m.end() :]
    sm = _SOURCES_RE.search(outside)
    if sm:
        sources = tuple(s.strip() for s in sm.group(1).split(",") if s.strip())
        unknown = [s for s in sources if s not in KNOWN_SEED_SOURCES]
        if unknown or not sources:
            raise SystemExit(
                f"예시 {version}: seed_sources 값 {unknown or '(비어 있음)'} 은(는) 쓸 수 없습니다. "
                f"가능한 값: {', '.join(KNOWN_SEED_SOURCES)}"
            )
    return ExampleSet(version=version, lines=lines, seed_sources=sources)


def load_example_set(examples_dir: Path, version: str) -> ExampleSet:
    """data/examples/<version>.md 를 읽는다. (EXAMPLES_DIR, EXAMPLES_VERSION 설정 또는 bench --examples)"""
    path = Path(examples_dir) / f"{version}.md"
    if not path.exists():
        have = sorted(p.stem for p in Path(examples_dir).glob("ex-v*.md"))
        raise SystemExit(f"예시 파일이 없습니다: {path} (있는 버전: {', '.join(have) or '없음'})")
    return parse_example_set(version, path.read_text(encoding="utf-8"))
