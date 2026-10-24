"""회원 CDC Bronze를 읽어 지정 UTC 날짜까지의 회원 현재 상태를 만든다."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pipelines.format_rules import DEFAULT_RULES, FormatRules, RuleConfigError
from pipelines.timestamps import parse_iso_datetime

from .common import RowError, collect_latest, decode_record, publish_bundle

KST = ZoneInfo("Asia/Seoul")
PARTITION = re.compile(
    r"(?:^|/)year=(\d{4})/month=(\d{2})/day=(\d{2})/"
    r"members-events\+\d+\+\d+\.json$"
)
OUTPUT_FILE = "part-00000.jsonl"
CHECK_VERSION = "members.v2"


def _location(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("S3 입력은 s3://버킷/접두사 형식이어야 합니다")
    return parsed.netloc, parsed.path.lstrip("/")


def _partition_day(path: str) -> date | None:
    match = PARTITION.search(path.replace("\\", "/"))
    if match is None:
        return None
    try:
        return date.fromisoformat("-".join(match.groups()))
    except ValueError as exc:
        raise ValueError("Bronze 경로에 올바르지 않은 날짜가 있습니다") from exc


def _input_files(root: str, through: date) -> list[str]:
    if root.startswith("s3://"):
        import boto3

        bucket, prefix = _location(root)
        pages = boto3.client("s3").get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix.rstrip("/") + "/"
        )
        paths = (
            f"s3://{bucket}/{item['Key']}"
            for page in pages
            for item in page.get("Contents", [])
        )
    else:
        paths = (str(path) for path in Path(root).rglob("*.json"))
    return sorted(
        path for path in paths if (day := _partition_day(path)) is not None and day <= through
    )


def _lines(uri: str):
    if uri.startswith("s3://"):
        import boto3

        bucket, key = _location(uri)
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"]
        for line in body.iter_lines():
            yield line.decode("utf-8")
    else:
        with Path(uri).open(encoding="utf-8") as handle:
            yield from handle


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise RowError(field, "TYPE_MISMATCH", "시간대가 있는 ISO 시각이어야 합니다")
    try:
        result = parse_iso_datetime(value)
    except ValueError as exc:
        raise RowError(field, "TYPE_MISMATCH", "시간대가 있는 ISO 시각이어야 합니다") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise RowError(field, "INVALID_VALUE", "시간대가 없습니다")
    return result


def _normalize(raw: dict[str, object], rules: FormatRules) -> tuple[str, int, dict[str, object]]:
    # 업무 필드 기준은 YAML에 모으고 CDC 변경 종류·순서는 Silver에서 검사한다.
    rules.validate("members", raw)
    if raw.get("__op") not in ("r", "c", "u"):
        raise RowError("__op", "INVALID_VALUE", "지원하지 않는 CDC 변경 종류입니다")
    source_ts = raw.get("__source_ts_ms")
    if isinstance(source_ts, bool) or not isinstance(source_ts, int) or source_ts < 0:
        raise RowError("__source_ts_ms", "INVALID_VALUE", "__source_ts_ms는 0 이상의 정수여야 합니다")
    signup = _timestamp(raw.get("signup_at"), "signup_at")
    created = _timestamp(raw.get("created_at"), "created_at")
    withdrawn_value = raw.get("withdrawn_at")
    withdrawn = (
        None if withdrawn_value is None else _timestamp(withdrawn_value, "withdrawn_at")
    )
    row = {
        "member_id": raw["member_id"],
        "age_band": raw["age_band"],
        "gender": raw["gender"],
        "signup_channel": raw["signup_channel"],
        "region_sigungu": raw["region_sigungu"],
        "marketing_consent": raw["marketing_consent"],
        "status": raw["status"],
        "signup_at_utc": signup.astimezone(timezone.utc).isoformat(),
        "signup_at_kst": signup.astimezone(KST).isoformat(),
        "created_at_utc": created.astimezone(timezone.utc).isoformat(),
        "withdrawn_at_utc": None if withdrawn is None else withdrawn.astimezone(timezone.utc).isoformat(),
        "source_ts_ms": source_ts,
    }
    return str(raw["member_id"]), source_ts, row


def build_quality(input_root: str, through: date, rules: FormatRules | None = None) -> tuple[dict, list[str]]:
    rules = rules if rules is not None else FormatRules()
    if "members" not in rules.datasets:
        raise RuleConfigError("회원 데이터셋의 공통 규칙이 없습니다")
    files = _input_files(input_root, through)
    if not files:
        raise FileNotFoundError("지정 날짜까지의 회원 Bronze 파일이 없습니다")
    inputs = [decode_record(line, uri, number)
              for uri in files for number, line in enumerate(_lines(uri), 1) if line.strip()]
    rows, issues, summary = collect_latest(
        inputs, "members", "member_id", lambda raw: _normalize(raw, rules)[2], "source_ts_ms", CHECK_VERSION)
    summary["through_date_utc"] = through.isoformat()
    summary["format_rules"] = rules.reference()
    return {"members_current": rows, "quarantined_records": issues, "dq_results": [summary]}, files


def build_current(input_root: str, through: date) -> tuple[list[dict[str, object]], int]:
    # 기존 계산 호출은 유지한다. 후속 집계는 품질 결과까지 담긴 manifest를 읽어야 한다.
    result, files = build_quality(input_root, through)
    return result["members_current"], len(files)


def _write_text(uri: str, body: str) -> None:
    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".members-", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(body, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(input_root: str, output_root: str, through: date,
        rules_path: str | Path | None = None) -> tuple[int, int, str]:
    rules = FormatRules(DEFAULT_RULES if rules_path is None else rules_path)
    if output_root.startswith("s3://"):
        raise ValueError("첫 버전은 로컬 Silver 출력만 지원합니다")
    if not input_root.startswith("s3://"):
        source, target = Path(input_root).resolve(), Path(output_root).resolve()
        if source == target or source in target.parents or target in source.parents:
            raise ValueError("입력과 출력 경로는 서로 겹치지 않아야 합니다")
    result, files = build_quality(input_root, through, rules)
    base = str(Path(output_root).resolve() / "silver" / "members_current" / f"as_of={through}")
    manifest = publish_bundle(base, {name + ".jsonl": rows for name, rows in result.items()}, {
        "status": result["dq_results"][0]["status"], "check_version": CHECK_VERSION,
        "format_rules": rules.reference(),
        "through_date_utc": through.isoformat(), "input_files": files,
        "input_count": result["dq_results"][0]["input_count"],
    }, _write_text)
    return len(result["members_current"]), len(files), manifest["outputs"]["members_current.jsonl"]


def main() -> None:
    parser = argparse.ArgumentParser(description="회원 CDC Bronze → 회원 현재 상태 Silver")
    parser.add_argument("--input-root", required=True, help="bronze_v2/members-events 경로")
    parser.add_argument("--output-root", required=True, help="로컬 결과 루트")
    parser.add_argument("--through-date", type=date.fromisoformat, required=True, help="UTC 수집 날짜")
    parser.add_argument("--rules-path", help="공통 입력 규칙 YAML. 생략하면 저장소 기본 규칙")
    args = parser.parse_args()
    count, files, path = run(args.input_root, args.output_root, args.through_date, args.rules_path)
    print(f"회원 Bronze {files}개 파일 → Silver 현재 회원 {count}행: {path}")
    print(f"품질·완료 상태 확인: {Path(args.output_root).resolve() / 'silver/members_current' / f'as_of={args.through_date}' / 'current.json'}")


if __name__ == "__main__":
    main()
