"""Silver 리뷰의 기본 일간 집계와 상품·기간·키워드 원문 조회."""

from __future__ import annotations

import argparse
import json
import csv
import io
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from datetime import date, timedelta

from . import (_uri, _read_text, _write_text, read_rows, load_silver, save_gold,
               load_products, connect_reviews, replacement)

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
        product_id = str(row.get("article_id", row.get("product_id")))
        item = by_product[product_id]
        if "article_id" in row:
            item["article_id"], item["product_code"] = row["article_id"], row["product_code"]
        rating = row["rating"]
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise ValueError("별점은 1~5 정수여야 합니다")
        item["review_count"] = int(item["review_count"]) + 1
        item["rating_sum"] = int(item["rating_sum"]) + rating
        item["low_rating_count"] = int(item["low_rating_count"]) + int(rating <= 2)

    return [
        {
            "review_date_kst": day.isoformat(),
            **({"article_id": item["article_id"], "product_code": item["product_code"]}
               if "article_id" in item else {"product_id": product_id}),
            "review_count": item["review_count"],
            "rating_sum": item["rating_sum"],
            "average_rating": ratio(item["rating_sum"], item["review_count"], 4),
            "low_rating_rate": ratio(item["low_rating_count"], item["review_count"]),
            "low_rating_count": item["low_rating_count"],
        }
        for product_id, item in sorted(by_product.items())
    ]


def ratio(numerator: int, denominator: int, places: int = 6) -> float | None:
    if denominator == 0:
        return None
    value = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
    return float(value)


def _connected_scope(silver_root, start, end, products_root=None, mapping_path=None):
    by_day, ref = _read_scope(silver_root, start, end)
    refs = {"silver_reviews": ref, "start_date_kst": str(start), "end_date_kst": str(end)}
    if mapping_path and not products_root:
        raise ValueError("리뷰 매핑에는 상품 기준정보가 필요합니다")
    if products_root:
        products, catalog_ref = load_products(products_root)
        mapping = read_rows(mapping_path) if mapping_path else None
        by_day = {day: connect_reviews(rows, products, mapping) for day, rows in by_day.items()}
        refs.update(silver_products=catalog_ref, product_mapping=mapping_path,
                    product_mapping_rows=mapping or [])
    return by_day, refs


def _check_scope(reprocess, start, end):
    if reprocess and (reprocess["start_date"] < str(start) or reprocess["end_date"] > str(end)):
        raise ValueError("교체 날짜는 전체 Silver 입력 범위 안이어야 합니다")


def run_aggregate(silver_root: str, output_root: str, start: date, end: date,
                  products_root: str | None = None, mapping_path: str | None = None,
                  reprocess: dict | None = None) -> dict[str, int]:
    _check_scope(reprocess, start, end)
    by_day, refs = _connected_scope(silver_root, start, end, products_root, mapping_path)
    result, counts = {}, {}
    for day in _days(start, end):
        rows = aggregate_day(by_day[str(day)], day)
        result[f"year={day:%Y}/month={day:%m}/day={day:%d}/{OUTPUT_FILE}"] = rows
        counts[str(day)] = len(rows)
    saved = save_gold(_uri(output_root, "gold_a", "review_product_daily", "scopes", f"{start}_{end}"),
                      result, refs, reprocess)
    # 부분 재처리도 저장된 전체 범위의 행 수를 반환한다.
    return {str(day): saved["output_counts"][f"year={day:%Y}/month={day:%m}/day={day:%d}/{OUTPUT_FILE}"]
            for day in _days(start, end)}


ASPECTS = {"재질·촉감", "사이즈·핏", "색상·디자인", "품질·내구성", "가격·가성비", "냄새",
           "세탁·관리", "활용성·사용감", "배송", "포장", "교환·환불·CS"}
SCORE_FIELDS = {-2: "score_neg2_count", -1: "score_neg1_count", 0: "score_zero_count",
                1: "score_pos1_count", 2: "score_pos2_count"}
ASPECT_SCHEMA = "score.v1"


def load_analysis(path: str, model_version: str) -> list[dict]:
    if path.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(_read_text(path).lstrip("\ufeff"))))
        converted = []
        for row in rows:
            value = row.get("score")
            if value not in {"-2", "-1", "0", "1", "2"}:
                raise ValueError("모델 score CSV는 -2~2 정수여야 합니다")
            score = int(value)
            converted.append({"review_id": row.get("review_id"), "aspect": row.get("aspect"),
                              "model_version": model_version, "score": score})
        return converted
    return read_rows(path)


