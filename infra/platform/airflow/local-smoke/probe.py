"""Runs inside the isolated API container; emits no credentials."""
from datetime import datetime, timezone
import json
import os
import time
import urllib.error
import urllib.request

BASE = 'http://api:8080'
PASSWORDS = json.loads(open('/opt/airflow/smoke-passwords.json').read())


def request(method, path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def until(label, function, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = function()
        if value:
            print('PASS: ' + label, flush=True)
            return value
        time.sleep(5)
    raise RuntimeError('Timeout: ' + label)


def main():
    tokens = {}
    for user in ('operator', 'observer'):
        status, body = request('POST', '/auth/token', {'username': user, 'password': PASSWORDS[user]})
        assert status in (200, 201), ('authentication', user, status)
        tokens[user] = body['access_token']
    token = tokens['operator']
    assert request('GET', '/api/v2/dags')[0] == 401
    assert request('POST', '/auth/token', {'username': 'operator', 'password': 'invalid'})[0] in (400, 401, 403)
    until('both probe DAGs discovered', lambda: all(request('GET', '/api/v2/dags/' + name, token=token)[0] == 200
          for name in ('cq_replay_probe', 'cq_five_minute_probe')))
    schedule_enabled_at = datetime.now(timezone.utc)
    for name in ('cq_replay_probe', 'cq_five_minute_probe'):
        assert request('PATCH', '/api/v2/dags/' + name, {'is_paused': False}, token)[0] == 200
    run_path = '/api/v2/dags/cq_replay_probe/dagRuns'
    payload = {'dag_run_id': 'approval-probe-1', 'logical_date': None, 'conf': {'synthetic': True}}
    assert request('POST', run_path, payload, tokens['observer'])[0] == 403
    print('PASS: authentication and viewer trigger denial', flush=True)
    first_started = time.monotonic()
    assert request('POST', run_path, payload, token)[0] in (200, 201)
    assert request('POST', run_path, payload, token)[0] == 409
    payload['dag_run_id'] = 'approval-probe-2'
    assert request('POST', run_path, payload, token)[0] in (200, 201)

    def replays_finished():
        status, body = request('GET', run_path, token=token)
        assert status == 200
        runs = body['dag_runs']
        assert sum(run['state'] == 'running' for run in runs) <= 1
        assert not any(run['state'] == 'failed' for run in runs), 'Replay DAG failed'
        return runs if len(runs) == 2 and all(run['state'] == 'success' for run in runs) else None

    runs = until('two API replays complete without overlap', replays_finished)
    runs.sort(key=lambda run: run['start_date'])
    assert datetime.fromisoformat(runs[0]['end_date']) <= datetime.fromisoformat(runs[1]['start_date'])
    print('PASS: duplicate approval run ID rejected (409)', flush=True)
    print('Replay pair elapsed seconds: ' + str(round(time.monotonic() - first_started, 1)), flush=True)

    def scheduled_finished():
        status, body = request('GET', '/api/v2/dags/cq_five_minute_probe/dagRuns', token=token)
        assert status == 200
        scheduled = [run for run in body['dag_runs'] if run['run_type'] == 'scheduled']
        assert not any(run['state'] == 'failed' for run in scheduled), 'Scheduled DAG failed'
        successes = sorted((run for run in scheduled if run['state'] == 'success'
                            and datetime.fromisoformat(run['run_after']) >= schedule_enabled_at),
                           key=lambda run: run['logical_date'])
        if len(successes) < 2:
            return None
        spacing = (datetime.fromisoformat(successes[1]['logical_date']) - datetime.fromisoformat(successes[0]['logical_date'])).total_seconds()
        assert spacing == 300, spacing
        return successes[:2]

    print('Waiting for two real cron-scheduled runs (up to 11 minutes)...', flush=True)
    scheduled = until('two real five-minute scheduled runs succeeded', scheduled_finished, timeout=660)
    result = {'api_authentication': True, 'viewer_trigger_denied': True, 'duplicate_run_rejected': True,
              'schedule_enabled_at': schedule_enabled_at.isoformat(),
              'replay_runs': runs, 'scheduled_runs': scheduled, 'athena_or_s3_tested': False}
    with open('/opt/airflow/logs/smoke/result.json', 'w') as output:
        json.dump(result, output)


if __name__ == '__main__':
    main()
