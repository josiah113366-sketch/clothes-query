"""합의된 Gold A 시나리오를 전체 실행·부분 교체 결과로 확인한다."""
import json
from datetime import date
from pathlib import Path

import pytest

from pipelines.gold_a import connect_reviews, read_rows, replacement
from pipelines.gold_a.funnels import build_funnels
from pipelines.gold_a.funnels import run as gold_funnels
from pipelines.gold_a.reviews import (
    aggregate_aspects,
    load_analysis,
    run_aggregate,
    run_aspects,
)
from pipelines.gold_a.transactions import run as gold_transactions
from pipelines.silver.clicks import run as silver_clicks
from pipelines.silver.products import run as silver_products
from pipelines.silver.reviews import run as silver_reviews
from pipelines.silver.transactions import run as silver_transactions

START, END = date(2026, 10, 18), date(2026, 10, 19)


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def pointer(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_outputs(manifest):
    return {name: read_rows(path) for name, path in manifest["outputs"].items()}


def make_example(root):
    source, silver, gold = root / "input", root / "silver", root / "gold"
    design = {"product_code": 100, "product_type_no": 1, "garment_group_no": 1, "index_group_no": 1,
              "design_price": 10000, "product_type_name": "top", "product_group_name": "clothes",
              "garment_group_name": "top", "index_group_name": "test"}
    variants = [{"article_id": article, "product_code": 100, "colour_group_code": 1,
                 "graphical_appearance_no": 1, "price": price, "prod_name": "test product",
                 "colour_group_name": "black", "graphical_appearance_name": "solid"}
                for article, price in (("0001", 10000), ("0002", 5000))]
    write(source / "designs.jsonl", [design])
    write(source / "variants.jsonl", variants)
    silver_products(str(source / "designs.jsonl"), str(source / "variants.jsonl"), str(silver))
    orders, items, payments = [], [], []
    specifications = [("O1", "S1", "0001", 2, 10000, "2026-10-18T23:50:00+09:00", "2026-10-19T00:10:00+09:00", "SUCCESS"),
                      ("O2", "S3", "0001", 1, 10000, "2026-10-18T11:00:00+09:00", "2026-10-18T11:01:00+09:00", "SUCCESS"),
                      ("O3", "S4", "0002", 1, 5000, "2026-10-18T12:00:00+09:00", "2026-10-18T12:01:00+09:00", "FAILED")]
    for order_id, session, article, quantity, price, ordered, completed, status in specifications:
        orders.append({"order_id": order_id, "member_id": "M-DEMO", "session_id": session,
                       "status": "PAID" if status == "SUCCESS" else "PAYMENT_FAILED", "status_reason": None,
                       "total_amount": quantity * price, "ordered_at": ordered, "updated_at": completed})
        items.append({"order_item_id": "I" + order_id, "order_id": order_id, "article_id": article,
                      "quantity": quantity, "unit_price": price})
        payments.append({"payment_id": "P" + order_id, "order_id": order_id, "attempt_no": 1,
                         "method": "CARD", "pg": "PG_A", "amount": quantity * price, "status": status,
                         "failure_code": None if status == "SUCCESS" else "PG_TIMEOUT",
                         "requested_at": ordered, "completed_at": completed})
    for name, rows in (("orders", orders), ("items", items), ("payments", payments)):
        write(source / (name + ".jsonl"), rows)
    silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"), str(source / "payments.jsonl"), str(silver))
    clicks = []
    for session, article, kind, at in (("S1", "0001", "view", "2026-10-18T10:00:00+09:00"),
                                     ("S1", "0001", "view", "2026-10-18T10:01:00+09:00"),
                                     ("S1", "0001", "cart_add", "2026-10-18T10:02:00+09:00"),
                                     ("S2", "0001", "view", "2026-10-18T10:00:00+09:00"),
                                     ("S3", "0001", "view", "2026-10-18T10:30:00+09:00"),
                                     ("S4", "0002", "view", "2026-10-18T11:00:00+09:00"),
                                     ("S4", "0002", "cart_add", "2026-10-18T11:02:00+09:00")):
        clicks.append({"event_id": "E" + str(len(clicks)), "event_type": kind, "member_id": "M-DEMO",
                       "article_id": article, "session_id": session, "event_time": at})
    write(source / "clicks.jsonl", clicks)
    silver_clicks(str(source / "clicks.jsonl"), str(silver))
    reviews = []
    for review_id, product, rating, created in (("R1", "alias-0001", 2, "2026-10-19T01:00:00Z"),
                                               ("R2", "alias-0001", 5, "2026-10-19T02:00:00Z"),
                                               ("R3", "0002", 4, "2026-10-18T01:00:00Z"),
                                               ("R4", "0002", 1, "2026-10-19T03:00:00Z")):
        reviews.append({"schema_version": "review.v2", "event_type": "review_created", "review_id": review_id,
                        "event_id": "E" + review_id, "product_id": product, "rating": rating,
                        "created_at": created, "emitted_at": "2026-10-19T04:00:00Z", "text": "synthetic test review"})
    write_reviews(source, reviews)
    silver_reviews(str(source), str(silver), START, END)
    mapping = source / "mapping.jsonl"
    write(mapping, [{"product_id": "alias-0001", "article_id": "0001"}])
    analysis = [{"review_id": rid, "aspect": aspect, "score": score, "model_version": "demo.v1"}
                for rid, aspect, score in (("R1", "품질·내구성", -2), ("R1", "배송", 2),
                                               ("R2", "품질·내구성", 1), ("R3", "사이즈·핏", 2),
                                               ("R4", "품질·내구성", -1))]
    analysis.append(dict(analysis[0]))  # 동일 분석 재수신은 한 번만 집계한다.
    write(source / "analysis.jsonl", analysis)
    manifests = {"transactions": gold_transactions(str(silver), str(gold), str(silver)),
                 "funnels": gold_funnels(str(silver), str(silver), str(silver), str(gold))}
    run_aggregate(str(silver), str(gold), START, END, str(silver), str(mapping))
    manifests["reviews"] = pointer(gold / "gold_a/review_product_daily/scopes/2026-10-18_2026-10-19/current.json")
    manifests["aspects"] = run_aspects(str(silver), str(gold), START, END, str(silver),
                                     str(source / "analysis.jsonl"), "demo.v1", str(mapping))
    return {"root": root, "source": source, "silver": silver, "gold": gold, "reviews": reviews,
            "variants": variants, "analysis": analysis, "mapping": mapping, "manifests": manifests}


def write_reviews(source, rows):
    for day in (START, END):
        write(source / f"reviews/year={day:%Y}/month={day:%m}/day={day:%d}/part-00000.jsonl",
              [row for row in rows if row["created_at"][:10] == str(day)])


def prepare_scoped_trade(example, conflict=True, complete=True):
    source, silver = example["source"], example["silver"]
    payments = [json.loads(line) for line in (source / "payments.jsonl").read_text().splitlines()]
    payments = [row for row in payments if row["payment_id"] != "PO1" or row["amount"] == 20000]
    for row in payments:
        if row["order_id"] == "O3":
            row["status"], row["failure_code"] = "SUCCESS", None
    if conflict:
        original = next(row for row in payments if row["payment_id"] == "PO1")
        payments.append({**original, "amount": 99999, "completed_at": "2026-10-19T01:10:00+09:00"})
    write(source / "payments.jsonl", payments)
    silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"),
                        str(source / "payments.jsonl"), str(silver), input_complete=complete)
    silver_clicks(str(source / "clicks.jsonl"), str(silver), input_complete=complete)