def aggregate_aspects(reviews: list[dict], analysis: list[dict], model_version: str) -> tuple[list[dict], dict]:
    if not isinstance(model_version, str) or not model_version.strip():
        raise ValueError("분석 모델 버전이 필요합니다")
    originals = {row["review_id"]: row for row in reviews}
    if len(originals) != len(reviews):
        raise ValueError("분석 연결 대상 리뷰 ID 중복")
    selected, unknown, analyzed, matching_version = {}, set(), set(), False
    for row in analysis:
        review_id, aspect, version = (row.get(field) for field in ("review_id", "aspect", "model_version"))
        if not all(isinstance(value, str) and value.strip() for value in (review_id, aspect, version)):
            raise ValueError("분석 결과의 키·속성·모델 버전이 필요합니다")
        if aspect not in ASPECTS:
            raise ValueError("지원하지 않는 분석 속성")
        score = row.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or score not in SCORE_FIELDS:
            raise ValueError("score는 -2~2 정수여야 합니다. sentiment에서 점수를 추정하지 않습니다")
        if version != model_version:
            continue
        matching_version = True
        if review_id not in originals:
            unknown.add(review_id)
            continue
        key = (review_id, aspect)
        if key in selected and selected[key] != score:
            raise ValueError("동일 리뷰·속성·모델 버전의 분석 내용 충돌")
        selected[key] = score
        analyzed.add(review_id)
    if analysis and not matching_version:
        raise ValueError("입력에 요청한 모델 버전 결과가 없습니다")
    if unknown:
        raise ValueError("분석 결과에 Silver 범위에 없는 review_id가 있습니다")
    buckets = {}
    for (review_id, aspect), score in sorted(selected.items()):
        review = originals[review_id]
        if "article_id" not in review:
            raise ValueError("속성 집계에는 검증된 상품 연결이 필요합니다")
        key = (review["review_date_kst"], review["article_id"], aspect, model_version)
        bucket = buckets.setdefault(key, {"review_date_kst": key[0], "article_id": key[1],
            "product_code": review["product_code"], "aspect": aspect, "model_version": model_version,
            "scored_review_count": 0, "score_sum": 0, **{field: 0 for field in SCORE_FIELDS.values()}})
        bucket["scored_review_count"] += 1
        bucket["score_sum"] += score
        bucket[SCORE_FIELDS[score]] += 1
    for bucket in buckets.values():
        bucket["average_score"] = ratio(bucket["score_sum"], bucket["scored_review_count"], 4)
    coverage = {"review_count": len(originals), "reviews_with_aspect_result": len(analyzed),
                "reviews_without_aspect_result": len(originals) - len(analyzed),
                "analysis_completion_status": "UNVERIFIED",
                "note": "결과 없음은 속성 미언급 또는 미분석일 수 있습니다. 0점으로 세지 않습니다."}
    return [buckets[key] for key in sorted(buckets)], coverage


def _check_score_baseline(base: str) -> None:
    """3분류 결과에 점수 결과를 부분 병합하지 않는다. 0건 기존 결과도 버전으로 판별한다."""
    try:
        previous = json.loads(_read_text(_uri(base, "current.json")))
    except FileNotFoundError as exc:
        raise ValueError("점수 기반 전체 집계를 먼저 실행한 뒤 부분 재처리하세요") from exc
    if not isinstance(previous, dict) or previous.get("inputs", {}).get("aspect_schema") != ASPECT_SCHEMA:
        raise ValueError("기존 속성 결과 형식이 다릅니다. 원래 점수 입력으로 전체 재집계하세요")
    required = set(SCORE_FIELDS.values()) | {"scored_review_count", "score_sum", "average_score"}
    legacy = {"mentioned_review_count", "positive_review_count", "neutral_review_count", "negative_review_count", "negative_rate"}
    path = previous.get("outputs", {}).get("review_aspect_daily.jsonl")
    if not isinstance(path, str):
        raise ValueError("기존 점수 집계 파일 경로가 없습니다")
    if any(not required.issubset(row) or legacy.intersection(row) for row in read_rows(path)):
        raise ValueError("기존 속성 결과에 다른 형식이 섞여 있습니다. 전체 재집계하세요")


def run_aspects(silver_root: str, output_root: str, start: date, end: date, products_root: str,
                analysis_path: str, model_version: str, mapping_path: str | None = None,
                reprocess: dict | None = None) -> dict:
    _check_scope(reprocess, start, end)
    base = _uri(output_root, "gold_a", "review_aspect_daily", "scopes", f"{start}_{end}")
    if reprocess:
        _check_score_baseline(base)
    by_day, refs = _connected_scope(silver_root, start, end, products_root, mapping_path)
    analysis = load_analysis(analysis_path, model_version)
    rows, coverage = aggregate_aspects([row for group in by_day.values() for row in group], analysis, model_version)
    refs.update(analysis_path=analysis_path, model_version=model_version, analysis_coverage=coverage,
                aspect_schema=ASPECT_SCHEMA, score_policy="integer-minus2-plus2.v1")
    if reprocess:
        reprocess = {**reprocess, "model_version": model_version}
    return save_gold(base, {"review_aspect_daily.jsonl": rows}, refs, reprocess)


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
    aggregate = commands.choices["aggregate"]
    aggregate.add_argument("--products-root")
    aggregate.add_argument("--mapping-path")
    aspect = commands.add_parser("aspects")
    for option in ("silver-root", "output-root", "products-root", "analysis-path", "model-version"):
        aspect.add_argument("--" + option, required=True)
    aspect.add_argument("--start-date", type=date.fromisoformat, required=True)
    aspect.add_argument("--end-date", type=date.fromisoformat, required=True)
    aspect.add_argument("--mapping-path")
    for command in (aggregate, aspect):
        command.add_argument("--replace-start-date")
        command.add_argument("--replace-end-date")
        command.add_argument("--article-id", action="append")
    args = parser.parse_args()
    if args.command == "aggregate":
        for day, count in run_aggregate(
            args.silver_root, args.output_root, args.start_date, args.end_date, args.products_root, args.mapping_path,
            replacement(args.replace_start_date, args.replace_end_date, args.article_id)
        ).items():
            print(f"{day}: 상품별 리뷰 집계 {count}행")
    elif args.command == "aspects":
        result = run_aspects(args.silver_root, args.output_root, args.start_date, args.end_date,
                             args.products_root, args.analysis_path, args.model_version, args.mapping_path,
                             replacement(args.replace_start_date, args.replace_end_date, args.article_id))
        print("속성 집계 완료: " + result["manifest_path"])
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
