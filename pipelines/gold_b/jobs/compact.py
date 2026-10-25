"""Gold B 파일 합치기: 끝난 UTC 하루의 시간 폴더마다 작은 Parquet 파일을 하나로 합친다 (6단계).

적재 잡과 수집기는 1분마다 파일을 하나씩 만들어서 한 시간 폴더에 60개 넘게 쌓인다. 파일이 많으면 Athena 조회가 느려지고 비싸진다.
설계는 docs/design/gold-b/README.md 6단계, 기본값과 부르는 방법은 같은 폴더의 README.md.

run(day) 한 번에 하는 일
  1. 그 날(UTC)이 끝나고 여유 시간(10분)이 지났는지 확인한다. 안 지났으면 거부한다.
  2. 원장 4개 × 24개 시간 폴더마다 파일 목록을 읽는다.
  3. 앞선 실행이 합친 파일을 쓰고 원래 파일을 다 못 지웠으면, 남은 원래 파일부터 지운다 (합친 파일에 원래 파일 이름이 적혀 있다).
  4. 파일이 2개 이상이면 줄을 하나도 빼거나 고치지 않고 한 파일로 합친다. 새 파일의 줄 수를 확인한 뒤 원래 파일을 지운다.

중복 줄도 그대로 둔다. topic_messages의 같은 위치 두 줄은 탐지가 보는 신뢰성 신호다.
재처리 잡과 같은 시간에 돌리면 안 된다 (재처리는 승인 범위 밖 결제 시각 폴더도 고친다. DAG에서 한 번에 하나씩 돌린다).
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Callable, Mapping, Sequence
import uuid

from pipelines.gold_b.ledger import HOUR, Store, hour_folder, open_store, utc_naive

LEDGERS = ("payment_events", "topic_messages", "bronze_lag_snapshots", "malformed_events")
COMPACTED_FROM = "gold_b.compacted_from"   # 합친 파일에 적는 원래 파일 이름 목록 (JSON)
PREFIX = "part-compact-"                    # 합친 파일 이름의 앞부분


class CompactError(RuntimeError):
    """합치기를 시작하지 않았거나 끝내지 못했다."""


def _name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def finish_previous(store: Store, files: Sequence[str]) -> list[str]:
    """앞선 실행이 합친 파일을 쓰고 원래 파일을 못 지웠으면 그 원래 파일을 지운다. 남은 파일 목록을 돌려준다.

    다시 합치면 같은 줄이 두 번 들어가므로, 이미 합친 원래 파일은 합치지 않고 지운다.
    """
    by_name = {_name(path): path for path in files}
    leftovers: set[str] = set()
    for path in files:
        if not _name(path).startswith(PREFIX):   # 합친 파일만 원래 파일 목록이 있다 (S3에서 파일마다 읽지 않게)
            continue
        sources = json.loads(store.metadata(path).get(COMPACTED_FROM, "[]"))
        leftovers.update(by_name[name] for name in sources if name in by_name and by_name[name] != path)
    if leftovers:
        store.delete(sorted(leftovers))
    return [path for path in files if path not in leftovers]


def compact_folder(store: Store, table: str, hour: datetime, stamp: str) -> dict | None:
    """시간 폴더 하나를 합친다. 합칠 것이 없으면 None."""
    folder = hour_folder(table, hour)
    files = finish_previous(store, store.files(folder))
    if len(files) < 2:
        return None
    rows = [row for path in files for row in store.read(path, table)]
    target = f"{folder}/{PREFIX}{stamp}-{uuid.uuid4().hex[:8]}.parquet"
    store.write(target, table, rows, metadata={COMPACTED_FROM: json.dumps([_name(p) for p in files])})
    written = len(store.read(target, table))
    if written != len(rows):   # 원래 파일은 그대로 두고 멈춘다
        raise CompactError(f"{table} {hour:%Y-%m-%d %H}시: 합친 파일의 줄 수가 다르다 ({written} != {len(rows)})")
    store.delete(files)
    return {"table": table, "hour": hour, "files": len(files), "rows": len(rows)}


def _log(message: str) -> None:
    print(message, flush=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run(day: date, *, store: Store, tables: Sequence[str] = LEDGERS, margin: timedelta = timedelta(minutes=10),
        now: Callable[[], datetime] = _utc_now, log: Callable[[str], None] = _log) -> list[dict]:
    """그 날(UTC)의 시간 폴더를 합치고, 합친 폴더 목록을 돌려준다."""
    start = datetime.combine(day, time())
    current = utc_naive(now())
    if start + timedelta(days=1) + margin > current:
        raise CompactError(f"{day:%Y-%m-%d}(UTC)이 아직 끝나지 않았다 (끝 + {int(margin.total_seconds() // 60)}분 뒤에 합친다)")
    stamp = f"{current:%Y%m%dT%H%M%SZ}"
    done = []
    for table in tables:
        for i in range(24):
            result = compact_folder(store, table, start + HOUR * i, stamp)
            if result:
                done.append(result)
    log(f"파일 합치기 {day:%Y-%m-%d}: 폴더 {len(done)}개, 원래 파일 {sum(r['files'] for r in done)}개 → "
        f"{len(done)}개, 줄 {sum(r['rows'] for r in done)}개")
    return done


# ---------- 실행 입구 ----------

ENV_LEDGER_ROOT = "GOLD_B_LEDGER_ROOT"    # s3://<버킷>/gold_b 또는 로컬 폴더 (필수)
ENV_DAY = "GOLD_B_COMPACT_DAY"            # 합칠 날 (YYYY-MM-DD, 선택). Airflow DAG가 날짜 입력(day)을 넣는다. 비면 어제(UTC)


def _day(value: str) -> date | None:
    """합칠 날 (--day 또는 GOLD_B_COMPACT_DAY). 비어 있으면 None(어제 UTC). 형식이 틀리면 ArgumentTypeError."""
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("합칠 날은 YYYY-MM-DD 형식이어야 한다") from None


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None,
         now: Callable[[], datetime] = _utc_now, log: Callable[[str], None] = _log) -> int:
    """하루치(UTC) 시간 폴더를 합친다. Airflow DAG가 하루 1번 부른다. 성공하면 0, 실패하면 1.
    합칠 날은 --day, 없으면 환경변수 GOLD_B_COMPACT_DAY(DAG의 날짜 입력), 둘 다 비면 어제(UTC)다."""
    import os

    parser = argparse.ArgumentParser(prog="python -m pipelines.gold_b.jobs.compact",
                                     description="Gold B 파일 합치기: 끝난 UTC 하루의 시간 폴더마다 파일을 하나로 합친다")
    parser.add_argument("--day", type=_day, help="합칠 날 (UTC, YYYY-MM-DD). 생략하거나 비우면 어제(UTC)")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    root = (env.get(ENV_LEDGER_ROOT) or "").strip()
    if not root:
        log(f"{ENV_LEDGER_ROOT}가 없다")
        return 1
    try:
        chosen = args.day or _day(env.get(ENV_DAY) or "")
    except argparse.ArgumentTypeError as exc:
        log(f"파일 합치기 실패: {ENV_DAY} - {exc}")
        return 1
    day = chosen or (utc_naive(now()) - timedelta(days=1)).date()
    try:
        run(day, store=open_store(root), now=now, log=log)
    except CompactError as exc:
        log(f"파일 합치기 {day:%Y-%m-%d} 실패: {exc}")
        return 1
    except Exception as exc:   # S3 오류 문장에는 버킷 이름이 들어 있을 수 있어서 종류만 남긴다
        log(f"파일 합치기 {day:%Y-%m-%d} 실패: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