def test_scoped_hold_preserves_bad_product_updates_good_and_recovers(tmp_path):
    example = make_example(tmp_path)
    prepare_scoped_trade(example)
    silver, gold = str(example["silver"]), str(example["gold"])
    manifest = gold_transactions(silver, gold, silver, scope_aware=True)
    assert manifest["status"] == "PARTIAL"
    rows = read_outputs(manifest)["product_sales_daily.jsonl"]
    assert next(row for row in rows if row["sales_date_kst"] == "2026-10-19")["item_sales_amount"] == 20000
    assert next(row for row in rows if row["article_id"] == "0002")["item_sales_amount"] == 5000
    hours = [scope["key"].get("hour_start_kst") for scope in manifest["held_scopes"]]
    assert "2026-10-19T00:00:00+09:00" in hours and "2026-10-19T01:00:00+09:00" in hours
    repeated = gold_transactions(silver, gold, silver, scope_aware=True)
    assert read_outputs(repeated) == read_outputs(manifest)
    assert [row["last_normal_result"] for row in repeated["held_scopes"]] == [
        row["last_normal_result"] for row in manifest["held_scopes"]]
    with pytest.raises(ValueError, match="scope-aware"):
        gold_transactions(silver, gold, silver)
    prepare_scoped_trade(example, conflict=False)
    recovered = gold_transactions(silver, gold, silver, scope_aware=True)
    assert recovered["status"] == "PASS" and not recovered["held_scopes"]
    assert read_outputs(recovered) == read_outputs(gold_transactions(silver, gold, silver, scope_aware=True))


