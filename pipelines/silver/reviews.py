"""review.v2 Bronze JSONL을 KST 날짜별 Silver 리뷰로 정제한다.

현재 리뷰 시뮬레이터의 ``--sink lake`` 출력 경로를 입력으로 쓴다. 운영용
``reviews/``만 읽고 의도/검수 라벨이 있는 ``reviews_truth/``는 읽지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
OUTPUT_FILE = "part-00000.jsonl"


def _uri(root: str, *parts: str) -> str:
    return "/".join((root.rstrip("/"), *(part.strip("/") for part in parts)))


def _s3_location(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("S3 경로는 s3://버킷/접두사 형식이어야 합니다")
    return parsed.netloc, parsed.path.lstrip("/")


def _input_uris(root: str, utc_day: date) -> list[str]:
    # 최신 year/month/day와 기존 dt를 모두 읽고, 이후 review_id로 중복 처리한다.
    prefixes = [
        _uri(root, "reviews", f"year={utc_day:%Y}", f"month={utc_day:%m}", f"day={utc_day:%d}"),
        _uri(root, "reviews", f"dt={utc_day.isoformat()}"),
    ]
    paths = set()
    for prefix in prefixes:
        if prefix.startswith("s3://"):
            import boto3

            bucket, key = _s3_location(prefix)
            objects = boto3.client("s3").get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=key.rstrip("/") + "/"
            )
            paths.update(
                f"s3://{bucket}/{item['Key']}"
                for page in objects
                for item in page.get("Contents", [])
                if item["Key"].endswith(".jsonl")
            )
        else:
            paths.update(str(path) for path in Path(prefix).glob("*.jsonl"))
    return sorted(paths)


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
    # 같은 날짜를 재처리하면 파일 하나를 교체한다. 쓰다 중단돼도 기존 결과는 남는다.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".reviews-", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(body)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field}는 시간대가 있는 ISO 시각이어야 합니다")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field}는 시간대가 있는 ISO 시각이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}에 시간대가 없습니다")
    return parsed


def normalize_review(raw: dict[str, object]) -> dict[str, object]:
    """현재 확정된 review.v2 작성 이벤트를 운영용 Silver 모양으로 바꾼다."""
    if raw.get("schema_version") != "review.v2" or raw.get("event_type") != "review_created":
        raise ValueError("지원하지 않는 리뷰 스키마 또는 이벤트 종류입니다")
    for field in ("review_id", "event_id", "product_id", "text"):
        if not isinstance(raw.get(field), str) or not str(raw[field]).strip():
            raise ValueError(f"{field}가 비어 있습니다")
    rating = raw.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ValueError("rating은 1~5의 정수여야 합니다")
    created = _timestamp(raw.get("created_at"), "created_at")
    emitted = _timestamp(raw.get("emitted_at"), "emitted_at")
    kst = created.astimezone(KST)
    # 원천 product_id를 보존한다. 값만 보고 article_id/product_code로 임의 변환하지 않는다.
    # 개인 식별용 member_id와 평가 전용 라벨은 분석용 출력에 복사하지 않는다.
    return {
        "review_id": raw["review_id"],
        "event_id": raw["event_id"],
        "product_id": raw["product_id"],
        "product_name": raw.get("product_name"),
        "category": raw.get("category"),
        "order_id": raw.get("order_id"),
        "created_at_utc": created.astimezone(UTC).isoformat(),
        "created_at_kst": kst.isoformat(),
        "review_date_kst": kst.date().isoformat(),
        "emitted_at_utc": emitted.astimezone(UTC).isoformat(),
        "rating": rating,
        "text": raw["text"],
        "option_size": raw.get("option_size"),
        "option_color": raw.get("option_color"),
        "has_photo": raw.get("has_photo"),
        "source": raw.get("source"),
    }


def build_reviews(input_root: str, start: date, end: date) -> dict[str, list[dict[str, object]]]:
    """KST 날짜 범위에 속한 리뷰만 남기고 review_id별 최신 재생성 1건을 선택한다."""
    if end < start:
        raise ValueError("end-date가 start-date보다 빠릅니다")
    selected: dict[str, dict[str, object]] = {}
    found_input = False
    # KST 하루의 앞부분은 전날 UTC 폴더에 있으므로 시작일 하루 전부터 읽는다.
    utc_day = start - timedelta(days=1)
    while utc_day <= end:
        for uri in _input_uris(input_root, utc_day):
            found_input = True
            for line_no, line in enumerate(_read_text(uri).splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise ValueError("JSON 객체가 아닙니다")
                    row = normalize_review(raw)
                except (json.JSONDecodeError, ValueError) as exc:
                    # 원문·회원값을 오류 메시지에 싣지 않는다.
                    raise ValueError(f"{uri}:{line_no}: {exc}") from exc
                day = date.fromisoformat(str(row["review_date_kst"]))
                if not start <= day <= end:
                    continue
                review_id = str(row["review_id"])
                previous = selected.get(review_id)
                # 같은 리뷰가 재전송·재생성됐으면 emitted_at이 가장 늦은 1건만 남긴다.
                if previous is None or str(row["emitted_at_utc"]) > str(previous["emitted_at_utc"]):
                    selected[review_id] = row
                elif str(row["emitted_at_utc"]) == str(previous["emitted_at_utc"]) and row != previous:
                    raise ValueError(f"review_id {review_id}: 같은 전송 시각에 서로 다른 내용이 있습니다")
        utc_day += timedelta(days=1)

    if not found_input:
        raise FileNotFoundError("대상 UTC 날짜 범위에 운영 리뷰 JSONL 파일이 없습니다")

    by_day: dict[str, list[dict[str, object]]] = {}
    day = start
    while day <= end:
        # 원본이 0건인 날짜도 빈 결과를 써야 과거 집계가 남지 않는다.
        by_day[day.isoformat()] = []
        day += timedelta(days=1)
    for row in selected.values():
        by_day[str(row["review_date_kst"])].append(row)
    for rows in by_day.values():
        rows.sort(key=lambda row: (str(row["created_at_utc"]), str(row["review_id"])))
    return by_day


def run(input_root: str, output_root: str, start: date, end: date) -> dict[str, int]:
    if input_root.rstrip("/") == output_root.rstrip("/"):
        raise ValueError("입력과 출력 루트는 서로 달라야 합니다")
    by_day = build_reviews(input_root, start, end)
    counts: dict[str, int] = {}
    for day, rows in by_day.items():
        body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
        # 재처리: 지정 날짜의 기존 파일을 새 결과로 교체하며 뒤에 덧붙이지 않는다.
        _write_text(_uri(output_root, "silver", "reviews", f"dt={day}", OUTPUT_FILE), body)
        counts[day] = len(rows)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="review.v2 Bronze → KST Silver 리뷰")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    for day, count in run(args.input_root, args.output_root, args.start_date, args.end_date).items():
        print(f"{day}: Silver 리뷰 {count}건")


if __name__ == "__main__":
    main()
