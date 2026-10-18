"""예시 세트(ex-vN) 성능 점검표 (지시서 sim/review-product-import 2단계, 2026-10-16).

rsim bench 의 summary.json 한 개 → 마크다운 표 한 줄. docs/examples-scorecard.md 의 표에 붙인다.
`rsim scorecard` 는 .local/bench/*/summary.json 을 모두 읽어 표 전체를 다시 출력한다
(예시 버전 기록이 없던 예전 실행은 예시 칸이 "-", 검수 루프 이전 실행은 뺀다).

칸 설명 (비율은 명세 수 n 기준)
- 1차 통과 : 검수 1차에서 속성 누락·감성 차이가 없던 비율
- 버림     : 재생성 후에도 실패해서 버린 비율 (시뮬레이터라면 레이크에 안 쓰는 리뷰)
- 감성/중립 : 1차 감성 차이 건수 / 그중 중립이 낀 건수
- 명세 밖  : 1차에서 명세에 없는 속성을 덧붙인 건수 (버리지 않고 정답에 추가됨)
- 문장·글자 : 최종 리뷰 중 문장 수 초과 / 글자 수 범위 밖 건수
- 토큰/건  : 생성 + 검수 호출 합계 ÷ n
"""

from __future__ import annotations

import json
from pathlib import Path

HEADER = (
    "| 실행 | 예시 | 프롬프트 | n | 1차 통과 | 버림 | 감성/중립 | 명세 밖 | 문장·글자 "
    "| 입력 토큰/건 | 출력 토큰/건 | $/1,000건 | 지연(초) |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
)


def _pct(num: int, den: int) -> str:
    return f"{num / den:.0%}" if den else "-"


def scorecard_row(run_id: str, summary: dict, model_id: str) -> str:
    """summary.json 의 모델 하나 → 표 한 줄"""
    m = summary["models"][model_id]
    n = summary.get("n_specs") or m.get("reviews_expected") or 0
    first = str(m.get("aspect_pass_first", "-/-")).split("/")[0]
    first_pct = _pct(int(first), n) if first.isdigit() else "-"
    counts = m.get("aspect_problem_counts_first", {})
    neutral = m.get("neutral_errors_first", "-")
    problems = m.get("problem_counts", {})
    cost = m.get("cost_per_1000_reviews_usd")
    cells = [
        run_id,
        summary.get("examples_version") or "-",
        summary.get("prompt_version", "-"),
        str(n),
        first_pct,
        _pct(m.get("aspect_dropped", 0), n),
        f"{counts.get('sentiment', '-')}/{neutral}",
        str(counts.get("extra", "-")),
        f"{problems.get('too_many_sentences', 0)}/{problems.get('length_out_of_range', 0)}",
        f"{m['input_tokens'] / n:.0f}" if n else "-",
        f"{m['output_tokens'] / n:.0f}" if n else "-",
        "-" if cost is None else f"{cost:.3f}",
        str(m.get("latency_sec_mean", "-")),
    ]
    return "| " + " | ".join(cells) + " |"


def run_scorecard(bench_dir: Path) -> None:
    """bench_dir 아래 모든 실행의 점검표를 출력한다 (오래된 순)."""
    rows = []
    for path in sorted(Path(bench_dir).glob("*/summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        for model_id, m in summary.get("models", {}).items():
            if "aspect_pass_first" not in m:
                continue  # 검수 루프(p5.3) 이전 실행은 비교 기준이 달라 뺀다
            try:
                rows.append(scorecard_row(path.parent.name, summary, model_id))
            except (KeyError, TypeError, ValueError):
                continue  # 검수 루프 이전의 아주 오래된 형식은 건너뛴다
    if not rows:
        print(f"{bench_dir} 에 bench 결과가 없습니다. 먼저 rsim bench --yes 를 실행하세요.")
        return
    print(HEADER)
    print("\n".join(rows))
