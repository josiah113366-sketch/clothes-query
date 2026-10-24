"""Bronze v2 결제의 최신 상태를 Kafka 위치로 선택한다. 업무 값을 고치지 않는다."""
from collections import defaultdict

from pipelines.silver.common import kafka_reference


def payment_decisions(rows, invalid=()):
    """입력 순서별 CURRENT/HISTORY/HOLD와 보류 사유. legacy 키는 반환하지 않는다."""
    invalid = set(invalid)
    groups = defaultdict(list)
    result = {}
    for index, row in enumerate(rows):
        if isinstance(row, dict) and isinstance(row.get("payment_id"), str):
            groups[row["payment_id"]].append(index)
    for indices in groups.values():
        refs = {i: kafka_reference(rows[i]) for i in indices}
        if all(ref["status"] == "MISSING" for ref in refs.values()):
            continue
        reason = None
        if any(ref["status"] != "VALID" or ref.get("topic") != "payments" for ref in refs.values()):
            reason = "INVALID_KAFKA_POSITION"
        elif len({ref["partition"] for ref in refs.values()}) > 1:
            reason = "MULTI_PARTITION"
        if reason:
            result.update({i: ("HOLD", reason) for i in indices})
            continue
        latest_offset = max(ref["offset"] for ref in refs.values())
        latest = [i for i in indices if refs[i]["offset"] == latest_offset]
        # 같은 위치의 중복 전달은 허용하되, 내용이 다른 두 원문 중 하나를 고르지 않는다.
        business = [{k: v for k, v in rows[i].items()
                     if not k.startswith("_") and not k.startswith("kafka_")} for i in latest]
        for item, index in zip(business, latest):
            item.update(__op=rows[index].get("__op"), __source_ts_ms=rows[index].get("__source_ts_ms"))
        if any(i in invalid for i in latest):
            reason = "INVALID_LATEST"
        elif any(row != business[0] for row in business[1:]):
            reason = "CONTENT_CONFLICT"
        else:
            at = rows[latest[0]].get("__source_ts_ms")
            previous = [rows[i]["__source_ts_ms"] for i in indices if i not in latest
                        and type(rows[i].get("__source_ts_ms")) is int]
            if type(at) is not int:
                reason = "INVALID_LATEST"
            elif previous and at < max(previous):
                reason = "ORDER_ANOMALY"
        for i in indices:
            result[i] = (("HOLD", reason) if reason else
                         ("CURRENT", None) if i in latest else ("HISTORY", None))
    return result
