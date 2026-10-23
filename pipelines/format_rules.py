"""공통 YAML의 source_rules를 검사한다. 소비 경로의 정제/집계에는 의존하지 않는다.

validate()는 첫 오류 하나를 내고(Silver), errors()는 한 행의 오류를 전부 돌려준다(Gold B). 두 함수의 첫 오류는 같다.
"""
from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import yaml

from pipelines.timestamps import parse_iso_datetime

DEFAULT_RULES = Path(__file__).resolve().parents[1] / "docs/contracts/format_rules.yaml"


class RuleConfigError(ValueError):
    """규칙 파일 오류는 행 격리가 아니라 실행 실패다."""


class FormatError(ValueError):
    def __init__(self, field: str, code: str, rule_id: str):
        super().__init__("공통 형식 규칙 위반: " + rule_id)
        self.field, self.code, self.rule_id = field, code, rule_id


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise RuleConfigError("YAML 키가 문자열이 아니거나 중복됩니다")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _object(value, allowed, required):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise RuleConfigError("지원하지 않는 키 또는 누락된 규칙 항목이 있습니다")


def _aware_time(value):
    parsed = parse_iso_datetime(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("시간대 없음")
    return parsed


def _literal(spec, value):
    """조건의 값도 필드 타입과 허용값에 맞아야 오타로 검사가 생략되지 않는다."""
    if value is None:
        if spec["nullable"]:
            return
        raise RuleConfigError("조건 값에 NULL을 사용할 수 없습니다")
    if type(value) is not {"integer": int, "boolean": bool}.get(spec["type"], str):
        raise RuleConfigError("조건 값의 타입이 잘못되었습니다")
    if isinstance(value, str) and not value.strip():
        raise RuleConfigError("조건 값이 비어 있습니다")
    if "enum" in spec and value not in spec["enum"]:
        raise RuleConfigError("조건 값이 필드 허용 목록에 없습니다")
    try:
        if spec["type"] == "uuid":
            UUID(value)
        elif spec["type"] == "timestamp":
            _aware_time(value)
    except ValueError as exc:
        raise RuleConfigError("조건 값의 UUID 또는 시각 형식 오류") from exc


class FormatRules:
    def __init__(self, path: str | Path = DEFAULT_RULES, consumer: str = "silver"):
        self.path = Path(path).resolve()
        # 파일/의존성 오류도 여기서 실행 실패로 전달한다. 잘못된 YAML로 조용히 통과하지 않는다.
        body = self.path.read_bytes()
        try:
            document = yaml.load(body.decode("utf-8-sig"), Loader=_UniqueLoader)
        except (yaml.YAMLError, UnicodeError) as exc:
            raise RuleConfigError("YAML 문법 또는 인코딩 오류") from exc
        _object(document, {"version", "status", "runtime_connected", "input_stage", "source",
                           "source_rules_status", "source_rules", "proposed_changes"},
                {"version", "runtime_connected", "input_stage", "source_rules_status", "source_rules"})
        if not isinstance(document["version"], str) or not document["version"].strip():
            raise RuleConfigError("규칙 버전이 없습니다")
        connections = document["runtime_connected"]
        if not isinstance(connections, dict) or any(type(value) is not bool for value in connections.values()):
            raise RuleConfigError("소비 경로별 연결 상태가 필요합니다")
        if connections.get(consumer) is not True or document["source_rules_status"] != "decided":
            raise RuleConfigError("이 소비 경로에서 적용 승인되지 않은 규칙입니다")
        if document["input_stage"] != "normalized_business_row":
            raise RuleConfigError("지원하지 않는 입력 단계")
        self.version, self.digest = document["version"], sha256(body).hexdigest()
        self.consumer, self.datasets = consumer, document["source_rules"]
        if not isinstance(self.datasets, dict) or not self.datasets:
            raise RuleConfigError("source_rules가 없습니다")
        ids = set()
        for name, definition in self.datasets.items():
            if not isinstance(name, str) or not name:
                raise RuleConfigError("데이터셋 이름 오류")
            _object(definition, {"fields", "checks", "forbidden_fields", "source"}, {"fields", "checks"})
            fields, checks = definition["fields"], definition["checks"]
            if not isinstance(fields, dict) or not fields or not isinstance(checks, list):
                raise RuleConfigError("fields/checks 구조 오류")
            if "source" in definition:   # 데이터셋의 원천. 없으면 맨 위 source를 따른다
                _object(definition["source"], {"path", "revision"}, {"path"})
                if any(not isinstance(value, str) or not value.strip() for value in definition["source"].values()):
                    raise RuleConfigError("데이터셋 원천(source) 정의 오류")
            forbidden = definition.get("forbidden_fields", [])
            if (not isinstance(forbidden, list) or not all(isinstance(name, str) and name for name in forbidden)
                    or len(set(forbidden)) != len(forbidden) or set(forbidden) & set(fields)):
                raise RuleConfigError("금지 필드(forbidden_fields) 정의 오류")
            for field, spec in fields.items():
                if not isinstance(field, str) or not field:
                    raise RuleConfigError("필드 이름 오류")
                _object(spec, {"type", "required", "nullable", "enum", "minimum", "pattern"},
                        {"type", "required", "nullable"})
                if (not isinstance(spec["type"], str)
                        or spec["type"] not in {"uuid", "string", "integer", "timestamp", "boolean"}):
                    raise RuleConfigError("지원하지 않는 필드 타입")
                if type(spec["required"]) is not bool or type(spec["nullable"]) is not bool:
                    raise RuleConfigError("required/nullable은 bool이어야 합니다")
                if "minimum" in spec and (spec["type"] != "integer" or type(spec["minimum"]) is not int):
                    raise RuleConfigError("minimum은 정수 필드의 정수여야 합니다")
                if "pattern" in spec:   # 문자열 전체가 맞아야 하는 정규식
                    if spec["type"] != "string" or not isinstance(spec["pattern"], str) or not spec["pattern"]:
                        raise RuleConfigError("pattern은 문자열 필드의 정규식이어야 합니다")
                    try:
                        re.compile(spec["pattern"])
                    except re.error as exc:
                        raise RuleConfigError("pattern 정규식 오류") from exc
                if "enum" in spec:
                    enum = spec["enum"]
                    if (not isinstance(enum, list) or not enum
                            or spec["type"] not in {"string", "integer"}
                            or any(type(value) is not (int if spec["type"] == "integer" else str) for value in enum)
                            or len(set(enum)) != len(enum)):
                        raise RuleConfigError("enum 정의 오류")
            for check in checks:
                _object(check, {"id", "when", "rule", "field", "other_field", "value"}, {"id", "rule", "field"})
                if not isinstance(check["id"], str) or not check["id"] or check["id"] in ids:
                    raise RuleConfigError("검사 ID 누락 또는 중복")
                ids.add(check["id"])
                if not isinstance(check["field"], str) or check["field"] not in fields:
                    raise RuleConfigError("검사 대상 필드가 없습니다")
                operator = check["rule"]
                if not isinstance(operator, str) or operator not in {"greater_than_or_equal_field", "equals_value", "is_null", "required_non_null"}:
                    raise RuleConfigError("지원하지 않는 검사 연산자")
                if operator == "greater_than_or_equal_field":
                    other = check.get("other_field")
                    if (not isinstance(other, str) or other not in fields
                            or fields[other]["type"] != fields[check["field"]]["type"]
                            or fields[other]["type"] not in {"timestamp", "integer"}):
                        raise RuleConfigError("비교할 필드 또는 타입이 잘못되었습니다")
                elif "other_field" in check:
                    raise RuleConfigError("이 연산자는 other_field를 사용하지 않습니다")
                if (operator == "equals_value") != ("value" in check):
                    raise RuleConfigError("equals_value의 value 정의 오류")
                if operator == "equals_value":
                    _literal(fields[check["field"]], check["value"])
                if "when" in check:
                    condition = check["when"]
                    _object(condition, {"field", "equals", "not_in"}, {"field"})
                    if (not isinstance(condition["field"], str) or condition["field"] not in fields
                            or ("equals" in condition) == ("not_in" in condition)
                            or ("not_in" in condition and not isinstance(condition["not_in"], list))):
                        raise RuleConfigError("when 조건 오류")
                    for value in ([condition["equals"]] if "equals" in condition else condition["not_in"]):
                        _literal(fields[condition["field"]], value)
        # proposed_changes는 제안 문서다. 검사를 생성하거나 원천 규칙에 합치지 않는다.

    def reference(self) -> dict:
        return {"version": self.version, "sha256": self.digest, "path": str(self.path),
                "scope": "source_rules", "consumer": self.consumer}

    def _definition(self, dataset: str) -> dict:
        if dataset not in self.datasets:
            raise RuleConfigError("해당 데이터셋의 규칙이 없습니다")
        return self.datasets[dataset]

    def errors(self, dataset: str, row: dict) -> list[FormatError]:
        """한 행의 오류를 전부 돌려준다 (Gold B가 오류마다 한 줄씩 남길 때 쓴다).

        순서는 필드마다 첫 오류 하나(필드 정의 순서), 들어오면 안 되는 필드(forbidden_fields), 조건 검사(정의 순서)다.
        오류가 난 필드를 쓰는 조건 검사는 건너뛰어서 한 필드에 오류는 하나다. 같은 원인의 오류가 겹치거나
        읽을 수 없는 값을 비교하지 않게 한다. 금지 필드는 값을 남기지 않고 필드 이름으로만 알린다.
        """
        definition = self._definition(dataset)
        fields = definition["fields"]
        found = [error for field, spec in fields.items()
                 if (error := _field_error(dataset, field, spec, row)) is not None]
        found += [FormatError(name, "INVALID_VALUE", dataset + ".forbidden_fields." + name)
                  for name in definition.get("forbidden_fields", ()) if name in row]
        broken = {error.field for error in found}
        for check in definition["checks"]:
            used = {check["field"], check.get("other_field"), (check.get("when") or {}).get("field")}
            if broken & used:
                continue
            error = _check_error(check, fields, row)
            if error is not None:
                found.append(error)
                broken.add(error.field)
        return found

    def validate(self, dataset: str, row: dict) -> None:
        """첫 오류 하나만 낸다 (Silver가 쓰는 동작). errors()의 첫 오류와 같다."""
        found = self.errors(dataset, row)
        if found:
            raise found[0]


def _field_error(dataset: str, field: str, spec: dict, row: dict) -> FormatError | None:
    """필드 하나의 첫 오류. 통과하면 None."""
    prefix = dataset + ".fields." + field
    if field not in row:
        return FormatError(field, "MISSING_FIELD", prefix + ".required") if spec["required"] else None
    value = row[field]
    if value is None:
        return None if spec["nullable"] else FormatError(field, "MISSING_FIELD", prefix + ".nullable")
    kind = spec["type"]
    if kind == "integer":
        if type(value) is not int:
            return FormatError(field, "TYPE_MISMATCH", prefix + ".type")
    elif kind == "boolean":
        if type(value) is not bool:
            return FormatError(field, "TYPE_MISMATCH", prefix + ".type")
    else:
        if not isinstance(value, str):
            return FormatError(field, "TYPE_MISMATCH", prefix + ".type")
        if not value.strip():
            return FormatError(field, "MISSING_FIELD", prefix + ".non_blank")
        try:
            if kind == "uuid":
                UUID(value)
            elif kind == "timestamp":
                _aware_time(value)
        except ValueError:
            return FormatError(field, "INVALID_VALUE", prefix + ".type")
        if "pattern" in spec and re.fullmatch(spec["pattern"], value) is None:
            return FormatError(field, "INVALID_VALUE", prefix + ".pattern")
    if "enum" in spec and value not in spec["enum"]:
        return FormatError(field, "INVALID_VALUE", prefix + ".enum")
    if "minimum" in spec and value < spec["minimum"]:
        return FormatError(field, "INVALID_VALUE", prefix + ".minimum")
    return None


def _check_error(check: dict, fields: dict, row: dict) -> FormatError | None:
    """조건 검사 하나의 오류. 조건(when)에 해당하지 않거나 통과하면 None."""
    condition = check.get("when")
    if condition:
        actual = row.get(condition["field"])
        if "equals" in condition and actual != condition["equals"]:
            return None
        if "not_in" in condition and actual in condition["not_in"]:
            return None
    field, value, operator = check["field"], row.get(check["field"]), check["rule"]
    if operator == "required_non_null":
        return FormatError(field, "MISSING_FIELD", check["id"]) if value is None else None
    valid = value is None if operator == "is_null" else value == check.get("value")
    if operator == "greater_than_or_equal_field":
        other = row.get(check["other_field"])
        if value is None or other is None:
            return FormatError(field, "MISSING_FIELD", check["id"])
        if fields[field]["type"] == "timestamp":
            value, other = _aware_time(value), _aware_time(other)
        valid = value >= other
    return None if valid else FormatError(field, "INVALID_VALUE", check["id"])
