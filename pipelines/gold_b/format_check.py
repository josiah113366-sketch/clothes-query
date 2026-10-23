"""Gold B 형식 검사: Kafka 메시지 하나를 공통 형식 규칙으로 검사해 원장 줄의 재료(ledger.Judgement)를 돌려준다.

규칙표는 docs/contracts/format_rules.yaml이고 Silver와 같은 검사기(pipelines/format_rules.py)를 소비 경로 gold_b로 쓴다.
적재 잡과 재처리 잡이 같은 검사기를 쓴다 (ledger.Checker). Kafka 위치·loaded_at·rule_version은 ledger.message_rows가 붙인다.
설계는 docs/design/gold-b/README.md 「처리 규칙」, 「④ malformed_events」, 2단계.

메시지 하나에 하는 일
  1. 토픽으로 규칙 이름을 정한다. 규칙을 쓰지 않는 토픽(reviews.raw 등)은 검사하지 않는다 (② topic_messages에만 남음).
  2. 값을 JSON 객체로 읽는다. 못 읽으면 PARSE_ERROR 한 줄 (field "__message__").
  3. 공통 검사기 errors()로 오류를 전부 찾는다 (필드마다 하나). __op가 c·r·u인 결제는 __source_ts_ms도 검사한다.
     오류마다 ④ 한 줄이고 raw_sample은 첫 줄에만 넣는다. 오류 줄마다 메시지의 키(record_key)와 변경 시각(source_ts_ms)을 남긴다.
  4. 결제이고 오류가 없고 __op가 c·r·u면 지문을 붙여 ① 결제 줄을 만든다. 지문을 만들 수 없으면 그 필드의 INVALID_VALUE.
     같은 결제의 최신 상태와 보류는 원장이 아니라 정리 뷰(payment_states)가 정한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from pipelines.format_rules import DEFAULT_RULES, FormatRules, RuleConfigError
from pipelines.gold_b.ledger import Judgement, KafkaMessage
from pipelines.payment_fingerprint import FingerprintError, payment_fingerprint
from pipelines.timestamps import parse_iso_datetime

# Kafka 토픽 → 공통 규칙의 데이터셋 이름. 여기 없는 토픽은 형식 검사를 하지 않는다 (reviews.raw: 2026-10-23 결정)
DATASETS = {"payments": "payments", "orders": "orders", "order-items": "order_items",
            "members-events": "members", "clickstream": "clickstream"}
# 결제 원장에 넣는 CDC 변경 종류: 새 결제, Debezium 시작 전부터 있던 결제, 결제 수정 (u는 2026-10-23 추가)
PAYMENT_OPS = ("c", "r", "u")
PARSE_FIELD = "__message__"   # 메시지 전체를 읽지 못했을 때의 field
SOURCE_TS = "__source_ts_ms"  # 원본 DB에서 바뀐 시각 (Debezium, 밀리초)
# 오류 줄의 record_key: 메시지의 키 (Silver 키와 같음). 회원은 남기지 않는다 (회원 정보를 원장에 두지 않음)
RECORD_KEYS = {"payments": "payment_id", "orders": "order_id", "order_items": "order_item_id",
               "clickstream": "event_id"}
# 오류 줄에 변경 시각을 남기는 데이터셋 (회원 제외. 결제는 잘못된 최신 이벤트의 순서 이상을 볼 때 쓴다)
SOURCE_TS_DATASETS = frozenset({"payments", "orders", "order_items"})

# raw_sample에 값을 그대로 두는 필드: 개인정보가 아닌 업무 값, 결제·주문 ID, 시각 (2026-10-23 결정).
# 회원 ID·세션 ID·회원 토픽의 값·상품 번호·클릭 event_id는 MASK로 가린다
KEEP_VALUES: dict[str, frozenset[str]] = {
    "payments": frozenset({"payment_id", "order_id", "method", "pg", "status", "failure_code", "attempt_no",
                           "amount", "requested_at", "completed_at", SOURCE_TS}),
    "orders": frozenset({"order_id", "status", "status_reason", "total_amount", "ordered_at", "updated_at",
                         SOURCE_TS}),
    "order_items": frozenset({"order_item_id", "order_id", "quantity", "unit_price", SOURCE_TS}),
    "clickstream": frozenset({"event_type", "event_time"}),
    "members": frozenset(),
}
CDC_KEEP = frozenset({"__op", "__source_snapshot"})
MASK = "***"
SAMPLE_LIMIT = 1000           # raw_sample 최대 길이 (원문 일부)
VALUE_LIMIT = 40              # 그대로 두는 값도 이보다 긴 문자열은 가린다


def mask_sample(dataset: str, row: Mapping[str, object]) -> str:
    """필드 이름은 다 남기고, 정해 둔 업무 값만 그대로 둔 JSON 문자열. null은 그대로 둔다 (값이 없다는 것만 보임)."""
    keep = KEEP_VALUES.get(dataset, frozenset()) | CDC_KEEP
    masked = {str(key): (_shown(value) if key in keep else (None if value is None else MASK))
              for key, value in row.items()}
    text = json.dumps(masked, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= SAMPLE_LIMIT else text[:SAMPLE_LIMIT - 1] + "…"


def _shown(value: object) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else MASK   # NaN·무한대는 JSON이 아님
    if isinstance(value, str) and len(value) <= VALUE_LIMIT:
        return value
    return MASK


def _parse(value: bytes | str | None) -> dict | None:
    """메시지 값을 JSON 객체로 읽는다. 못 읽으면 None."""
    if value is None:
        return None
    try:
        text = value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else value
        row = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        return None
    return row if isinstance(row, dict) else None


def _source_ts_ms(row: Mapping[str, object]) -> int | None:
    """__source_ts_ms가 0 이상의 정수면 그 값, 아니면 None."""
    value = row.get(SOURCE_TS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _source_ts_error(row: Mapping[str, object]) -> tuple[str, str] | None:
    """결제 CDC 줄의 변경 시각 검사. Silver 거래 검사(common.integer(…, 0))와 같은 오류 코드."""
    value = row.get(SOURCE_TS)
    if value is None:
        return SOURCE_TS, "MISSING_FIELD"
    if isinstance(value, bool) or not isinstance(value, int):
        return SOURCE_TS, "TYPE_MISMATCH"
    return (SOURCE_TS, "INVALID_VALUE") if value < 0 else None


def _record_key(dataset: str, row: Mapping[str, object]) -> str | None:
    field = RECORD_KEYS.get(dataset)
    value = row.get(field) if field else None
    return value if isinstance(value, str) and value.strip() else None


def _payment_row(row: Mapping[str, object]) -> dict:
    """결제 원장 ①의 업무 칼럼 (ledger.PAYMENT_FIELDS). 지문은 시각을 바꾸기 전의 원문으로 만든다."""
    fingerprint = payment_fingerprint(row)    # 시각 형식도 여기서 확인한다 (소수초 6자리까지, 시간대 필수)
    # 공통 시각 파서: 팀 Spark 이미지의 Python 3.10에서도 Z와 1~6자리 소수초를 읽는다 (지문·형식 규칙과 같은 함수)
    return {"payment_id": row["payment_id"], "order_id": row["order_id"], "attempt_no": row["attempt_no"],
            "pg": row["pg"], "status": row["status"], "failure_code": row.get("failure_code"),
            "completed_at": parse_iso_datetime(str(row["completed_at"])), **fingerprint,
            "cdc_op": row["__op"], "source_ts_ms": row[SOURCE_TS]}


class FormatChecker:
    """ledger.Checker: Kafka 메시지 하나 → Judgement. rule_version은 규칙표의 version이다."""

    def __init__(self, rules: FormatRules | None = None, *, rules_path: str | Path | None = None):
        if rules is None:
            rules = FormatRules(DEFAULT_RULES if rules_path is None else rules_path, consumer="gold_b")
        missing = sorted(set(DATASETS.values()) - set(rules.datasets))
        if missing:
            raise RuleConfigError(f"Gold B가 쓰는 규칙이 규칙표에 없습니다: {', '.join(missing)}")
        self._rules = rules
        self.rule_version = rules.version

    def __call__(self, message: KafkaMessage) -> Judgement:
        dataset = DATASETS.get(message.topic)
        if dataset is None:
            return Judgement()
        row = _parse(message.value)
        if row is None:
            return Judgement(errors=[{"field": PARSE_FIELD, "reason": "PARSE_ERROR", "raw_sample": None,
                                      "record_key": None, "source_ts_ms": None}])
        found = [(error.field, error.code) for error in self._rules.errors(dataset, row)]
        payment_event = dataset == "payments" and row.get("__op") in PAYMENT_OPS
        if payment_event and (source_ts_error := _source_ts_error(row)):
            found.append(source_ts_error)   # 변경 시각이 있어야 순서 이상을 볼 수 있다
        payment = None
        if not found and payment_event:
            try:
                payment = _payment_row(row)
            except FingerprintError as exc:
                found = [(exc.field, "INVALID_VALUE")]
        if found:
            sample = mask_sample(dataset, row)
            key = _record_key(dataset, row)
            source_ts = _source_ts_ms(row) if dataset in SOURCE_TS_DATASETS else None
            return Judgement(errors=[{"field": field, "reason": reason, "raw_sample": sample if i == 0 else None,
                                      "record_key": key, "source_ts_ms": source_ts}
                                     for i, (field, reason) in enumerate(found)])
        return Judgement(payment=payment)
