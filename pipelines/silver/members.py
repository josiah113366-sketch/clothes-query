"""회원 CDC Bronze를 읽어 지정 UTC 날짜까지의 회원 현재 상태를 만든다."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
PARTITION = re.compile(
    r"(?:^|/)year=(\d{4})/month=(\d{2})/day=(\d{2})/"
    r"members-events\+\d+\+\d+\.json$"
)
OUTPUT_FILE = "part-00000.jsonl"
FIELDS = (
    "member_id",
    "age_band",
    "gender",
    "signup_channel",
    "region_sigungu",
    "marketing_consent",
    "status",
)


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
        raise ValueError(f"{field}는 시간대가 있는 ISO 시각이어야 합니다")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field}는 시간대가 있는 ISO 시각이어야 합니다") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field}에 시간대가 없습니다")
    return result


def _normalize(raw: dict[str, object]) -> tuple[str, int, dict[str, object]]:
    for field in FIELDS:
        value = raw.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"{field}가 비어 있습니다")
    if not isinstance(raw["member_id"], str):
        raise ValueError("member_id는 문자열이어야 합니다")
    if not isinstance(raw["marketing_consent"], bool):
        raise ValueError("marketing_consent는 boolean이어야 합니다")
    if raw["status"] not in ("ACTIVE", "WITHDRAWN"):
        raise ValueError("지원하지 않는 회원 상태입니다")
    if raw.get("__op") not in ("r", "c", "u"):
        raise ValueError("지원하지 않는 CDC 변경 종류입니다")
    source_ts = raw.get("__source_ts_ms")
    if isinstance(source_ts, bool) or not isinstance(source_ts, int) or source_ts < 0:
        raise ValueError("__source_ts_ms는 0 이상의 정수여야 합니다")
    signup = _timestamp(raw.get("signup_at"), "signup_at")
    created = _timestamp(raw.get("created_at"), "created_at")
    withdrawn_value = raw.get("withdrawn_at")
    withdrawn = (
        None if withdrawn_value is None else _timestamp(withdrawn_value, "withdrawn_at")
    )
    if (raw["status"] == "WITHDRAWN") != (withdrawn is not None):
        raise ValueError("status와 withdrawn_at이 일치하지 않습니다")
    row = {
        "member_id": raw["member_id"],
        "age_band": raw["age_band"],
        "gender": raw["gender"],
        "signup_channel": raw["signup_channel"],
        "region_sigungu": raw["region_sigungu"],
        "marketing_consent": raw["marketing_consent"],
        "status": raw["status"],
        "signup_at_utc": signup.astimezone(UTC).isoformat(),
        "signup_at_kst": signup.astimezone(KST).isoformat(),
        "created_at_utc": created.astimezone(UTC).isoformat(),
        "withdrawn_at_utc": None if withdrawn is None else withdrawn.astimezone(UTC).isoformat(),
        "source_ts_ms": source_ts,
    }
    return str(raw["member_id"]), source_ts, row


def build_current(input_root: str, through: date) -> tuple[list[dict[str, object]], int]:
    files = _input_files(input_root, through)
    if not files:
        raise FileNotFoundError("지정 날짜까지의 회원 Bronze 파일이 없습니다")
    current: dict[str, tuple[int, dict[str, object]]] = {}
    for uri in files:
        for line_no, line in enumerate(_lines(uri), 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("JSON 객체가 아닙니다")
                member_id, source_ts, row = _normalize(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                # 원본에는 회원 데이터가 있으므로 오류에 행 내용은 넣지 않는다.
                raise ValueError(f"Bronze 파일 {uri}의 {line_no}번째 행: {exc}") from exc
            previous = current.get(member_id)
            if previous is None or source_ts > previous[0]:
                current[member_id] = (source_ts, row)
            elif source_ts == previous[0] and row != previous[1]:
                raise ValueError("같은 회원의 동일 원천 시각에 서로 다른 상태가 있습니다")
    return [current[member_id][1] for member_id in sorted(current)], len(files)


def run(input_root: str, output_root: str, through: date) -> tuple[int, int, str]:
    if output_root.startswith("s3://"):
        raise ValueError("첫 버전은 로컬 Silver 출력만 지원합니다")
    if input_root.rstrip("/\\") == output_root.rstrip("/\\"):
        raise ValueError("입력과 출력 경로는 달라야 합니다")
    rows, file_count = build_current(input_root, through)
    path = Path(output_root) / "silver" / "members_current" / f"as_of={through}" / OUTPUT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # 재실행 때 추가하지 않고 해당 시점의 전체 결과를 교체한다.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".members-", delete=False
    ) as handle:
        temporary = Path(handle.name)
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(rows), file_count, str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="회원 CDC Bronze → 회원 현재 상태 Silver")
    parser.add_argument("--input-root", required=True, help="bronze/members-events 경로")
    parser.add_argument("--output-root", required=True, help="로컬 결과 루트")
    parser.add_argument("--through-date", type=date.fromisoformat, required=True, help="UTC 수집 날짜")
    args = parser.parse_args()
    count, files, path = run(args.input_root, args.output_root, args.through_date)
    print(f"회원 Bronze {files}개 파일 → Silver 현재 회원 {count}행: {path}")


if __name__ == "__main__":
    main()
