"""적재 결과 확인 (읽기 전용). 원본 Parquet와 DB를 둘 다 읽어 비교한다.

출력에는 컬럼 이름, 건수, 최대 5개의 키(product_code / article_id)만 담는다. 상품 값 전체는 쏟아내지 않는다.
"""

from collections import Counter
from dataclasses import dataclass

import psycopg

from sim.common.db import safe_db_errors
from sim.common.rng import SimRandom
from sim.product import params, source

Columns = dict[str, list]
Data = dict[str, Columns]  # 테이블 이름 → 컬럼 이름 → 값 목록


@dataclass(frozen=True)
class CheckResult:
    number: int
    name: str
    passed: bool
    detail: str


def _size(columns: Columns) -> int:
    return len(next(iter(columns.values()))) if columns else 0


def _examples(keys: list) -> str:
    shown = ", ".join(str(key) for key in keys[: params.MAX_EXAMPLES])
    return f" (예: {shown})" if shown else ""


def check_row_counts(src: Data, db: Data) -> CheckResult:
    parts = [f"{t} {_size(db[t]):,}/{_size(src[t]):,}" for t in params.TABLES]
    passed = all(_size(src[t]) == _size(db[t]) for t in params.TABLES)
    return CheckResult(1, "행 수", passed, "DB/Parquet: " + ", ".join(parts))


def check_keys(db: Data) -> CheckResult:
    parts: list[str] = []
    passed = True
    for table in params.TABLES:
        key = params.KEY_COLUMN[table]
        values = db[table][key]
        nulls = sum(1 for v in values if v is None)
        duplicates = len(values) - len(set(values))
        passed = passed and nulls == 0 and duplicates == 0
        parts.append(f"{table}.{key} 중복 {duplicates:,}, NULL {nulls:,}")
    return CheckResult(2, "키", passed, ", ".join(parts))


def check_references(db: Data) -> CheckResult:
    design_codes = set(db[params.DESIGN_TABLE]["product_code"])
    variant = db[params.VARIANT_TABLE]
    orphans = [
        article
        for article, code in zip(variant["article_id"], variant["product_code"], strict=True)
        if code not in design_codes
    ]
    without_variant = len(design_codes - set(variant["product_code"]))
    detail = (
        f"고아 variant {len(orphans):,}개{_examples(orphans)}, "
        f"variant 없는 design {without_variant:,}개 (보고만)"
    )
    return CheckResult(3, "참조 무결성", not orphans, detail)


def check_article_id(db: Data) -> CheckResult:
    ids = db[params.VARIANT_TABLE]["article_id"]
    not_digits = [i for i in ids if not (isinstance(i, str) and i.isdigit())]
    lengths = sorted({len(i) for i in ids if isinstance(i, str)})
    passed = not not_digits and len(lengths) <= 1
    detail = f"숫자가 아닌 값 {len(not_digits):,}개{_examples(not_digits)}, 길이 {lengths}"
    return CheckResult(4, "article_id 형식", passed, detail)


def _is_unknown(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == params.UNKNOWN_WORD


def check_no_unknown(db: Data) -> CheckResult:
    hits: list[str] = []
    for table in params.TABLES:
        for column, values in db[table].items():
            if not column.endswith("_name"):
                continue
            count = sum(1 for v in values if _is_unknown(v))
            if count:
                hits.append(f"{table}.{column} {count:,}건")
    detail = "Unknown 0건" if not hits else "Unknown 있음: " + ", ".join(hits)
    return CheckResult(5, "Unknown 제외", not hits, detail)


def price_ok(price: object) -> bool:
    """5,900 이상이고 500원 단위(5,900, 6,400, 6,900 … → 끝자리 900 또는 400)."""
    return isinstance(price, int) and price >= params.PRICE_MIN and price % params.PRICE_STEP == 400


def check_price_rule(db: Data) -> CheckResult:
    design = db[params.DESIGN_TABLE]
    bad = [
        code
        for code, price in zip(design["product_code"], design["design_price"], strict=True)
        if not price_ok(price)
    ]
    detail = (
        f"규칙(5,900 이상, 500원 단위)에 어긋나는 design {len(bad):,}개{_examples(bad)}"
        if bad
        else "design_price 전부 규칙 안 (5,900 이상, 끝자리 900 또는 400)"
    )
    return CheckResult(6, "가격 규칙", not bad, detail)


def _aggregates(columns: Columns) -> dict[str, object]:
    """숫자 컬럼은 합, 문자 컬럼은 서로 다른 값 개수, *_name 컬럼은 값별 행 수."""
    out: dict[str, object] = {}
    for column, values in columns.items():
        if values and isinstance(values[0], str):
            out[f"{column}:distinct"] = len(set(values))
        else:
            out[f"{column}:sum"] = sum(v for v in values if v is not None)
        if column.endswith("_name"):
            out[f"{column}:groups"] = Counter(values)
    return out


def check_aggregates(src: Data, db: Data) -> CheckResult:
    differing: list[str] = []
    for table in params.TABLES:
        a, b = _aggregates(src[table]), _aggregates(db[table])
        differing += [f"{table}.{key.split(':')[0]}" for key in a if a[key] != b.get(key)]
    unique = sorted(set(differing))
    detail = (
        "컬럼별 집계 일치"
        if not unique
        else f"집계가 다른 컬럼 {len(unique)}개: {', '.join(unique[:10])}"
    )
    return CheckResult(7, "원본과 같은 값(집계)", not unique, detail)


def check_sample(src: Data, db: Data) -> CheckResult:
    rng = SimRandom(params.SAMPLE_SEED)
    mismatched: list[str] = []
    checked = 0
    for table in params.TABLES:
        key = params.KEY_COLUMN[table]
        names = source.column_names(table)
        total = _size(src[table])
        indexes = rng.random.sample(range(total), min(params.SAMPLE_SIZE, total))
        db_index = {k: i for i, k in enumerate(db[table][key])}
        for i in indexes:
            checked += 1
            row_key = src[table][key][i]
            j = db_index.get(row_key)
            if j is None or any(src[table][c][i] != db[table][c][j] for c in names):
                mismatched.append(f"{table}:{row_key}")
    detail = f"{checked:,}행 대조, 다른 행 {len(mismatched):,}개{_examples(mismatched)}"
    return CheckResult(8, "샘플 대조", not mismatched, detail)


def evaluate(src: Data, db: Data) -> list[CheckResult]:
    """순수 함수: 원본 데이터와 DB 데이터를 받아 8개 항목 결과를 돌려준다."""
    return [
        check_row_counts(src, db),
        check_keys(db),
        check_references(db),
        check_article_id(db),
        check_no_unknown(db),
        check_price_rule(db),
        check_aggregates(src, db),
        check_sample(src, db),
    ]


def read_source(source_path: str) -> Data:
    found = source.inspect_source(source_path)
    return {t: source.read_columns(found[t].parquet, t) for t in params.TABLES}


def read_db(conn: psycopg.Connection) -> Data:
    data: Data = {}
    with safe_db_errors():
        for table in params.TABLES:
            names = source.column_names(table)
            order = params.KEY_COLUMN[table]
            rows = conn.execute(
                f"SELECT {', '.join(names)} FROM {table} ORDER BY {order}"
            ).fetchall()
            data[table] = {name: [row[i] for row in rows] for i, name in enumerate(names)}
    return data


def run_verify(conn: psycopg.Connection, source_path: str) -> list[CheckResult]:
    return evaluate(read_source(source_path), read_db(conn))
