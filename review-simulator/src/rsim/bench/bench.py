"""Bedrock 리뷰 생성 소량 실행 (비용·속도·검수 결과 확인용).

시뮬레이터와 같은 프롬프트(SYSTEM_PROMPT, build_user_prompt)·검수 루프 규칙으로 고정 시드 명세 N건을 만들고,
결과를 사람이 채점할 수 있는 시트로 저장한다. Kafka 로는 보내지 않는다.
모델 비교(2026-10-13, 8개 모델)는 끝나서 gemma-3-12b 로 확정했고, 모델 목록 조회·호출 확인·자동 선택 기능은
2026-10-14 정리 때 뺐다. 다른 모델을 다시 보고 싶으면 --models 에 ID 를 직접 넣으면 된다.

인증: .env 의 AWS_BEARER_TOKEN_BEDROCK(Bedrock API 키). Bedrock 호출은 rsim/review/bedrock.py 를 같이 쓴다.

실행 예 (review-simulator/ 폴더에서)
  rsim bench --n 10                                   # 계획만 출력 (호출 안 함)
  rsim bench --yes --n 100 --max-calls 20 --region ap-northeast-1
리전 기본값은 .env 의 AWS_REGION, 모델 기본값은 .env 의 BEDROCK_MODEL_ID.

결과: .local/bench/<실행시각>/ 에 summary.json, calls.jsonl, outputs.jsonl, rating_sheet.csv, blind_key.json
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from rsim.common.config import load_settings
from rsim.common.rng import make_rng
from rsim.review.bedrock import converse as _converse
from rsim.review.bedrock import response_text, response_usage
from rsim.review.catalog import Catalog
from rsim.review.generator import (
    JSON_INSTRUCTION,
    LENGTH_GUIDE,
    LENGTH_LIMITS_FOR_PROMPT,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
    normalize_jamo,
    parse_reviews,
)
from rsim.review.scenario import ScenarioEngine, SimClock
from rsim.review.seeds import SeedPool
from rsim.review.verifier import (
    VERIFIER_PROMPT_VERSION,
    blocking,
    compare,
    merge_truth,
    problems_to_feedback,
    verify_batch,
)

# 길이 지정(short/medium/long)별 허용 글자수. generator.LENGTH_GUIDE 문구보다 조금 넉넉하게 잡았다.
LENGTH_LIMITS = {"short": (1, 60), "medium": (40, 160), "long": (100, 320)}

# 생성 온도. 모델마다 기본값이 달라서 고정한다. 리뷰는 다양해야 하므로 약간 높게.
TEMPERATURE = 0.8


# ---------------------------------------------------------------- Bedrock 호출
def converse(
    region: str,
    model_id: str,
    system: str,
    user: str,
    max_tokens: int,
    retries: int = 3,
    temperature: float | None = None,
) -> dict:
    """rsim.review.bedrock.converse 를 벤치마크 형식({"status", "resp"})으로 감싼다. 키가 없으면 멈춘다."""
    settings = load_settings()
    if not settings.bedrock_api_key:
        sys.exit(".env 또는 환경변수에 AWS_BEARER_TOKEN_BEDROCK(Bedrock API 키)를 넣어 주세요.")
    status, resp = _converse(
        api_key=settings.bedrock_api_key,
        region=region,
        model_id=model_id,
        system=system,
        user=user,
        max_tokens=max_tokens,
        retries=retries,
        # 생성은 TEMPERATURE(0.8), 검수(라벨링)는 0 으로 부른다
        temperature=TEMPERATURE if temperature is None else temperature,
    )
    return {"status": status, "resp": resp}


# ---------------------------------------------------------------- 벤치마크 본체
def make_specs(settings, n: int, seed: int):
    """고정 시드로 명세 n건을 만든다. 이상 상황·수정 이벤트는 넣지 않는다(소량 테스트라 기본 경로만)."""
    rng = make_rng(seed)
    seeds = SeedPool.load(settings.seeds_path, rng)
    catalog = Catalog.build(settings.products_path, seeds.product_names(), rng)
    engine = ScenarioEngine(catalog, [], SimClock(None, 60, rng), rng)
    specs = [engine.next_spec() for _ in range(n)]
    # 말투 예시도 한 번만 뽑아 모든 모델/호출에서 공유한다 (비교 조건 통일)
    examples = seeds.sample(settings.few_shot_k, specs[0].product.category)
    return specs, examples


def chunks(items, size):
    return [items[i : i + size] for i in range(0, len(items), size)]


def run_verify(region, verifier_model, items):
    """검수 호출 1번 (review/verifier.py 와 같은 프롬프트). 반환: (라벨 dict 또는 None, 기록용 dict)"""
    t0 = time.monotonic()

    def call(system, user, max_tokens):
        r = converse(region, verifier_model, system, user, max_tokens, temperature=0)
        return r["status"], r["resp"]

    labels, usage = verify_batch(call, items)
    rec = {
        "kind": "verify",
        "verifier_model": verifier_model,
        "n_specs": len(items),
        "http_status": usage["status"],
        "ok": labels is not None,
        "error": None if labels is not None else f"검수 실패 HTTP {usage['status']}",
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "latency_sec": round(time.monotonic() - t0, 2),
    }
    return labels, rec


def run_batch(region, model_id, batch, examples, feedback=None):
    """명세 한 묶음을 한 번 호출로 생성하고 기록용 dict 를 돌려준다. feedback = 재생성 때 지난 문제 설명."""
    t0 = time.monotonic()
    r = converse(
        region,
        model_id,
        SYSTEM_PROMPT,
        build_user_prompt(batch, examples, feedback) + JSON_INSTRUCTION,
        max_tokens=1000 + 500 * len(batch),
    )  # 시뮬레이터와 같은 상한
    rec = {
        "model": model_id,
        "n_specs": len(batch),
        "http_status": r["status"],
        "ok": False,
        "error": None,
        "stop_reason": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_sec": round(time.monotonic() - t0, 2),
        "reviews": [],
    }
    if r["status"] != 200:
        rec["error"] = f"HTTP {r['status']}: {str(r['resp'])[:200]}"
        return rec
    resp = r["resp"]
    rec["stop_reason"] = resp.get("stopReason")
    rec["input_tokens"], rec["output_tokens"] = response_usage(resp)
    text = response_text(resp)
    reviews = parse_reviews(text)
    if reviews is None:
        rec["error"] = f"JSON 파싱 실패: {text[:120]}"
    else:
        # 시뮬레이터와 같은 후처리(조합용 자모 → ㅜ ㅠ ㅋ). 바뀐 건수는 기록해 둔다.
        rec["jamo_fixed"] = 0
        for r in reviews:
            fixed = normalize_jamo(str(r["text"]))
            rec["jamo_fixed"] += fixed != str(r["text"])
            r["text"] = fixed
        rec["reviews"] = reviews
        rec["ok"] = rec["stop_reason"] != "max_tokens"
    return rec


def check_review(spec, text):
    """자동 점검. 반환: 문제 이름 리스트(비어 있으면 통과). 속성·감성을 지켰는지는 사람이(또는 나중에 라벨러가) 본다."""
    problems = []
    lo, hi = LENGTH_LIMITS[spec.length]
    if not (lo <= len(text) <= hi):
        problems.append("length_out_of_range")
    # p5.1: 문장 수 점검 (마침표·물음표·느낌표·말줄임표 뒤를 문장 끝으로 셈. 대략적인 기준)
    n_sent = len([x for x in re.split(r"[.!?…]+\s*", text.strip()) if x.strip()])
    if n_sent > LENGTH_LIMITS_FOR_PROMPT[spec.length]["max_sentences"]:
        problems.append("too_many_sentences")
    if (
        spec.product.product_name and spec.product.product_name in text
    ):  # 규칙 5: 상품명 그대로 쓰지 않기
        problems.append("product_name_leak")
    if re.search(r"[1-6]0대", text):  # 규칙 4: 연령대 직접 밝히지 않기
        problems.append("age_stated")
    if not re.search(r"[가-힣]", text):  # 한국어가 아닌 답 (일부 모델은 영어로 답하기도 함)
        problems.append("not_korean")
    return problems


def load_prices() -> dict:
    return json.loads((Path(__file__).parent / "prices.json").read_text(encoding="utf-8"))


def cost_usd(prices, model, in_tok, out_tok):
    """prices.json 에 단가가 있는 모델만 계산. 추론 프로필 접두사(jp./apac./global.)는 떼고도 찾아본다."""
    p = prices.get(model) or prices.get(re.sub(r"^(jp|apac|global|us|eu)\.", "", model))
    if not p:
        return None
    return (in_tok * p["input"] + out_tok * p["output"]) / 1_000_000


# 결과 저장 폴더. 생성 리뷰 원문이 들어 있어서 .local/ 에만 두고 커밋하지 않는다.
OUT_DIR = Path(".local/bench")


def run_bench(args) -> None:
    """소량 실행 본체. args 는 cli.py 의 rsim bench 옵션(n, batch_size, models, seed, region, max_calls,
    dry_run, yes, verifier_model, aspect_retries)을 담은 객체."""

    settings = load_settings()
    region = args.region or settings.aws_region
    print(f"리전={region}  프롬프트={PROMPT_VERSION}")

    args.models = args.models or [settings.bedrock_model_id]

    specs, examples = make_specs(settings, args.n, args.seed)
    batches = chunks(specs, args.batch_size)
    total_calls = len(args.models) * len(batches)
    print(
        f"명세 {len(specs)}건, 호출당 {args.batch_size}건 -> 모델당 {len(batches)}회, 모델 {len(args.models)}개, 총 {total_calls}회"
    )
    # 검수 루프는 항상 켜져 있다 (2026-10-14 --no-verify 제거)
    print(
        f"검수 루프: 생성 호출마다 검수 호출 1번 추가 (1차 {total_calls}회) + 실패분 재생성·재검수 "
        f"(검수 모델: {args.verifier_model or '생성 모델과 같음'})"
    )
    for m in args.models:
        print(f"  - {m}")
    approx_in = (len(SYSTEM_PROMPT) + len(build_user_prompt(batches[0], examples))) / 1.5
    print(
        f"호출 1회 입력 어림: 약 {approx_in:.0f} 토큰 (한국어라 모델마다 토크나이저가 달라 실제 값은 결과 usage 기준)"
    )
    if total_calls > args.max_calls:
        sys.exit(
            f"계획된 호출 {total_calls}회가 --max-calls {args.max_calls} 보다 많아 중단합니다."
        )
    if args.dry_run or not args.yes:
        print("\n[호출 안 함] 실제 실행하려면 --yes 를 붙이세요.")
        return

    prices = load_prices()
    out_dir = OUT_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    spec_by_id = {s.spec_id: s for s in specs}
    calls, outputs = [], []
    for model_id in args.models:
        verifier_model = args.verifier_model or model_id
        # 검수 루프: round 0 = 1차 생성, 1 이상 = 실패분 재생성. 각 생성 배치 뒤에 검수 호출 1번.
        todo, feedback = list(specs), {}
        for rnd in range(args.aspect_retries + 1):
            if not todo:
                break
            failed_specs, next_feedback = [], {}
            for batch in chunks(todo, args.batch_size):
                rec = run_batch(
                    region,
                    model_id,
                    batch,
                    examples,
                    {s.spec_id: feedback[s.spec_id] for s in batch if s.spec_id in feedback},
                )
                rec["round"] = rnd
                rec["kind"] = "generate"
                rec["cost_usd"] = cost_usd(
                    prices, model_id, rec["input_tokens"], rec["output_tokens"]
                )
                got = {str(r["spec_id"]) for r in rec["reviews"]}
                rec["missing_spec_ids"] = [s.spec_id for s in batch if s.spec_id not in got]
                calls.append({k: v for k, v in rec.items() if k != "reviews"})
                print(
                    f"{model_id} {rec['latency_sec']}s in={rec['input_tokens']} out={rec['output_tokens']} "
                    f"리뷰={len(rec['reviews'])}/{len(batch)} {rec['error'] or ''}"
                )

                reviews = {
                    str(r["spec_id"]): r
                    for r in rec["reviews"]
                    if spec_by_id.get(str(r["spec_id"])) in batch
                }
                labels = None
                if reviews:
                    labels, vrec = run_verify(
                        region,
                        verifier_model,
                        [(sid, str(r["text"]).strip()) for sid, r in reviews.items()],
                    )
                    vrec.update(
                        {
                            "model": model_id,
                            "round": rnd,
                            "cost_usd": cost_usd(
                                prices, verifier_model, vrec["input_tokens"], vrec["output_tokens"]
                            ),
                        }
                    )
                    calls.append(vrec)
                    print(
                        f"  검수 {vrec['latency_sec']}s in={vrec['input_tokens']} out={vrec['output_tokens']} {vrec['error'] or ''}"
                    )

                last_round = rnd == args.aspect_retries
                for sid, r in reviews.items():
                    spec = spec_by_id[sid]
                    text = str(r["text"]).strip()
                    if labels is None or sid not in labels:
                        aspect_problems, lab = ["verify_failed"], None
                    else:
                        lab = labels[sid]
                        aspect_problems = compare(spec, lab)
                    # p5.4: 덧붙인 속성(extra)은 실패가 아니라 정답 라벨에 추가. 누락·감성 차이만 재생성/버림
                    block = blocking(aspect_problems)
                    if block and not last_round:
                        failed_specs.append(spec)  # 다음 라운드에서 다시 생성
                        next_feedback[sid] = problems_to_feedback(block, lab)
                    outputs.append(
                        {
                            "model": model_id,
                            "spec_id": sid,
                            "round": rnd,
                            # 마지막 라운드에서도 실패하면 시뮬레이터는 버린다 → kept=False
                            "kept": not block,
                            "truth_aspects": merge_truth(spec, lab),
                            "text": text,
                            "verify_labels": lab,
                            "aspect_problems": aspect_problems,
                            "feedback_used": feedback.get(sid),
                            "problems": check_review(spec, text),
                        }
                    )
            todo, feedback = failed_specs, next_feedback

    (out_dir / "calls.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in calls), encoding="utf-8"
    )
    (out_dir / "outputs.jsonl").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in outputs), encoding="utf-8"
    )

    # ---- 모델별 요약
    summary = {
        "region": region,
        "prompt_version": PROMPT_VERSION,
        "n_specs": len(specs),
        "models": {},
        "verify": {
            "verifier_prompt": VERIFIER_PROMPT_VERSION,
            "verifier_model": args.verifier_model or "생성 모델과 같음",
        },
    }
    for model_id in args.models:
        cs = [c for c in calls if c["model"] == model_id]
        all_ = [o for o in outputs if o["model"] == model_id]
        os_ = [o for o in all_ if o["kept"]]  # 최종으로 남은 리뷰만 (시뮬레이터가 Kafka 로 보낼 것)
        first = [o for o in all_ if o["round"] == 0]
        gen_cs = [c for c in cs if c.get("kind") != "verify"]
        ver_cs = [c for c in cs if c.get("kind") == "verify"]
        in_t = sum(c["input_tokens"] for c in cs)
        out_t = sum(c["output_tokens"] for c in cs)
        # 비용 = 생성 + 검수 호출 합계 (검수 모델이 다르면 단가도 다르므로 호출별 비용을 더한다)
        cost = None if any(c["cost_usd"] is None for c in cs) else sum(c["cost_usd"] for c in cs)
        summary["models"][model_id] = {
            "calls": len(gen_cs),
            "verify_calls": len(ver_cs),
            "failed_calls": sum(not c["ok"] for c in cs),
            "reviews_returned": len(os_),
            "reviews_expected": len(specs),
            # 검수 루프: 1차 통과율, 재생성 호출 수, 최종 버림 수, 문제 종류별 건수(1차 기준)
            "aspect_pass_first": f"{sum(not blocking(o['aspect_problems']) for o in first)}/{len(first)}",
            "extra_added_to_truth": sum(
                any(a["source"] == "verifier" for a in o["truth_aspects"]) for o in os_
            ),
            "aspect_retry_calls": sum(c.get("round", 0) > 0 for c in gen_cs),
            "aspect_dropped": len(specs) - len(os_),
            "aspect_problem_counts_first": {
                k: sum(any(p.startswith(k) for p in o["aspect_problems"]) for o in first)
                for k in ("missing", "extra", "sentiment", "verify_failed")
            },
            "input_tokens": in_t,
            "output_tokens": out_t,
            "cost_usd": None if cost is None else round(cost, 5),
            "cost_per_1000_reviews_usd": None
            if cost is None or not os_
            else round(cost / len(os_) * 1000, 3),
            "latency_sec_mean": round(statistics.mean(c["latency_sec"] for c in gen_cs), 2),
            "reviews_with_problems": sum(bool(o["problems"]) for o in os_),
            "problem_counts": {
                p: sum(p in o["problems"] for o in os_)
                for p in sorted({p for o in os_ for p in o["problems"]})
            },
            "errors": [c["error"] for c in cs if c["error"]],
        }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- 사람 평가 시트: 모델 이름을 가리고 섞는다. 정답 열쇠는 별도 파일(blind_key.json)
    rows = [o for o in outputs if o["kept"]]  # 버린 리뷰는 시트에서 뺀다(outputs.jsonl 에는 남음)
    make_rng(args.seed).shuffle(rows)
    key = {}
    with open(out_dir / "rating_sheet.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "번호",
                "별점",
                "카테고리",
                "지정 속성(속성:감성)",
                "추가된 정답 라벨(검수)",
                "지정 길이",
                "본문",
                "실제 후기 같은가(1~5)",
                "명세를 지켰나(O/X)",
                "메모",
            ]
        )
        for i, o in enumerate(rows, 1):
            s = spec_by_id[o["spec_id"]]
            key[i] = {"model": o["model"], "spec_id": o["spec_id"]}
            w.writerow(
                [
                    i,
                    s.rating,
                    s.product.category,
                    ", ".join(f"{a['aspect']}:{a['sentiment']}" for a in s.aspects),
                    ", ".join(
                        f"{a['aspect']}:{a['sentiment']}"
                        for a in o["truth_aspects"]
                        if a["source"] == "verifier"
                    ),
                    LENGTH_GUIDE[s.length],
                    o["text"],
                    "",
                    "",
                    "",
                ]
            )
    (out_dir / "blind_key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"\n저장: {out_dir}")
    print(json.dumps(summary["models"], ensure_ascii=False, indent=1))
    if any(v["cost_usd"] is None for v in summary["models"].values()):
        print(
            "※ 단가가 없는 모델은 비용이 None 입니다. src/rsim/bench/prices.json 에 Bedrock 도쿄 단가를 넣으면 다시 계산됩니다."
        )