def test_scoped_funnel_holds_first_view_day_and_restores_paid(tmp_path):
    example = make_example(tmp_path)
    prepare_scoped_trade(example)
    silver, gold = str(example["silver"]), str(example["gold"])
    manifest = gold_funnels(silver, silver, silver, gold, scope_aware=True)
    assert manifest["status"] == "PARTIAL"
    scopes = manifest["held_scopes"]
    assert any(scope["table"] == "funnel_daily" and scope["key"] == {
        "funnel_date_kst": "2026-10-18", "article_id": "0001"} for scope in scopes)
    daily = read_outputs(manifest)["funnel_daily.jsonl"]
    assert next(row for row in daily if row["article_id"] == "0001")["paid_sessions"] == 2
    assert next(row for row in daily if row["article_id"] == "0002")["paid_sessions"] == 1
    prepare_scoped_trade(example, conflict=False)
    recovered = gold_funnels(silver, silver, silver, gold, scope_aware=True)
    assert recovered["status"] == "PASS" and not recovered["held_scopes"]


def test_scoped_changed_order_key_also_finds_previously_published_order(tmp_path):
    example = make_example(tmp_path)
    source = example["source"]
    payments = [json.loads(line) for line in (source / "payments.jsonl").read_text().splitlines()]
    # 이번 입력에 O1 결제 후보가 없어도 이전 공개에 반영한 P/O1을 따라가야 한다.
    changed = next(row for row in payments if row["payment_id"] == "PO1")
    changed.update(order_id="O3", amount=5000, requested_at="2026-10-18T12:00:00+09:00",
                   completed_at="2026-10-18T12:01:00+09:00")
    write(source / "payments.jsonl", payments)
    silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"),
                        str(source / "payments.jsonl"), str(example["silver"]), input_complete=True)
    manifest = gold_transactions(str(example["silver"]), str(example["gold"]),
                                 str(example["silver"]), scope_aware=True)
    assert manifest["status"] == "PARTIAL"
    scopes = [row for row in manifest["held_scopes"] if row["table"] == "product_sales_daily"]
    assert any(row["key"] == {"sales_date_kst": "2026-10-19", "article_id": "0001"} for row in scopes)
    assert any(row["key"] == {"sales_date_kst": "2026-10-18", "article_id": "0002"} for row in scopes)


def test_scoped_no_baseline_is_missing_not_zero_and_requires_complete_input(tmp_path):
    example = make_example(tmp_path)
    prepare_scoped_trade(example, complete=False)
    silver = str(example["silver"])
    with pytest.raises(ValueError, match="input-complete"):
        gold_transactions(silver, str(tmp_path / "fresh-gold"), silver, scope_aware=True)
    prepare_scoped_trade(example, complete=True)
    manifest = gold_transactions(silver, str(tmp_path / "fresh-gold"), silver, scope_aware=True)
    assert manifest["status"] == "PARTIAL"
    assert not any(row["sales_date_kst"] == "2026-10-19" for row in read_outputs(manifest)["product_sales_daily.jsonl"])
    assert all(not scope["previous_result_available"] for scope in manifest["held_scopes"])


