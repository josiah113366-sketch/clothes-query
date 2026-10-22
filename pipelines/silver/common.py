"""Silver 로컬 입력·단일 행 검사·완료된 결과 묶음 저장을 공유한다."""
from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pipelines.format_rules import FormatError


class RowError(ValueError):
    def __init__(self, field: str, code: str, message: str):
        super().__init__(message)
        self.field, self.code = field, code


def required_text(row: dict, field: str) -> str:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RowError(field, "MISSING_FIELD", "필수 정보가 없습니다")
    if not isinstance(value, str):
        raise RowError(field, "TYPE_MISMATCH", "문자열이어야 합니다")
    return value


def timestamp(row: dict, field: str) -> datetime:
    value = required_text(row, field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise RowError(field, "TYPE_MISMATCH", "ISO 시각이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RowError(field, "INVALID_VALUE", "시간대가 없습니다")
    return parsed.astimezone(timezone.utc)


def integer(row: dict, field: str, minimum: int | None = None) -> int:
    value = row.get(field)
    if value is None:
        raise RowError(field, "MISSING_FIELD", "필수 정보가 없습니다")
    if isinstance(value, bool) or not isinstance(value, int):
        raise RowError(field, "TYPE_MISMATCH", "정수여야 합니다")
    if minimum is not None and value < minimum:
        raise RowError(field, "INVALID_VALUE", "허용 최솟값보다 작습니다")
    return value


def collect_unique(rows: list[dict], name: str, key_field: str, normalize,
                   check_version: str) -> tuple[list[dict], list[dict], dict]:
    """클릭·상품 스냅샷의 정상 중복, 내용 충돌, 행 오류를 구분한다."""
    groups, normalized, errors = defaultdict(list), {}, {}

    def key_of(raw):
        value = raw.get(key_field) if isinstance(raw, dict) else None
        return value if not isinstance(value, bool) and isinstance(value, (str, int)) else None

    def reject(index, field, code, reason):
        raw = rows[index]
        category = code if code in {"PENDING_REFERENCE", "DEPENDENCY_BLOCKED"} else (
            "CONFLICT" if code == "CONTENT_CONFLICT" else "INVALID"
        )
        issue = {
            "source_dataset": name, "source_row_number": index + 1,
            "record_key": key_of(raw), "field": field, "error_code": code,
            "reason": reason, "category": category, "check_version": check_version,
        }
        if isinstance(raw, dict) and isinstance(raw.get("_input_source"), dict):
            source = raw["_input_source"]
            if isinstance(source.get("file"), str) and isinstance(source.get("line"), int):
                issue.update(source_file=source["file"], source_line=source["line"])
        errors.setdefault(index, issue)

    for index, raw in enumerate(rows):
        if (key := key_of(raw)) is not None:
            groups[key].append(index)
        if not isinstance(raw, dict):
            reject(index, "record", "TYPE_MISMATCH", "객체 형태의 행이어야 합니다")
            continue
        if raw.get("_input_error"):
            reject(index, "record", raw["_input_error"], "업무 행 JSON 객체를 읽을 수 없습니다")
            continue
        try:
            normalized[index] = normalize(raw)
        except (RowError, FormatError) as exc:
            reject(index, exc.field, exc.code, str(exc))
            if isinstance(exc, FormatError):
                errors[index]["rule_id"] = exc.rule_id

    selected = {}
    for key, indices in groups.items():
        if any(index in errors for index in indices):
            for index in indices:
                reject(index, key_field, "DEPENDENCY_BLOCKED", "같은 키의 오류 행이 있어 결과를 보류합니다")
        elif any(normalized[index] != normalized[indices[0]] for index in indices[1:]):
            for index in indices:
                reject(index, key_field, "CONTENT_CONFLICT", "동일 키의 업무 내용이 다릅니다")
        else:
            selected[key] = normalized[indices[0]]
    clean = sorted(selected.values(), key=lambda row: row[key_field])
    issues = [errors[index] for index in sorted(errors)]
    summary = {
        "source_dataset": name, "check_name": "record_processing", "check_version": check_version,
        "status": "INCOMPLETE" if issues else "PASS", "input_count": len(rows),
        "accepted_count": len(clean), "quarantined_count": len(issues),
        "duplicate_count": len(rows) - len(issues) - len(clean),
        "conflict_count": sum(issue["category"] == "CONFLICT" for issue in issues),
        "pending_count": sum(issue["category"] == "PENDING_REFERENCE" for issue in issues),
        "affected_record_keys": sorted({str(issue["record_key"]) for issue in issues if issue["record_key"] is not None}),
        "source_row_numbers": [issue["source_row_number"] for issue in issues],
    }
    return clean, issues, summary


def kafka_reference(raw: dict) -> dict:
    """제안된 추적 필드만 검사한다. 누락을 추정하지 않고 업무 품질과 분리한다."""
    fields = ("kafka_topic", "kafka_partition", "kafka_offset",
              "kafka_timestamp", "kafka_timestamp_type")
    if not any(field in raw for field in fields):
        return {"status": "MISSING", "errors": []}
    values, errors = {}, []
    for field in fields:
        value = raw.get(field)
        valid = False
        if field == "kafka_topic":
            valid = isinstance(value, str) and bool(value.strip())
        elif field in {"kafka_partition", "kafka_offset"}:
            valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        elif field == "kafka_timestamp_type":
            valid = value in ("CreateTime", "LogAppendTime")
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
                valid = parsed.tzinfo is not None and parsed.utcoffset() is not None
            except ValueError:
                pass
        if valid:
            values[field.removeprefix("kafka_")] = value
        else:
            errors.append(field)
    return {"status": "VALID" if not errors else "INVALID", **values, "errors": errors}


def kafka_observations(rows: list[dict]) -> dict:
    """관측 범위이며 연속성·입수 완료·A/B 일치의 증명은 아니다."""
    counts = {"VALID": 0, "INVALID": 0, "MISSING": 0}
    partitions = {}
    for row in rows:
        ref = row.get("_input_source", {}).get("kafka", {"status": "MISSING"})
        counts[ref["status"]] += 1
        if not all(field in ref for field in ("topic", "partition", "offset")):
            continue
        offsets = partitions.setdefault((ref["topic"], ref["partition"]), [])
        offsets.append(ref["offset"])
    return {"contract": "kafka-trace.draft.v1", "coverage_status": "UNVERIFIED",
            "row_counts": counts, "partitions": [
                {"topic": topic, "partition": partition, "min_offset": min(offsets),
                 "max_offset": max(offsets), "row_count": len(offsets),
                 "unique_offset_count": len(set(offsets))}
                for (topic, partition), offsets in sorted(partitions.items())]}


def load_jsonl(location: str, allow_cdc: bool = False) -> tuple[list[dict], list[str]]:
    """지정한 파일/폴더를 읽고 원본 파일 위치와 줄 번호를 보존한다."""
    root = Path(location).resolve()
    files = sorted(path for path in root.rglob("*")
                   if path.is_file() and path.suffix in {".json", ".jsonl"}) if root.is_dir() else [root]
    if not files:
        raise FileNotFoundError("입력 폴더에 JSONL 파일이 없습니다")
    rows = []
    for path in files:
        # 파일/인코딩 읽기 실패는 실행 실패로 전달한다. 0건 입력으로 바꾸지 않는다.
        with path.open(encoding="utf-8-sig") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                error = None
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    raw, error = {}, "PARSE_ERROR"
                if not isinstance(raw, dict):
                    raw, error = {}, "TYPE_MISMATCH"
                # 실제 CDC 해석이 연결된 것처럼 임의로 op/after를 처리하지 않는다.
                if any(field in raw for field in ("after", "before", "payload", "op")) or (
                    "__op" in raw and not allow_cdc
                ):
                    raise ValueError("CDC 입력은 업무 행으로 변환한 뒤 전달해야 합니다")
                source = {"file": str(path), "line": number}
                if allow_cdc:
                    source["kafka"] = kafka_reference(raw)
                rows.append({**raw, "_input_source": source,
                             "_input_error": error})
    return rows, [str(path) for path in files]


def run_local(locations: dict[str, str], output_root: str, dataset: str,
              check_version: str, build, input_complete: bool = False,
              rule_metadata: dict | None = None) -> dict:
    """입력 전체를 계산하고, 결과 묶음 저장 완료 후 current.json만 원자적으로 교체한다."""
    if any("://" in location for location in (*locations.values(), output_root)):
        raise ValueError("이번 입출력은 로컬 경로만 지원합니다")
    root = Path(output_root).resolve()
    for location in locations.values():
        source = Path(location).resolve()
        if source == root or source in root.parents or root in source.parents:
            raise ValueError("입력과 출력 경로는 서로 겹치지 않아야 합니다")
    loaded, sources = {}, {}
    for name, location in locations.items():
        loaded[name], sources[name] = load_jsonl(location, allow_cdc=dataset == "transactions")
    result = build(loaded)

    base = root / "silver" / dataset
    runs = base / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="run-", dir=runs))
    fixed_manifest = snapshot / "manifest.json"
    temporary = None
    try:
        # 업무 시각이 아닌 이번 검사 완료 시각. 기존 업무 출력은 변경하지 않는다.
        checked_at = datetime.now(timezone.utc).isoformat()
        if dataset == "transactions":
            result["order_amount_checks"] = [
                {**row, "run_id": snapshot.name, "checked_at": checked_at,
                 "source_manifest": str(fixed_manifest)}
                for row in result["order_amount_checks"]
            ]
        paths = {}
        for name, rows in result.items():
            path = snapshot / f"{name}.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                    for row in rows), encoding="utf-8")
            paths[name] = str(path)
        manifest = {
            "status": "INCOMPLETE" if result["quarantined_records"] else "PASS",
            "check_version": check_version,
            **({"format_rules": rule_metadata} if rule_metadata is not None else {}),
            "input_completeness": "DECLARED_COMPLETE" if input_complete else "UNVERIFIED",
            "run_id": snapshot.name,
            **({"checked_at": checked_at, "fixed_manifest_path": str(fixed_manifest)}
               if dataset == "transactions" else {}),
            "input_files": sources,
            **({"kafka_observations": {name: kafka_observations(rows)
                                       for name, rows in loaded.items()}}
               if dataset == "transactions" else {}),
            "input_counts": {name: len(rows) for name, rows in loaded.items()},
            "output_counts": {name: len(rows) for name, rows in result.items()},
            "outputs": paths,
            "manifest_path": str(base / "current.json"),
        }
        if dataset == "transactions":
            # 고정 실행 기록을 먼저 완성해야 최신 참조를 바꿀 수 있다.
            fixed_manifest.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                                 indent=2), encoding="utf-8")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=base,
                                         prefix=".current-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, indent=2)
        # 후속 처리는 runs/를 전부 합치지 않고 이 파일이 가리키는 결과 묶음만 읽는다.
        os.replace(temporary, base / "current.json")
    except Exception:
        # 이번 실행의 고정된 파일만 제거한다. 이전 실행 결과는 건드리지 않는다.
        for name in result:
            (snapshot / f"{name}.jsonl").unlink(missing_ok=True)
        fixed_manifest.unlink(missing_ok=True)
        snapshot.rmdir()
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest


def decode_record(line: str, source: str, number: int) -> dict:
    """원문을 오류 결과에 복사하지 않고 파일·줄 위치만 보존한다."""
    error = None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        raw, error = {}, "PARSE_ERROR"
    if not isinstance(raw, dict):
        raw, error = {}, "TYPE_MISMATCH"
    return {**raw, "_input_source": {"file": source, "line": number}, "_input_error": error}


def collect_latest(rows: list[dict], name: str, key_field: str, normalize,
                   version_field: str, check_version: str) -> tuple[list[dict], list[dict], dict]:
    """키의 오류·동시각 충돌을 전부 확인한 뒤 최신 상태를 선택한다."""
    groups, normalized, errors = defaultdict(list), {}, {}

    def key_of(raw):
        value = raw.get(key_field)
        return value if isinstance(value, str) and value.strip() else None

    def reject(index, field, code, reason):
        source = rows[index]["_input_source"]
        errors.setdefault(index, {
            "source_dataset": name, "source_row_number": index + 1,
            "record_key": key_of(rows[index]), "field": field, "error_code": code,
            "reason": reason, "category": ("CONFLICT" if code == "CONTENT_CONFLICT"
                       else "DEPENDENCY_BLOCKED" if code == "DEPENDENCY_BLOCKED" else "INVALID"),
            "check_version": check_version, "source_file": source["file"], "source_line": source["line"],
        })

    for index, raw in enumerate(rows):
        key = key_of(raw)
        if key is not None:
            groups[key].append(index)
        if raw.get("_input_error"):
            reject(index, "record", raw["_input_error"], "업무 행 JSON 객체를 읽을 수 없습니다")
            continue
        try:
            normalized[index] = normalize(raw)
        except (RowError, FormatError) as exc:
            reject(index, exc.field, exc.code, str(exc))
            if isinstance(exc, FormatError):
                errors[index]["rule_id"] = exc.rule_id
        else:
            if key is None:
                reject(index, key_field, "MISSING_FIELD", "고유 식별 키가 없습니다")

    selected, duplicate_count, accepted_count = [], 0, 0
    for key, indices in groups.items():
        versions = defaultdict(list)
        for index in indices:
            if index in normalized:
                versions[normalized[index][version_field]].append(index)
        for same_time in versions.values():
            if any(normalized[index] != normalized[same_time[0]] for index in same_time[1:]):
                for index in same_time:
                    reject(index, version_field, "CONTENT_CONFLICT", "동일 키·원천 시각에 서로 다른 내용이 있습니다")
        if any(index in errors for index in indices):
            for index in indices:
                reject(index, key_field, "DEPENDENCY_BLOCKED", "같은 키의 오류 또는 충돌로 현재 결과를 보류합니다")
            continue
        duplicate_count += sum(len(same_time) - 1 for same_time in versions.values())
        accepted_count += len(versions)
        selected.append(normalized[versions[max(versions)][0]])
    selected.sort(key=lambda row: row[key_field])
    issues = [errors[index] for index in sorted(errors)]
    summary = {
        "source_dataset": name, "check_name": "record_processing", "check_version": check_version,
        "status": "INCOMPLETE" if issues else "PASS", "input_count": len(rows),
        "accepted_count": accepted_count, "duplicate_count": duplicate_count,
        "quarantined_count": len(issues), "output_count": len(selected),
        "superseded_count": accepted_count - len(selected),
        "conflict_count": sum(issue["category"] == "CONFLICT" for issue in issues),
        "pending_count": 0,
        "affected_record_keys": sorted({issue["record_key"] for issue in issues if issue["record_key"] is not None}),
        "unknown_key_error_count": sum(issue["record_key"] is None for issue in issues),
        "source_row_numbers": [issue["source_row_number"] for issue in issues],
    }
    return selected, issues, summary


