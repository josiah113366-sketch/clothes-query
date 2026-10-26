"""흐름도 새로 이은 3단계 시험 (이상 탐지, Silver 리뷰, 감성 점수. 파이프라인 상태 › 데이터 흐름 탭).

진짜 Athena·S3 대신 가짜를 끼워 SQL 조건(기간·표 이름)과 상태 판정(ok/warn)을 본다.
표가 비었을 때 '이상 없음'(ok)과 '점수 기록 없음'(warn)이 구분되는지, S3 포인터가 PASS 가 아니면 warn 인지도 본다.

실행: python test_flow_status.py   (dashboard 폴더에서. streamlit·pandas 가 있어야 한다)
"""
import io
import json
import sys
import types
from datetime import datetime, timezone

import pandas as pd

import data

ok = True
NOW = pd.Timestamp("2026-10-26 02:30:00", tz="UTC")


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(("통과 " if good else "실패 ") + name + ("" if good else f" | 결과: {got!r} | 기대: {want!r}"))


class FakeAthena:
    """data._athena 처럼 값이 모두 글자인 DataFrame 을 돌려주고 받은 SQL 을 남긴다."""

    def __init__(self, columns, rows):
        self.columns, self.rows, self.sql = columns, rows, []

    def __call__(self, sql):
        self.sql.append(sql)
        return pd.DataFrame([[None if v is None else str(v) for v in r] for r in self.rows], columns=self.columns)


# --- 이상 탐지 ---
f = FakeAthena(["open_n", "total_n", "last_at"], [[0, 0, None]])
data._athena = f
st_, label, detail = data._flow_from_anomaly(NOW)["anomaly"]
check("이상: 표가 비면 ok (이상 없음이 정상)", (st_, label), ("ok", "이상 없음"))
check("이상: 최근 14일 조건", "TIMESTAMP '2026-10-12 02:30:00'" in f.sql[0] and "gold_b.anomaly_current" in f.sql[0], True)

data._athena = FakeAthena(["open_n", "total_n", "last_at"], [[2, 5, "2026-10-26 01:10:00.000"]])
st_, label, detail = data._flow_from_anomaly(NOW)["anomaly"]
check("이상: OPEN 이 있으면 warn", (st_, label), ("warn", "OPEN 2건"))
check("이상: 마지막 탐지는 KST 로", "10-26 10:10" in detail, True)

data._athena = FakeAthena(["open_n", "total_n", "last_at"], [[0, 3, "2026-10-25 00:00:00.000"]])
check("이상: 전부 RESOLVED 면 ok", data._flow_from_anomaly(NOW)["anomaly"][:2], ("ok", "OPEN 없음"))

# --- 감성 점수 ---
f = FakeAthena(["last_at", "n", "ver"], [["2026-10-26 00:40:00.000", 1234, "s2c-v3"]])
data._athena = f
st_, label, detail = data._flow_from_review_score(NOW)["r_score"]
check("점수: 최근 분석이면 ok", (st_, label), ("ok", "10-26 09:40 분석"))
check("점수: 후기 수·모델이 설명에", "1,234건" in detail and "s2c-v3" in detail, True)
check("점수: review_score_log 를 review_date 로 자름", "review_score_log" in f.sql[0] and "review_date >= DATE '" in f.sql[0], True)

data._athena = FakeAthena(["last_at", "n", "ver"], [["2026-10-24 00:40:00.000", 10, "s2c-v3"]])
check("점수: 26시간 넘게 오래되면 warn", data._flow_from_review_score(NOW)["r_score"][0], "warn")

data._athena = FakeAthena(["last_at", "n", "ver"], [[None, 0, None]])
check("점수: 행이 없으면 warn(점수 기록 없음)", data._flow_from_review_score(NOW)["r_score"][:2], ("warn", "점수 기록 없음"))


# --- Silver 리뷰 (S3 current.json) ---
class FakeS3:
    def __init__(self, body, modified):
        self.body, self.modified, self.keys = body, modified, []

    def get_object(self, Bucket, Key):
        self.keys.append((Bucket, Key))
        return {"Body": io.BytesIO(json.dumps(self.body).encode()), "LastModified": self.modified}


def with_s3(fake):
    mod = types.ModuleType("boto3")
    mod.client = lambda *a, **k: fake
    sys.modules["boto3"] = mod


fake = FakeS3({"run_id": "reviews-v2-20261026T001000Z", "status": "PASS"}, datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc))
with_s3(fake)
st_, label, detail = data._flow_from_review_silver(NOW)["r_silver"]
check("Silver 리뷰: PASS·최근이면 ok", (st_, label), ("ok", "10-26 10:00 공개"))
check("Silver 리뷰: 읽는 키", fake.keys, [(data.DATALAKE_BUCKET, "silver/runtime/reviews/current.json")])
check("Silver 리뷰: run_id 가 설명에", "reviews-v2-20261026T001000Z" in detail, True)

with_s3(FakeS3({"run_id": "x", "status": "PARTIAL"}, datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)))
check("Silver 리뷰: PASS 가 아니면 warn", data._flow_from_review_silver(NOW)["r_silver"][0], "warn")

with_s3(FakeS3({"run_id": "x", "status": "PASS"}, datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)))
check("Silver 리뷰: 오래되면 warn", data._flow_from_review_silver(NOW)["r_silver"][0], "warn")

# --- 묶음 등록 ---
ids = [i for _, group in data._FLOW_READERS for i in group]
check("묶음에 새 3단계 등록", {"anomaly", "r_silver", "r_score"} <= set(ids), True)

print("전체 통과" if ok else "실패 있음")
sys.exit(0 if ok else 1)
