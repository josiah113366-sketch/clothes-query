"""문서의 클릭 이벤트를 방문·상품 연결용 Silver로 정리한다."""
from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

from pipelines.format_rules import DEFAULT_RULES, FormatRules, RuleConfigError

from .common import collect_unique, run_local, timestamp

CHECK_VERSION = "clicks.v2"
KST = ZoneInfo("Asia/Seoul")


def _normalize(raw: dict, rules: FormatRules) -> dict:
    rules.validate("clickstream", raw)
    row = {field: raw[field] for field in (
        "event_id", "event_type", "member_id", "article_id", "session_id",
    )}
    utc = timestamp(raw, "event_time")
    kst = utc.astimezone(KST)
    return {**row, "event_time_utc": utc.isoformat(), "event_time_kst": kst.isoformat(),
            "event_date_kst": kst.date().isoformat()}


def build_clicks(events: list[dict], rules: FormatRules | None = None) -> dict[str, list[dict]]:
    rules = rules if rules is not None else FormatRules()
    if "clickstream" not in rules.datasets:
        raise RuleConfigError("클릭 데이터셋의 공통 규칙이 없습니다")
    clean, issues, summary = collect_unique(
        events, "clickstream", "event_id", lambda raw: _normalize(raw, rules), CHECK_VERSION)
    summary["output_counts"] = {"click_events": len(clean)}
    summary["format_rules"] = rules.reference()
    return {"click_events": clean, "quarantined_records": issues, "dq_results": [summary]}


def run(input_root: str, output_root: str, input_complete: bool = False,
        rules_path: str | Path | None = None) -> dict:
    rules = FormatRules(DEFAULT_RULES if rules_path is None else rules_path)
    return run_local({"clickstream": input_root}, output_root, "clicks", CHECK_VERSION,
                     lambda rows: build_clicks(rows["clickstream"], rules), input_complete=input_complete,
                     rule_metadata=rules.reference())


def main() -> None:
    parser = argparse.ArgumentParser(description="문서 기준 클릭 JSONL → 로컬 Silver")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--input-complete", action="store_true", help="필요한 전체 클릭 이력을 준비했음을 실행자가 확인")
    parser.add_argument("--rules-path", help="공통 입력 규칙 YAML. 생략하면 저장소 기본 규칙")
    args = parser.parse_args()
    manifest = run(args.input_root, args.output_root, args.input_complete, args.rules_path)
    print(f"클릭 Silver {manifest['status']}: {manifest['output_counts']}")
    print(f"대표 결과: {manifest['manifest_path']}")


if __name__ == "__main__":
    main()