def test_scoped_unknown_error_holds_whole_bundle_and_publish_failure_keeps_pointer(tmp_path, monkeypatch):
    example = make_example(tmp_path)
    source = example["source"]
    with (source / "payments.jsonl").open("a") as handle:
        handle.write("{broken json\n")
    silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"),
                        str(source / "payments.jsonl"), str(example["silver"]), input_complete=True)
    silver, gold = str(example["silver"]), str(example["gold"])
    held = gold_transactions(silver, gold, silver, scope_aware=True)
    assert held["status"] == "PARTIAL" and all(scope["key"] == {} for scope in held["held_scopes"])
    assert read_outputs(held) == read_outputs(example["manifests"]["transactions"])
    import pipelines.gold_a as module
    original = module._write_text
    before = Path(held["manifest_path"]).read_bytes()

    def fail_pointer(uri, body):
        if uri.endswith("current.json"):
            raise OSError("simulated publish failure")
        original(uri, body)

    monkeypatch.setattr(module, "_write_text", fail_pointer)
    with pytest.raises(OSError):
        gold_transactions(silver, gold, silver, scope_aware=True)
    assert Path(held["manifest_path"]).read_bytes() == before
    assert list(Path(held["manifest_path"]).parent.glob("failed-runs/*.json"))
    lock = Path(held["manifest_path"]).parent / ".writer.lock"
    lock.write_text("another writer", encoding="utf-8")
    with pytest.raises(ValueError, match="잠금"):
        gold_transactions(silver, gold, silver, scope_aware=True)
    assert Path(held["manifest_path"]).read_bytes() == before
    lock.unlink()


def test_order_total_mismatch_blocks_trade_and_funnel_then_reprocessing_recovers(tmp_path):
    example = make_example(tmp_path)
    source, silver, gold = example["source"], str(example["silver"]), str(example["gold"])
    orders = [json.loads(line) for line in (source / "orders.jsonl").read_text().splitlines()]
    payments = [json.loads(line) for line in (source / "payments.jsonl").read_text().splitlines()]
    original = next(row for row in orders if row["order_id"] == "O1")["total_amount"]
    # 주문 총액과 성공 결제만 바꿔 상품 합계 오류를 독립적으로 검출한다.
    next(row for row in orders if row["order_id"] == "O1")["total_amount"] += 1000
    next(row for row in payments if row["order_id"] == "O1")["amount"] += 1000
    write(source / "orders.jsonl", orders)
    write(source / "payments.jsonl", payments)
    manifest = silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"),
                                   str(source / "payments.jsonl"), silver, input_complete=True)
    checks = read_rows(manifest["outputs"]["dq_results"])
    assert next(row for row in checks if row["source_dataset"] == "orders")["amount_checks"][0]["status"] == "MISMATCH"
    silver_clicks(str(source / "clicks.jsonl"), silver, input_complete=True)
    held_trade = gold_transactions(silver, gold, silver, scope_aware=True)
    held_funnel = gold_funnels(silver, silver, silver, gold, scope_aware=True)
    assert held_trade["status"] == held_funnel["status"] == "PARTIAL"
    assert all(row["key"] == {} for row in held_trade["held_scopes"])
    assert read_outputs(held_trade) == read_outputs(example["manifests"]["transactions"])
    next(row for row in orders if row["order_id"] == "O1")["total_amount"] = original
    next(row for row in payments if row["order_id"] == "O1")["amount"] = original
    write(source / "orders.jsonl", orders)
    write(source / "payments.jsonl", payments)
    silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"),
                        str(source / "payments.jsonl"), silver, input_complete=True)
    assert gold_transactions(silver, gold, silver, scope_aware=True)["status"] == "PASS"
    assert gold_funnels(silver, silver, silver, gold, scope_aware=True)["status"] == "PASS"


