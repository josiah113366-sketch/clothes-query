"""검수 모델 정확도 측정 (p5.3 검수 루프용, 2026-10-14).

lemin 이 채점한 생성 리뷰(.local/bench/verify_gold.json 의 O/X 판정)를 검수 모델에 다시 라벨링시켜서
"검수 모델이 통과/실패라고 본 것"이 사람 판정과 얼마나 맞는지 잰다. 검수 루프를 믿고 써도 되는지 보는 용도.

실행 (Windows, Bedrock API 키 필요. 35건 → 검수 호출 7번, 약 $0.002)
  rsim verify-eval --yes
  rsim verify-eval --yes --verifier-model <다른 모델 ID>   # 다른 검수 모델 비교

결과: 화면 표 + .local/bench/verify-eval-<시각>.json
  - 일치율        : 애매(?)를 뺀 건 중 사람 판정과 같은 비율
  - 위반 잡은 비율 : 사람이 X 라고 한 것 중 검수 모델도 실패로 본 비율 (낮으면 나쁜 리뷰가 통과됨)
  - 오탐 비율      : 사람이 O 라고 한 것 중 검수 모델이 실패로 본 비율 (높으면 멀쩡한 리뷰를 버림 → 재생성 비용 증가)
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from rsim.bench.bench import chunks, converse
from rsim.common.config import load_settings  # noqa: F401  (.env 읽기)
from rsim.review.verifier import VERIFIER_PROMPT_VERSION, compare, verify_batch

# 벤치 결과(.local/bench)와 같은 폴더를 쓴다. 채점 파일·결과 모두 원문이 들어 있어 커밋하지 않는다.
OUT = Path(".local/bench")


def load_items(gold: dict) -> list[dict]:
    """gold 의 실행 폴더마다 rating_sheet.csv 에서 본문과 지정 속성을 읽는다.
    명세는 그 실행 당시의 것(시트의 '지정 속성' 열)을 써야 한다. (p5.2 부터 짧은 리뷰 속성 수가 바뀌어서 다시 만들면 달라짐)
    """
    items = []
    for run, verdicts in gold["runs"].items():
        rows = {
            r["번호"]: r
            for r in csv.DictReader(
                (OUT / run / "rating_sheet.csv").read_text(encoding="utf-8-sig").splitlines()
            )
        }
        for no, verdict in verdicts.items():
            r = rows[no]
            aspects = []
            for part in r["지정 속성(속성:감성)"].split(","):
                name, _, senti = part.strip().rpartition(":")
                aspects.append({"aspect": name, "sentiment": senti})
            items.append(
                {
                    "id": f"{run}#{no}",
                    "text": r["본문"],
                    "gold": verdict,
                    "spec": SimpleNamespace(aspects=aspects),
                }
            )
    return items


def run_verify_eval(args) -> None:
    """args: region, verifier_model, yes, gold (채점 파일 경로)."""

    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    items = load_items(gold)
    print(
        f"검수 모델={args.verifier_model}  프롬프트={VERIFIER_PROMPT_VERSION}  리뷰 {len(items)}건 → 호출 {len(chunks(items, 5))}회"
    )
    if not args.yes:
        print("[호출 안 함] 실제 실행하려면 --yes")
        return

    def call(system, user, max_tokens):
        r = converse(args.region, args.verifier_model, system, user, max_tokens, temperature=0)
        return r["status"], r["resp"]

    usage = {"input_tokens": 0, "output_tokens": 0}
    for batch in chunks(items, 5):
        labels, u = verify_batch(call, [(it["id"], it["text"]) for it in batch])
        usage["input_tokens"] += u["input_tokens"]
        usage["output_tokens"] += u["output_tokens"]
        for it in batch:
            lab = (labels or {}).get(it["id"])
            it["labels"] = lab
            it["problems"] = ["verify_failed"] if lab is None else compare(it["spec"], lab)
            it["pred"] = "X" if it["problems"] else "O"

    scored = [it for it in items if it["gold"] in ("O", "X")]
    agree = sum(it["pred"] == it["gold"] for it in scored)
    bad = [it for it in scored if it["gold"] == "X"]
    good = [it for it in scored if it["gold"] == "O"]
    print(f"\n{'번호':<22}{'사람':<5}{'검수':<5}검수가 찾은 문제")
    for it in items:
        mark = "" if it["gold"] == "?" else ("  " if it["pred"] == it["gold"] else "✗ ")
        print(f"{mark}{it['id']:<20}{it['gold']:<5}{it['pred']:<5}{', '.join(it['problems'])}")
    summary = {
        "verifier_model": args.verifier_model,
        "verifier_prompt": VERIFIER_PROMPT_VERSION,
        "scored": len(scored),
        "agreement": round(agree / len(scored), 3) if scored else None,
        "violation_recall": round(sum(it["pred"] == "X" for it in bad) / len(bad), 3)
        if bad
        else None,
        "false_alarm_rate": round(sum(it["pred"] == "X" for it in good) / len(good), 3)
        if good
        else None,
        **usage,
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=1))
    out = OUT / f"verify-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(
        json.dumps(
            {
                "summary": summary,
                "items": [{k: v for k, v in it.items() if k != "spec"} for it in items],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"저장: {out}")
