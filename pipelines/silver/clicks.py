"""문서의 클릭 이벤트를 방문·상품 연결용 Silver로 정리한다."""
from __future__ import annotations

import argparse
from zoneinfo import ZoneInfo

from .common import RowError, collect_unique, required_text, run_local, timestamp

CHECK_VERSION = "clicks.v1"
KST = ZoneInfo("Asia/Seoul")


def _normalize(raw: dict) -> dict:
    row = {field: required_text(raw, field) for field in (
        "event_id", "event_type", "member_id", "article_id", "session_id",
    )}
    if row["event_type"] not in {"view", "cart_add"}:
        raise RowError("event_type", "INVALID_VALUE", "조회·장바구니 이벤트만 지원합니다")
    utc = timestamp(raw, "event_time")
    kst = utc.astimezone(KST)
    return {**row, "event_time_utc": utc.isoformat(), "event_time_kst": kst.isoformat(),
            "event_date_kst": kst.date().isoformat()}


def build_clicks(events: list[dict]) -> dict[str, list[dict]]:
    clean, issues, summary = collect_unique(events, "clickstream", "event_id", _normalize, CHECK_VERSION)
    summary["output_counts"] = {"click_events": len(clean)}
    return {"click_events": clean, "quarantined_records": issues, "dq_results": [summary]}


def run(input_root: str, output_root: str) -> dict:
    return run_local({"clickstream": input_root}, output_root, "clicks", CHECK_VERSION,
                     lambda rows: build_clicks(rows["clickstream"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="문서 기준 클릭 JSONL → 로컬 Silver")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    manifest = run(args.input_root, args.output_root)
    print(f"클릭 Silver {manifest['status']}: {manifest['output_counts']}")
    print(f"대표 결과: {manifest['manifest_path']}")


if __name__ == "__main__":
    main()