def test_unknown_failure_code_is_quarantined_and_gold_stays_previous_until_corrected(tmp_path):
    example = make_example(tmp_path)
    source, silver, gold = example["source"], str(example["silver"]), str(example["gold"])
    payments = [json.loads(line) for line in (source / "payments.jsonl").read_text().splitlines()]
    failed = next(row for row in payments if row["status"] == "FAILED")
    failed["failure_code"] = "PG_NEW_ERROR"
    write(source / "payments.jsonl", payments)
    manifest = silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"),
                                   str(source / "payments.jsonl"), silver, input_complete=True)
    assert any(row["field"] == "failure_code" and row["error_code"] == "INVALID_VALUE"
               for row in read_rows(manifest["outputs"]["quarantined_records"]))
    pointer = Path(example["manifests"]["transactions"]["manifest_path"])
    before = pointer.read_bytes()
    with pytest.raises(ValueError, match="품질"):
        gold_transactions(silver, gold, silver)
    assert pointer.read_bytes() == before
    failed["failure_code"] = "PG_TIMEOUT"
    write(source / "payments.jsonl", payments)
    silver_transactions(str(source / "orders.jsonl"), str(source / "items.jsonl"),
                        str(source / "payments.jsonl"), silver, input_complete=True)
    recovered = gold_transactions(silver, gold, silver, scope_aware=True)
    assert recovered["status"] == "PASS"


def test_all_six_datasets_and_late_payment(tmp_path):
    example = make_example(tmp_path)
    output = {name: read_outputs(value) for name, value in example["manifests"].items()}
    product = output["transactions"]["product_sales_daily.jsonl"]
    assert [(row["sales_date_kst"], row["sold_quantity"], row["product_code"]) for row in product] == [
        ("2026-10-18", 1, 100), ("2026-10-19", 2, 100)]
    funnel = output["funnels"]["funnel_daily.jsonl"]
    first = next(row for row in funnel if row["article_id"] == "0001")
    assert (first["view_sessions"], first["cart_sessions"], first["order_sessions"], first["paid_sessions"]) == (3, 1, 2, 2)
    assert first["view_to_paid_rate"] == 0.666667
    assert first["cart_order_sessions"] == 1
    detail = output["funnels"]["funnel_session_product.jsonl"]
    late = next(row for row in detail if row["session_id"] == "S1")
    assert late["first_view_at_kst"].startswith("2026-10-18") and late["first_paid_at_kst"].startswith("2026-10-19")
    direct = next(row for row in detail if row["session_id"] == "S3")
    assert direct["has_paid"] and not direct["has_cart"]
    reviews = output["reviews"]["year=2026/month=10/day=19/part-00000.jsonl"]
    first_review = next(row for row in reviews if row["article_id"] == "0001")
    assert first_review == {"review_date_kst": "2026-10-19", "article_id": "0001", "product_code": 100,
                            "review_count": 2, "rating_sum": 7, "average_rating": 3.5,
                            "low_rating_count": 1, "low_rating_rate": 0.5}
    quality = next(row for row in output["aspects"]["review_aspect_daily.jsonl"]
                   if row["article_id"] == "0001" and row["aspect"] == "품질·내구성")
    assert (quality["scored_review_count"], quality["score_neg2_count"], quality["score_pos1_count"]) == (2, 1, 1)
    assert quality["score_sum"] == -1 and quality["average_score"] == -0.5
    assert "negative_rate" not in quality


def test_partial_review_replace_preserves_other_product_and_deletes_zero(tmp_path):
    example = make_example(tmp_path)
    rows = example["reviews"]
    changed = [dict(row, rating=4) if row["review_id"] == "R1" else dict(row, rating=5) for row in rows if row["review_id"] != "R2"]
    write_reviews(example["source"], changed)
    silver_reviews(str(example["source"]), str(example["silver"]), START, END)
    scope = replacement("2026-10-19", "2026-10-19", ["0001"])
    pointer_path = Path(example["manifests"]["reviews"]["manifest_path"])
    for _ in range(2):
        run_aggregate(str(example["silver"]), str(example["gold"]), START, END,
                      str(example["silver"]), str(example["mapping"]), scope)
        result = read_outputs(pointer(pointer_path))["year=2026/month=10/day=19/part-00000.jsonl"]
        assert next(row for row in result if row["article_id"] == "0001")["average_rating"] == 4
        assert next(row for row in result if row["article_id"] == "0002")["average_rating"] == 1
    changed = [row for row in changed if row["review_id"] != "R1"]
    write_reviews(example["source"], changed)
    silver_reviews(str(example["source"]), str(example["silver"]), START, END)
    run_aggregate(str(example["silver"]), str(example["gold"]), START, END,
                  str(example["silver"]), str(example["mapping"]), scope)
    result = read_outputs(pointer(pointer_path))["year=2026/month=10/day=19/part-00000.jsonl"]
    assert len(result) == 1 and result[0]["article_id"] == "0002"
    assert pointer(pointer_path)["previous_result"]["outputs"]


