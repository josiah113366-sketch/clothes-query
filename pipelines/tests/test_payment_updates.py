"""Gold B #95와 합의한 최신 결제·과거 오류·legacy 경계를 검증한다."""
from pipelines.silver.tests.test_transactions import order, payment
from pipelines.silver.transactions import build_silver


def event(offset, **changes):
    return payment(kafka_topic="payments", kafka_partition=0, kafka_offset=offset,
                   kafka_timestamp="2026-10-21T00:00:00.000Z", kafka_timestamp_type="CreateTime",
                   __op="u", __source_ts_ms=1000 + offset, **changes)


def process(rows):
    return build_silver([order()], [], rows)


def test_latest_update_replaces_content_and_preserves_original_fingerprint():
    result = process([event(2, pg="PG_B"), event(1)])
    assert len(result["payment_attempts"]) == 1
    assert result["payment_attempts"][0]["pg"] == "PG_B"
    assert not result["quarantined_records"]
    assert result["dq_results"][2]["superseded_count"] == 1


def test_historical_invalid_does_not_hold_corrected_latest():
    result = process([event(1, amount="bad"), event(2)])
    assert len(result["payment_attempts"]) == 1
    assert result["quarantined_records"][0]["active"] is False
    assert result["dq_results"][2]["status"] == "PASS"
    assert result["dq_results"][2]["historical_error_count"] == 1
    missing_source = {**event(1), "__source_ts_ms": None}
    assert len(process([missing_source, event(2)])["payment_attempts"]) == 1


def test_invalid_latest_and_multiple_partitions_hold_all():
    for latest in (event(2, amount="bad"), {**event(2), "kafka_partition": 1}):
        result = process([event(1), latest])
        assert not result["payment_attempts"]
        assert any(row["active"] for row in result["quarantined_records"])


def test_source_time_regression_and_same_time():
    assert not process([event(1), {**event(2), "__source_ts_ms": 999}])["payment_attempts"]
    assert process([event(1), {**event(2), "__source_ts_ms": 1001}])["payment_attempts"]


def test_legacy_update_and_mixed_positions_do_not_silently_fall_back():
    assert not process([payment(__op="u", __source_ts_ms=2)])["payment_attempts"]
    assert not process([payment(), event(2)])["payment_attempts"]
    assert not process([{**event(2), "kafka_offset": True}])["payment_attempts"]


def test_same_position_conflict_and_duplicate():
    assert not process([event(2), event(2, pg="PG_B")])["payment_attempts"]
    assert len(process([event(2), event(2)])["payment_attempts"]) == 1
