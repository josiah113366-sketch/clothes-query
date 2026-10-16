"""Disposable Airflow 3 local runtime test. No host ports, AWS credentials or business DAGs."""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
AIRFLOW_IMAGE = 'apache/airflow@sha256:9df9c8be4096b9cc626bd7cb1f2b8c712eef66c59c615f8c7e6200871ca10bd1'
POSTGRES_IMAGE = 'postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4'


def main():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(('AWS_', 'TF_', 'KUBE'))}
    if env.get('DOCKER_HOST') or env.get('DOCKER_CONTEXT'):
        raise RuntimeError('Use the local Docker context without overrides')

    def docker(*args, timeout=120, check=True):
        result = subprocess.run(['docker', *map(str, args)], env=env, capture_output=True, timeout=timeout)
        result.stdout = result.stdout.decode('utf-8', errors='replace')
        result.stderr = result.stderr.decode('utf-8', errors='replace')
        if check and result.returncode:
            raise RuntimeError(redact(result.stderr[-3000:] or result.stdout[-3000:]))
        return result

    def redact(value):
        for secret in secret_values:
            value = value.replace(secret, '[redacted]')
        return value

    secret_values = []
    context = json.loads(docker('context', 'inspect').stdout)[0]
    if not context['Endpoints']['docker']['Host'].startswith(('npipe://', 'unix://')):
        raise RuntimeError('Remote Docker endpoints are not supported')
    engine = json.loads(docker('info', '--format', '{{json .}}').stdout)
    if engine['OSType'] != 'linux':
        raise RuntimeError('Start Docker Desktop Linux engine first')
    project = 'cq-airflow-' + secrets.token_hex(5)
    print('Local test project: ' + project, flush=True)
    report_path = REPO / '.cache/airflow-local-report.json'
    report_path.parent.mkdir(exist_ok=True)
    # Do not leave a previous successful result masquerading as this execution.
    report = {'project': project, 'status': 'running', 'docker_cpus': engine['NCPU'],
              'docker_memory_bytes': engine['MemTotal'], 'aws_or_kubernetes_tested': False,
              'airflow_image': AIRFLOW_IMAGE, 'samples': []}
    report_path.write_text(json.dumps(report), encoding='utf-8')
    passwords = {name: secrets.token_urlsafe(24) for name in ('operator', 'observer')}
    pg_password, jwt_secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
    fernet = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    secret_values.extend([*passwords.values(), pg_password, jwt_secret, fernet])
    stop = threading.Event()
    sampler = None
    with tempfile.TemporaryDirectory(prefix=project + '-') as temp:
        directory = Path(temp)
        passwords_path = directory / 'passwords.json'
        passwords_path.write_text(json.dumps(passwords), encoding='utf-8')
        common_env = {
            'AIRFLOW__CORE__EXECUTOR': 'LocalExecutor',
            'AIRFLOW__DATABASE__SQL_ALCHEMY_CONN': f'postgresql+psycopg2://airflow:{pg_password}@postgres/airflow',
            'AIRFLOW__CORE__FERNET_KEY': fernet,
            'AIRFLOW__API_AUTH__JWT_SECRET': jwt_secret,
            'AIRFLOW__CORE__EXECUTION_API_SERVER_URL': 'http://api:8080/execution/',
            'AIRFLOW__CORE__LOAD_EXAMPLES': 'false',
            'AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION': 'true',
            'AIRFLOW__CORE__PARALLELISM': '2',
            'AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS': 'operator:admin,observer:viewer',
            'AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE': '/opt/airflow/smoke-passwords.json',
            'AIRFLOW__API__WORKERS': '1',
            'AIRFLOW__DAG_PROCESSOR__PARSING_PROCESSES': '1',
            'AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL': '5',
            'AIRFLOW__DAG_PROCESSOR__MIN_FILE_PROCESS_INTERVAL': '5',
        }
        common = {'image': AIRFLOW_IMAGE, 'platform': 'linux/amd64', 'user': '50000:0',
                  'environment': common_env, 'networks': ['smoke'],
                  'volumes': [f'{ROOT / "dags"}:/opt/airflow/dags:ro',
                              f'{ROOT / "probe.py"}:/opt/airflow/smoke-probe.py:ro',
                              f'{passwords_path}:/opt/airflow/smoke-passwords.json',
                              'airflow-logs:/opt/airflow/logs']}
        services = {
            'postgres': {'image': POSTGRES_IMAGE, 'platform': 'linux/amd64', 'mem_limit': '384m', 'cpus': 0.25,
                         'environment': {'POSTGRES_USER': 'airflow', 'POSTGRES_DB': 'airflow', 'POSTGRES_PASSWORD': pg_password},
                         'networks': ['smoke'], 'volumes': ['postgres-data:/var/lib/postgresql/data'],
                         'healthcheck': {'test': ['CMD', 'pg_isready', '-U', 'airflow'], 'interval': '3s', 'timeout': '3s', 'retries': 30}},
            'init': {**common, 'command': ['db', 'migrate'], 'mem_limit': '1024m', 'cpus': 1.0,
                     'depends_on': {'postgres': {'condition': 'service_healthy'}}},
            'api': {**common, 'command': ['api-server'], 'mem_limit': '768m', 'cpus': 0.5},
            'scheduler': {**common, 'command': ['scheduler'], 'mem_limit': '1536m', 'cpus': 1.0},
            'dag-processor': {**common, 'command': ['dag-processor'], 'mem_limit': '768m', 'cpus': 0.5},
        }
        config = directory / 'compose.json'
        config.write_text(json.dumps({'services': services, 'volumes': {'airflow-logs': {}, 'postgres-data': {}},
                                      'networks': {'smoke': {'internal': True}}}), encoding='utf-8')

        def compose(*args, **kwargs):
            return docker('compose', '--project-name', project, '--file', config, *args, **kwargs)

        def sample():
            while not stop.is_set():
                try:
                    ids = compose('ps', '-q').stdout.split()
                    if ids:
                        rows = docker('stats', '--no-stream', '--format', '{{json .}}', *ids, timeout=20).stdout
                        report['samples'].append({'seconds': round(time.monotonic() - started, 1),
                                                  'containers': [json.loads(line) for line in rows.splitlines() if line]})
                except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
                    pass
                stop.wait(5)

        started = time.monotonic()
        try:
            compose('up', '-d', 'postgres')
            compose('run', '--rm', 'init', timeout=240)
            print('PASS: isolated PostgreSQL metadata DB migrated', flush=True)
            compose('up', '-d', 'api', 'scheduler', 'dag-processor')
            sampler = threading.Thread(target=sample, daemon=True)
            sampler.start()
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                api_id = compose('ps', '-a', '-q', 'api').stdout.strip()
                if api_id and docker('inspect', '--format', '{{.State.Running}}', api_id).stdout.strip() == 'false':
                    raise RuntimeError('Airflow API container exited during boot; see sanitized diagnostics')
                health = compose('exec', '-T', 'api', 'python', '-c',
                                 "import urllib.request; urllib.request.urlopen('http://api:8080/api/v2/monitor/health',timeout=3)", check=False)
                if health.returncode == 0:
                    break
                time.sleep(5)
            else:
                raise RuntimeError('Airflow API did not become healthy')
            report['boot_seconds'] = round(time.monotonic() - started, 1)
            print('PASS: Airflow API ready; boot seconds: ' + str(report['boot_seconds']), flush=True)
            # Child output is sanitized after completion; progress appears in the captured test log.
            probe = compose('exec', '-T', 'api', 'python', '/opt/airflow/smoke-probe.py', timeout=950)
            print(redact(probe.stdout), end='', flush=True)
            report['probe'] = json.loads(compose('exec', '-T', 'api', 'cat', '/opt/airflow/logs/smoke/result.json').stdout)
            ids = compose('ps', '-q').stdout.split()
            report['health'] = []
            for container in json.loads(docker('inspect', *ids).stdout):
                report['health'].append({'service': container['Config']['Labels']['com.docker.compose.service'],
                                        'oom_killed': container['State']['OOMKilled'], 'restarts': container['RestartCount'],
                                        'memory_limit_bytes': container['HostConfig']['Memory'],
                                        'nano_cpus': container['HostConfig']['NanoCpus']})
            assert all(not item['oom_killed'] and item['restarts'] == 0 for item in report['health'])
            report['status'] = 'passed'
            print('PASS: API replay, real five-minute scheduling, concurrency and OOM/restart checks', flush=True)
        except Exception as error:
            report['status'] = 'failed'
            report['error'] = redact(str(error))
            report['diagnostics'] = redact(compose('logs', '--no-color', '--tail', '80', check=False).stdout)
            raise
        finally:
            stop.set()
            if sampler:
                sampler.join(timeout=30)
            report['elapsed_seconds'] = round(time.monotonic() - started, 1)
            cleanup = compose('down', '--volumes', '--remove-orphans', timeout=90, check=False)
            report['cleanup_ok'] = cleanup.returncode == 0
            if not report['cleanup_ok']:
                report['status'] = 'failed'
                report['cleanup_error'] = redact(cleanup.stderr[-2000:])
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('Report: .cache/airflow-local-report.json; cleanup: ' + str(report['cleanup_ok']), flush=True)
            if not report['cleanup_ok']:
                raise RuntimeError('Local test cleanup failed for ' + project)


if __name__ == '__main__':
    main()
