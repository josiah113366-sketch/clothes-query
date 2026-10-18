"""Silver 로컬 입력·단일 행 검사·완료된 결과 묶음 저장을 공유한다."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile


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
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RowError(field, "TYPE_MISMATCH", "ISO 시각이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RowError(field, "INVALID_VALUE", "시간대가 없습니다")
    return parsed.astimezone(UTC)


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
        except RowError as exc:
            reject(index, exc.field, exc.code, str(exc))

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


def load_jsonl(location: str) -> tuple[list[dict], list[str]]:
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
                if any(field in raw for field in ("after", "before", "payload", "__op", "op")):
                    raise ValueError("CDC 입력은 업무 행으로 변환한 뒤 전달해야 합니다")
                rows.append({**raw, "_input_source": {"file": str(path), "line": number},
                             "_input_error": error})
    return rows, [str(path) for path in files]


def run_local(locations: dict[str, str], output_root: str, dataset: str,
              check_version: str, build) -> dict:
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
        loaded[name], sources[name] = load_jsonl(location)
    result = build(loaded)

    base = root / "silver" / dataset
    runs = base / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="run-", dir=runs))
    temporary = None
    try:
        paths = {}
        for name, rows in result.items():
            path = snapshot / f"{name}.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                    for row in rows), encoding="utf-8")
            paths[name] = str(path)
        manifest = {
            "status": "INCOMPLETE" if result["quarantined_records"] else "PASS",
            "check_version": check_version,
            "input_files": sources,
            "input_counts": {name: len(rows) for name, rows in loaded.items()},
            "output_counts": {name: len(rows) for name, rows in result.items()},
            "outputs": paths,
            "manifest_path": str(base / "current.json"),
        }
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
        snapshot.rmdir()
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest


