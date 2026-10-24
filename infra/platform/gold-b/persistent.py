"""Render a single persistent Gold B client-mode Driver; never deploy."""
import argparse
import copy
import json
from pathlib import Path
import re

import yaml

NAME = "gold-b-ingest"
NS = "pipelines"
CHECKPOINT = "s3a://clothes-query-datalake/gold_b/_checkpoints/streaming_ingest/"
ENTRY = "local:///opt/gold_b/pipelines/gold_b/jobs/streaming_ingest.py"


def render(runtime):
    if runtime['metadata']['name'] != NAME + '-runtime' or runtime['metadata']['namespace'] != NS:
        raise ValueError('Use the existing confirmed Gold B runtime ConfigMap')
    config = json.loads(runtime['data']['ingest.config.json'])
    if not re.fullmatch(r'827913617635\.dkr\.ecr\.ap-northeast-1\.amazonaws\.com/clothes-query-dev/gold-b@sha256:[a-f0-9]{64}', config['image']):
        raise ValueError('Require the confirmed repository with an immutable digest')
    if config['application'] != ENTRY or config['env']['GOLD_B_CHECKPOINT'] != CHECKPOINT:
        raise ValueError('Do not change the entrypoint or reset the confirmed checkpoint')
    if any(k.startswith('GOLD_B_VALIDATION_') for k in config['env']) or 'validate_ingest.py' in runtime['data']:
        raise ValueError('Remove bounded validation settings before persistent execution')
    properties = runtime['data']['spark.properties']
    if 'GOLD_B_VALIDATION_' in properties:
        raise ValueError('Bounded validation properties are not operational settings')
    spec = copy.deepcopy(yaml.safe_load(runtime['data']['driver-pod-template.yaml'])['spec'])
    if spec.get('serviceAccountName') != NAME + '-driver' or 'activeDeadlineSeconds' in spec:
        raise ValueError('Use the Driver identity without a trial deadline')
    if spec.get('nodeSelector') != {'karpenter.sh/nodepool': 'clothes-query-dev-compute-spark'}:
        raise ValueError('Keep the approved dedicated Spark pool')
    spec.update(restartPolicy='Always', terminationGracePeriodSeconds=120)
    container = spec['containers'][0]
    container.update(name='driver', image=config['image'],
        command=['/opt/spark/bin/spark-submit'], args=[
            '--master', 'k8s://https://kubernetes.default.svc:443', '--deploy-mode', 'client',
            '--name', NAME, '--properties-file', '/opt/spark/infra/spark.properties',
            '--driver-memory', '1g',
            '--conf', 'spark.driver.host=gold-b-ingest-driver.pipelines.svc.cluster.local',
            '--conf', 'spark.driver.bindAddress=0.0.0.0',
            '--conf', 'spark.driver.port=7078', '--conf', 'spark.driver.blockManager.port=7079',
            '--conf', 'spark.kubernetes.driver.pod.name=$(POD_NAME)',
            '--conf', 'spark.kubernetes.authenticate.oauthTokenFile=/var/run/secrets/kubernetes.io/serviceaccount/token',
            '--conf', 'spark.kubernetes.authenticate.caCertFile=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt',
            ENTRY],
        env=[{'name': k, 'value': v} for k, v in sorted(config['env'].items())] + [
            {'name': 'PYTHONPATH', 'value': '/opt/gold_b'},
            {'name': 'SPARK_DRIVER_MEMORY', 'value': '1g'},
            {'name': 'POD_NAME', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.name'}}}],
        resources={'requests': {'cpu': '350m', 'memory': '2Gi'}, 'limits': {'cpu': '1', 'memory': '2Gi'}},
        ports=[{'name': 'driver-rpc', 'containerPort': 7078}, {'name': 'driver-block', 'containerPort': 7079}],
        readinessProbe={'tcpSocket': {'port': 'driver-rpc'}, 'initialDelaySeconds': 15, 'periodSeconds': 10})
    labels = {'app': NAME, 'gold-b-role': 'persistent-driver'}
    deployment = {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': NAME, 'namespace': NS},
        'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'revisionHistoryLimit': 2,
                 'selector': {'matchLabels': labels}, 'template': {'metadata': {'labels': labels}, 'spec': spec}}}
    service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': NAME + '-driver', 'namespace': NS},
        'spec': {'clusterIP': 'None', 'publishNotReadyAddresses': True, 'selector': labels,
                 'ports': [{'name': 'driver-rpc', 'port': 7078}, {'name': 'driver-block', 'port': 7079}]}}
    return [service, deployment]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-json', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(yaml.safe_dump_all(render(json.loads(args.runtime_json.read_text(encoding='utf-8-sig'))), sort_keys=False), encoding='utf-8')
