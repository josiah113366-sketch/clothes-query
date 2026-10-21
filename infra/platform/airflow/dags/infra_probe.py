"""Infrastructure checks only; keep paused outside an explicit smoke run."""

import json
import os
from datetime import UTC, datetime, timedelta

from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.sdk import dag, task
from kubernetes.client import models as k8s

PROBE = json.loads(os.environ["AIRFLOW_INFRA_PROBE_CONFIG"])
CODE = """
import json, os
from urllib.parse import urlparse
import boto3
from botocore.exceptions import ClientError
role = os.environ['PROBE_ROLE']
suffix = 'detection-job' if role == 'detection' else 'investigation-agent'
session = boto3.Session(region_name='ap-northeast-1')
assert '/clothes-query-dev-' + suffix + '/' in session.client('sts').get_caller_identity()['Arn']
config = session.client('athena').get_work_group(WorkGroup='clothes-query-dev-' + role)['WorkGroup']['Configuration']
bucket = urlparse(config['ResultConfiguration']['OutputLocation']).netloc
s3 = session.client('s3')
s3.list_objects_v2(Bucket=bucket, Prefix='gold_b/', MaxKeys=1)
try:
    s3.get_object(Bucket=bucket, Key='ground_truth/_infra-checks/airflow-deny-only.json')
except ClientError as error:
    assert error.response['Error']['Code'] == 'AccessDenied'
else:
    raise AssertionError('Ground truth access unexpectedly allowed')
print(json.dumps({'synthetic': True, 'role': role, 'identity_verified': True, 'ground_truth_denied': True}))
"""


@dag(
    dag_id="infra_airflow_access_probe",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    dagrun_timeout=timedelta(minutes=5),
    tags=["infra-probe"],
)
def access_probe():
    previous = None
    for role, service_account in [
        ("detection", "detection-job"),
        ("investigation", "investigation-agent"),
    ]:
        op = KubernetesPodOperator(
            task_id=role,
            name="airflow-infra-" + role,
            namespace="agent",
            in_cluster=True,
            service_account_name=service_account,
            automount_service_account_token=False,
            image=PROBE["image"],
            cmds=["python", "-c"],
            arguments=[CODE],
            env_vars={"PROBE_ROLE": role, "AWS_EC2_METADATA_DISABLED": "true"},
            node_selector={"kubernetes.io/hostname": PROBE["hostname"]},
            container_resources=k8s.V1ResourceRequirements(
                requests={"cpu": "25m", "memory": "96Mi"},
                limits={"cpu": "200m", "memory": "192Mi"},
            ),
            get_logs=True,
            on_finish_action="delete_pod",
            do_xcom_push=False,
            startup_timeout_seconds=180,
        )
        if previous is not None:
            previous >> op
        previous = op


@task
def record_tick():
    return {"synthetic": True, "completed_at": datetime.now(UTC).isoformat()}


@dag(
    dag_id="infra_airflow_five_minute_probe",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    tags=["infra-probe"],
)
def five_minute_probe():
    record_tick()


access_probe()
five_minute_probe()
