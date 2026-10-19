"""Silver 리뷰의 기본 일간 집계와 상품·기간·키워드 원문 조회."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta

from . import _uri, _write_text, load_silver, save_gold

OUTPUT_FILE = "part-00000.jsonl"


def _read_scope(silver_root: str, start: date, end: date) -> tuple[dict, dict]:
    days = list(_days(start, end))
    names = [f"year={day:%Y}/month={day:%m}/day={day:%d}/{OUTPUT_FILE}" for day in days]
    manifest = _uri(silver_root, "silver", "reviews", "scopes", f"{start}_{end}", "current.json")
    loaded, reference = load_silver(manifest, {"start_date_kst": str(start), "end_date_kst": str(end)}, names)
    by_day, seen = {}, set()
    for day, name in zip(days, names):
        rows = loaded[name]
        for row in rows:
            if row.get("review_date_kst") != str(day):
                raise ValueError("Silver 리뷰 날짜가 요청 날짜와 다릅니다")
            for field in ("review_id", "product_id"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError("Silver 리뷰·상품 키가 없습니다")
            if row["review_id"] in seen:
                raise ValueError("Silver 요청 범위에 동일 review_id가 두 번 있습니다")
            seen.add(row["review_id"])
            rating = row.get("rating")
            if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
                raise ValueError("Silver 리뷰 별점이 올바르지 않습니다")
        by_day[str(day)] = rows
    return by_day, reference


def _days(start: date, end: date):
    if end < start:
        raise ValueError("end-date가 start-date보다 빠릅니다")
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def aggregate_day(rows: list[dict[str, object]], day: date) -> list[dict[str, object]]:
    """리뷰 1건을 한 번만 세고 1~2점을 낮은 별점으로 집계한다."""
    by_product: dict[str, dict[str, object]] = defaultdict(
        lambda: {"review_count": 0, "rating_sum": 0, "low_rating_count": 0}
    )
    seen: set[str] = set()
    for row in rows:
        review_id = str(row["review_id"])
        # Silver에 동일 리뷰가 두 번 있으면 조용히 두 번 세지 않고 오류를 낸다.
        if review_id in seen:
            raise ValueError("Silver 리뷰에 동일 review_id가 두 번 있습니다")
        seen.add(review_id)
        product_id = str(row["product_id"])
        item = by_product[product_id]
        rating = int(row["rating"])
        item["review_count"] = int(item["review_count"]) + 1
        item["rating_sum"] = int(item["rating_sum"]) + rating
        item["low_rating_count"] = int(item["low_rating_count"]) + int(rating <= 2)

    return [
        {
            "review_date_kst": day.isoformat(),
            "product_id": product_id,
            "review_count": item["review_count"],
            "average_rating": round(int(item["rating_sum"]) / int(item["review_count"]), 2),
            "low_rating_count": item["low_rating_count"],
        }
        for product_id, item in sorted(by_product.items())
    ]


def run_aggregate(silver_root: str, output_root: str, start: date, end: date) -> dict[str, int]:
    by_day, reference = _read_scope(silver_root, start, end)
    result, counts = {}, {}
    for day in _days(start, end):
        rows = aggregate_day(by_day[str(day)], day)
        result[f"year={day:%Y}/month={day:%m}/day={day:%d}/{OUTPUT_FILE}"] = rows
        counts[str(day)] = len(rows)
    # 여러 날짜를 모두 계산한 뒤 실행 묶음 한 개로 공개한다.
    save_gold(_uri(output_root, "gold_a", "review_product_daily", "scopes", f"{start}_{end}"),
              result, {"silver_reviews": reference, "start_date_kst": str(start), "end_date_kst": str(end)})
    return counts


def search_reviews(
    silver_root: str,
    start: date,
    end: date,
    keyword: str,
    product_id: str | None = None,
    limit: int = 50,
) -> tuple[int, list[dict[str, object]]]:
    """Silver 원문에서 부분 문자열 검색. AI 감성 결과는 아직 사용하지 않는다."""
    term = keyword.strip().casefold()
    if not term:
        raise ValueError("keyword가 비어 있습니다")
    if limit < 1:
        raise ValueError("limit는 1 이상이어야 합니다")
    matches: list[dict[str, object]] = []
    by_day, _ = _read_scope(silver_root, start, end)
    for day in _days(start, end):
        for row in by_day[str(day)]:
            if product_id is not None and row["product_id"] != product_id:
                continue
            content = row.get("text")
            if not isinstance(content, str) or term not in content.casefold():
                continue
            matches.append(
                {
                    "review_id": row["review_id"],
                    "product_id": row["product_id"],
                    "product_name": row.get("product_name"),
                    "review_date_kst": row["review_date_kst"],
                    "created_at_kst": row["created_at_kst"],
                    "rating": row["rating"],
                    "text": content,
                }
            )
    matches.sort(key=lambda row: (str(row["created_at_kst"]), str(row["review_id"])), reverse=True)
    return len(matches), matches[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Gold A 리뷰 기본 집계·키워드 검색")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("aggregate", "search"):
        command = commands.add_parser(name)
        command.add_argument("--silver-root", required=True)
        command.add_argument("--start-date", type=date.fromisoformat, required=True)
        command.add_argument("--end-date", type=date.fromisoformat, required=True)
    commands.choices["aggregate"].add_argument("--output-root", required=True)
    query = commands.choices["search"]
    query.add_argument("--product-id")
    query.add_argument("--keyword", required=True)
    query.add_argument("--limit", type=int, default=50)
    query.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "aggregate":
        for day, count in run_aggregate(
            args.silver_root, args.output_root, args.start_date, args.end_date
        ).items():
            print(f"{day}: 상품별 리뷰 집계 {count}행")
    else:
        total, rows = search_reviews(
            args.silver_root, args.start_date, args.end_date, args.keyword, args.product_id, args.limit
        )
        _write_text(
            args.output,
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        )
        # 콘솔에는 리뷰 원문이나 개인 정보를 출력하지 않는다.
        print(f"검색 결과 {total}건 중 {len(rows)}건 저장: {args.output}")


if __name__ == "__main__":
    main()
