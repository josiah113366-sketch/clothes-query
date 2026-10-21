"""신뢰성 쿼리 Q1·Q2를 가짜 장부에 돌려 보는 시험. (sqlite 사용. Q3는 시각 계산만 파이썬으로 같은 기준을 시험)"""
import sqlite3, random
from datetime import datetime, timedelta

def build(rng, gaps=0, dups=0, pay_dups=0):
    con = sqlite3.connect(":memory:")
    con.execute("create table topic_messages(topic text, kafka_partition int, kafka_offset int, kafka_timestamp text, loaded_at text)")
    con.execute("create table payment_events(payment_id text, completed_at text)")
    t0 = datetime(2026, 10, 20, 8, 0)
    for p in range(2):
        for off in range(300):
            ts = (t0 + timedelta(seconds=off * 2)).isoformat()
            con.execute("insert into topic_messages values('orders',?,?,?,?)", (p, off, ts, ts))
    # 누락 심기: 파티션 0의 중간 offset 삭제
    for k in range(gaps):
        con.execute("delete from topic_messages where kafka_partition=0 and kafka_offset=?", (100 + k * 7,))
    # 중복 심기: 같은 위치를 한 번 더 쌓음
    for k in range(dups):
        con.execute("insert into topic_messages select * from topic_messages where kafka_partition=1 and kafka_offset=?", (50 + k,))
    for i in range(100):
        con.execute("insert into payment_events values(?,?)", (f"p{i}", (t0 + timedelta(seconds=i)).isoformat()))
    for k in range(pay_dups):
        con.execute("insert into payment_events values(?,?)", (f"p{k}", (t0 + timedelta(seconds=k)).isoformat()))
    return con

Q1 = """SELECT topic, kafka_partition,
 (MAX(kafka_offset)-MIN(kafka_offset)+1) - COUNT(DISTINCT kafka_offset) AS missing_count
FROM topic_messages WHERE kafka_timestamp >= :a AND kafka_timestamp < :b
GROUP BY topic, kafka_partition
HAVING (MAX(kafka_offset)-MIN(kafka_offset)+1) - COUNT(DISTINCT kafka_offset) > 0"""
Q2a = """SELECT COUNT(*) - COUNT(DISTINCT topic||'-'||kafka_partition||'-'||kafka_offset) FROM topic_messages
WHERE kafka_timestamp >= :a AND kafka_timestamp < :b"""
Q2b = "SELECT COUNT(*) - COUNT(DISTINCT payment_id) FROM payment_events WHERE completed_at >= :a AND completed_at < :b"

def stopped(last_seen, now, limit=120):
    return "STOPPED" if (now - last_seen).total_seconds() > limit else "OK"

rng = random.Random(1)
a, b = "2026-10-20T00:00:00", "2026-10-21T00:00:00"
ok = True
def check(name, got, want):
    global ok
    good = got == want; ok &= good
    print(("통과 " if good else "실패 ") + name, "| 결과:", got, "| 기대:", want)

con = build(rng)                       # 깨끗한 장부
check("Q1 정상 장부는 누락 0줄", con.execute(Q1, dict(a=a, b=b)).fetchall(), [])
check("Q2 정상 장부 메시지 중복 0", con.execute(Q2a, dict(a=a, b=b)).fetchone()[0], 0)
check("Q2 정상 장부 결제 중복 0", con.execute(Q2b, dict(a=a, b=b)).fetchone()[0], 0)
con = build(rng, gaps=3)               # 누락 3개 심음
check("Q1 누락 3개 찾음", con.execute(Q1, dict(a=a, b=b)).fetchall(), [("orders", 0, 3)])
con = build(rng, dups=5, pay_dups=4)   # 중복 심음
check("Q2 메시지 중복 5 찾음", con.execute(Q2a, dict(a=a, b=b)).fetchone()[0], 5)
check("Q2 결제 중복 4 찾음", con.execute(Q2b, dict(a=a, b=b)).fetchone()[0], 4)
now = datetime(2026, 10, 20, 9, 0, 0)
check("Q3 1분 전까지 썼으면 OK", stopped(now - timedelta(seconds=60), now), "OK")
check("Q3 3분 전에 멈췄으면 STOPPED", stopped(now - timedelta(seconds=180), now), "STOPPED")
check("Q3 정확히 120초는 OK(2분 넘게 멈추면 고장)", stopped(now - timedelta(seconds=120), now), "OK")
print("전체:", "모두 통과" if ok else "실패 있음")