def test_mapping_analysis_conflict_and_score_adapter(tmp_path):
    example = make_example(tmp_path)
    with pytest.raises(ValueError, match="상품 연결"):
        connect_reviews(example["reviews"], example["variants"])
    connected = connect_reviews(example["reviews"], example["variants"], [{"product_id": "alias-0001", "article_id": "0001"}])
    connected = [{**row, "review_date_kst": row["created_at"][:10]} for row in connected]
    with pytest.raises(ValueError, match="충돌"):
        aggregate_aspects(connected, example["analysis"] + [dict(example["analysis"][0], score=2)], "demo.v1")
    csv_path = example["source"] / "scores.csv"
    csv_path.write_text("review_id,aspect,score\nR1,품질·내구성,-2\nR2,품질·내구성,2\n", encoding="utf-8")
    analysis = load_analysis(str(csv_path), "score.v1")
    rows, coverage = aggregate_aspects(connected, analysis, "score.v1")
    assert rows[0]["average_score"] == 0 and rows[0]["score_neg2_count"] == 1 and rows[0]["score_pos2_count"] == 1
    assert coverage["reviews_without_aspect_result"] == 2
    assert len(rows) == 1


def test_partial_funnels_and_transactions_keep_other_product(tmp_path):
    example = make_example(tmp_path)
    scope = replacement("2026-10-18", "2026-10-19", ["0001"])
    orders = read_rows(str(example["source"] / "orders.jsonl"))
    items = read_rows(str(example["source"] / "items.jsonl"))
    payments = read_rows(str(example["source"] / "payments.jsonl"))
    orders = [dict(row, total_amount=30000) if row["order_id"] == "O1" else row for row in orders]
    items = [dict(row, quantity=3) if row["order_id"] == "O1" else row for row in items]
    payments = [dict(row, amount=30000) if row["order_id"] == "O1" else
                dict(row, status="SUCCESS", failure_code=None) if row["order_id"] == "O3" else row for row in payments]
    for name, rows in (("orders", orders), ("items", items), ("payments", payments)):
        write(example["source"] / (name + ".jsonl"), rows)
    silver_transactions(str(example["source"] / "orders.jsonl"), str(example["source"] / "items.jsonl"),
                        str(example["source"] / "payments.jsonl"), str(example["silver"]))
    clicks = read_rows(str(example["source"] / "clicks.jsonl"))
    write(example["source"] / "clicks.jsonl", [row for row in clicks if not (row["session_id"] == "S1" and row["event_type"] == "cart_add")])
    silver_clicks(str(example["source"] / "clicks.jsonl"), str(example["silver"]))
    trade = gold_transactions(str(example["silver"]), str(example["gold"]), str(example["silver"]), scope)
    funnels = gold_funnels(str(example["silver"]), str(example["silver"]), str(example["silver"]), str(example["gold"]), scope)
    output = read_outputs(trade)
    assert all(row["article_id"] == "0001" for row in output["product_sales_daily.jsonl"])
    assert next(row for row in output["product_sales_daily.jsonl"] if row["sales_date_kst"] == "2026-10-19")["sold_quantity"] == 3
    # 전체 주문 시간 지표는 상품 필터와 관계없이 해당 날짜 전체를 다시 계산한다.
    assert sum(row["approved_amount"] for row in output["order_sales_hourly.jsonl"]) == 45000
    details = read_outputs(funnels)["funnel_session_product.jsonl"]
    assert not next(row for row in details if row["session_id"] == "S1")["has_cart"]
    assert not next(row for row in details if row["session_id"] == "S4")["has_paid"]
    assert trade["previous_result"] and funnels["previous_result"]
    # 조회만 한 방문은 0/0 비율을 0이 아니라 NULL로 표현한다.
    check = [{"status": "PASS", "quarantined_count": 0}]
    clicks = {"dq_results": check, "click_events": [{"event_id": "E-only", "event_type": "view",
              "session_id": "only", "article_id": "0001", "event_time_kst": "2026-10-18T10:00:00+09:00"}]}
    trade = {"dq_results": check, "orders_current": [], "silver_order_items": [], "payment_attempts": []}
    row = build_funnels(clicks, trade, example["variants"])["funnel_daily"][0]
    assert row["cart_to_order_rate"] is None and row["order_to_paid_rate"] is None