def publish_bundle(base: str, payloads: dict[str, list[dict]], metadata: dict, write_text) -> dict:
    """실행별 파일을 모두 쓴 후 범위별 current.json 한 개로 공개한다.

    로컬은 원자 교체, S3는 단일 객체 PUT을 사용한다. 이전 실행을 삭제하지 않으며
    동시 실행 잠금은 제공하지 않는다. 소비자는 manifest만 따라 읽어야 한다.
    """
    from uuid import uuid4

    base = base.rstrip("/\\")
    run_id = "run-" + uuid4().hex
    snapshot = base + "/runs/" + run_id
    paths = {name: snapshot + "/" + name for name in payloads}
    if not base.startswith("s3://"):
        # Windows MAX_PATH보다 긴 실행/날짜 경로도 저장·후속 읽기가 가능하도록 한다.
        paths = {name: str(Path(path).resolve()) for name, path in paths.items()}
        if os.name == "nt":
            paths = {name: ("\\\\?\\" + path if not path.startswith("\\\\?\\") and len(path) >= 240 else path)
                     for name, path in paths.items()}
    manifest = {**metadata, "run_id": run_id, "outputs": paths,
                "output_counts": {name: len(rows) for name, rows in payloads.items()},
                "manifest_path": base + "/current.json"}
    # manifest가 실패해도 미공개 실행은 소비하지 않는다. 이전 current는 그대로 남는다.
    for name, rows in payloads.items():
        write_text(paths[name], "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))
    write_text(manifest["manifest_path"], json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return manifest
