import copy

from product_fixtures import make_data

from sim.product import params, verify


def results(src, db):
    return {r.number: r for r in verify.evaluate(src, db)}


def failed(src, db) -> list[int]:
    return [n for n, r in results(src, db).items() if not r.passed]


def test_clean_data_passes_all_eight() -> None:
    src = make_data()
    out = results(src, copy.deepcopy(src))
    assert sorted(out) == list(range(1, 9))
    assert all(r.passed for r in out.values())


def test_orphan_variant_fails_check_3() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.VARIANT_TABLE]["product_code"][0] = 999_999
    out = results(src, db)
    assert not out[3].passed and "고아 variant 1개" in out[3].detail


def test_design_without_variant_is_only_reported() -> None:
    src = make_data(designs=5, variants_each=1)
    db = copy.deepcopy(src)
    for column in db[params.VARIANT_TABLE]:
        db[params.VARIANT_TABLE][column] = db[params.VARIANT_TABLE][column][:-1]
    for column in src[params.VARIANT_TABLE]:
        src[params.VARIANT_TABLE][column] = src[params.VARIANT_TABLE][column][:-1]
    out = results(src, db)
    assert out[3].passed and "variant 없는 design 1개" in out[3].detail


def test_unknown_name_fails_check_5_case_insensitive() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.DESIGN_TABLE]["product_group_name"][2] = "UNKNOWN"
    assert 5 in failed(src, db)


def test_price_below_floor_or_wrong_ending_fails_check_6() -> None:
    for bad in (5_800, 6_000, 6_500, 4_900):
        src = make_data()
        src[params.DESIGN_TABLE]["design_price"][0] = bad
        assert 6 in failed(src, copy.deepcopy(src)), bad


def test_price_rule_accepts_900_and_400_endings() -> None:
    assert all(verify.price_ok(p) for p in (5_900, 6_400, 6_900, 7_400, 448_900))
    assert not any(verify.price_ok(p) for p in (5_400, 5_800, 6_000, 6_500, 0, None, 5_900.0))


def test_mixed_article_id_length_fails_check_4() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.VARIANT_TABLE]["article_id"][0] = "123456789"  # 9자리: 앞자리 0이 사라진 모양
    assert 4 in failed(src, db)


def test_non_digit_article_id_fails_check_4() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.VARIANT_TABLE]["article_id"][0] = "12345678ab"
    assert 4 in failed(src, db)


def test_one_changed_value_fails_checks_7_and_8() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.DESIGN_TABLE]["design_price"][3] += 500
    assert {7, 8} <= set(failed(src, db))


def test_one_changed_text_value_fails_checks_7_and_8() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.VARIANT_TABLE]["prod_name"][4] = "other"
    assert {7, 8} <= set(failed(src, db))


def test_row_count_difference_fails_check_1() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    for column in db[params.VARIANT_TABLE]:
        db[params.VARIANT_TABLE][column] = db[params.VARIANT_TABLE][column][:-1]
    assert 1 in failed(src, db)


def test_duplicate_key_fails_check_2() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.DESIGN_TABLE]["product_code"][1] = db[params.DESIGN_TABLE]["product_code"][0]
    assert 2 in failed(src, db)


def test_details_show_at_most_five_keys_and_no_row_values() -> None:
    src = make_data(designs=40)
    db = copy.deepcopy(src)
    for i in range(10):
        db[params.DESIGN_TABLE]["design_price"][i] = 5_800
    detail = results(src, db)[6].detail
    assert detail.count("1000") <= 5  # product_code 100000~ 중 최대 5개
    assert "type" not in detail and "garment" not in detail


def test_sample_check_is_reproducible() -> None:
    src = make_data()
    db = copy.deepcopy(src)
    db[params.DESIGN_TABLE]["design_price"][3] += 500
    assert results(src, db)[8].detail == results(src, db)[8].detail
