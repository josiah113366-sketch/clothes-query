"""Silver 리뷰의 기본 일간 집계와 상품·기간·키워드 원문 조회."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

OUTPUT_FILE = "part-00000.jsonl"


def _uri(root: str, *parts: str) -> str:
    return "/".join((root.rstrip("/"), *(part.strip("/") for part in parts)))


def _s3_location(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("S3 경로는 s3://버킷/접두사 형식이어야 합니다")
    return parsed.netloc, parsed.path.lstrip("/")


def _read_text(uri: str) -> str:
    if uri.startswith("s3://"):
        import boto3

        bucket, key = _s3_location(uri)
        return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read().decode(
            "utf-8"
        )
    return Path(uri).read_text(encoding="utf-8")


def _write_text(uri: str, body: str) -> None:
    if uri.startswith("s3://"):
        import boto3

        bucket, key = _s3_location(uri)
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="application/x-ndjson"
        )
        return
    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".gold-a-", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(body)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_day(silver_root: str, day: date) -> list[dict[str, object]]:
    uri = _uri(silver_root, "silver", "reviews", f"dt={day.isoformat()}", OUTPUT_FILE)
    if not uri.startswith("s3://") and not Path(uri).exists():
        raise FileNotFoundError(f"Silver 리뷰 날짜 파일이 없습니다: {uri}")
    rows: list[dict[str, object]] = []
    for line_no, line in enumerate(_read_text(uri).splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{uri}:{line_no}: JSON 파싱 실패") from exc
        if not isinstance(row, dict) or row.get("review_date_kst") != day.isoformat():
            raise ValueError(f"{uri}:{line_no}: Silver 리뷰 날짜가 파일 경로와 다릅니다")
        if not isinstance(row.get("review_id"), str) or not isinstance(row.get("product_id"), str):
            raise ValueError(f"{uri}:{line_no}: 리뷰·상품 ID가 없습니다")
        rating = row.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise ValueError(f"{uri}:{line_no}: 별점이 올바르지 않습니다")
        rows.append(row)
    return rows


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
    counts: dict[str, int] = {}
    for day in _days(start, end):
        result = aggregate_day(_read_day(silver_root, day), day)
        body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in result)
        uri = _uri(output_root, "gold_a", "review_product_daily", f"dt={day}", OUTPUT_FILE)
        # 재처리: 해당 날짜의 Gold A 파일을 교체한다. 0건이면 빈 파일로 교체한다.
        _write_text(uri, body)
        counts[day.isoformat()] = len(result)
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
    for day in _days(start, end):
        for row in _read_day(silver_root, day):
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