def test_aspect_partial_replace_preserves_other_product(tmp_path):
    example = make_example(tmp_path)
    modified = [dict(row, score=2) if row["review_id"] in {"R1", "R4"} else row for row in example["analysis"]]
    write(example["source"] / "analysis.jsonl", modified)
    result = run_aspects(str(example["silver"]), str(example["gold"]), START, END, str(example["silver"]),
                         str(example["source"] / "analysis.jsonl"), "demo.v1", str(example["mapping"]),
                         replacement("2026-10-19", "2026-10-19", ["0001"]))
    rows = read_outputs(result)["review_aspect_daily.jsonl"]
    assert next(row for row in rows if row["article_id"] == "0001" and row["aspect"] == "품질·내구성")["average_score"] == 1.5
    assert next(row for row in rows if row["article_id"] == "0002" and row["review_date_kst"] == "2026-10-19")["average_score"] == -1


def test_five_scores_are_preserved_and_sentiment_is_not_inferred():
    reviews = [{"review_id": str(score), "review_date_kst": "2026-10-19", "article_id": "0001", "product_code": 100}
               for score in range(-2, 3)]
    predictions = [{"review_id": str(score), "aspect": "품질·내구성", "score": score, "model_version": "v1"}
                   for score in range(-2, 3)]
    rows, _ = aggregate_aspects(reviews, predictions + [dict(predictions[0], extra_metadata="ignored")], "v1")
    row = rows[0]
    assert row["scored_review_count"] == 5 and row["score_sum"] == 0 and row["average_score"] == 0
    assert all(row[field] == 1 for field in ("score_neg2_count", "score_neg1_count", "score_zero_count", "score_pos1_count", "score_pos2_count"))
    for invalid in (None, True, 1.0, "1", -3, 3):
        with pytest.raises(ValueError, match="score"):
            aggregate_aspects(reviews, [dict(predictions[0], score=invalid)], "v1")
    with pytest.raises(ValueError, match="score"):
        aggregate_aspects(reviews, [{"review_id": "0", "aspect": "품질·내구성", "sentiment": "중립", "model_version": "v1"}], "v1")


def test_legacy_aspect_output_blocks_partial_until_full_rebuild(tmp_path):
    example = make_example(tmp_path)
    path = Path(example["manifests"]["aspects"]["manifest_path"])
    legacy = pointer(path)
    legacy["inputs"].pop("aspect_schema")
    path.write_text(json.dumps(legacy), encoding="utf-8")
    previous = path.read_bytes()
    arguments = (str(example["silver"]), str(example["gold"]), START, END, str(example["silver"]),
                 str(example["source"] / "analysis.jsonl"), "demo.v1", str(example["mapping"]))
    with pytest.raises(ValueError, match="전체 재집계"):
        run_aspects(*arguments, replacement("2026-10-19", "2026-10-19", ["0001"]))
    assert path.read_bytes() == previous
    rebuilt = run_aspects(*arguments)
    assert rebuilt["inputs"]["aspect_schema"] == "score.v1"
    assert run_aspects(*arguments, replacement("2026-10-19", "2026-10-19", ["0001"]))["status"] == "PASS"
