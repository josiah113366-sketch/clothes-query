"""Synthetic infrastructure probes only; no AWS calls or business DAGs."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from airflow.sdk import dag, task


@task
def record_probe(delay_seconds: int):
    time.sleep(delay_seconds)
    output = Path('/opt/airflow/logs/smoke')
    output.mkdir(exist_ok=True)
    path = output / f'probe-{time.time_ns()}.json'
    path.write_text(json.dumps({'synthetic': True, 'completed_at': datetime.now(timezone.utc).isoformat()}))


@dag(dag_id='cq_replay_probe', schedule=None, start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
     catchup=False, max_active_runs=1, max_active_tasks=1,
     dagrun_timeout=timedelta(minutes=3), tags=['local-smoke'])
def replay_probe():
    record_probe(20)


@dag(dag_id='cq_five_minute_probe', schedule='*/5 * * * *',
     start_date=datetime(2026, 1, 1, tzinfo=timezone.utc), catchup=False,
     max_active_runs=1, max_active_tasks=1, dagrun_timeout=timedelta(minutes=3), tags=['local-smoke'])
def five_minute_probe():
    record_probe(2)


replay_probe()
five_minute_probe()
