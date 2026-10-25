"""Prepare shared namespace RBAC/templates and optional Airflow config; never deploy."""
import argparse
import json
from pathlib import Path
import re

import yaml

from runtime import resources

NAMESPACE = 'pipelines'
PREFIX = 'silver-gold-a'
CONFIGMAP = PREFIX + '-runtime'
ENV_NAME = 'AIRFLOW_PIPELINE_RUNTIME'
IMAGE = re.compile(r'827913617635\.dkr\.ecr\.ap-northeast-1\.amazonaws\.com/clothes-query-dev/silver-gold-a@sha256:[0-9a-f]{64}')
FUNNEL_ATHENA_WORKGROUP = 'clothes-query-dev-athena-review-score'
FUNNEL_ATHENA_OUTPUT = 's3://clothes-query-datalake/athena-results/review-score/'


def prepare(image=None, trade_publication=False, *, funnel_athena_workgroup=None, funnel_athena_output=None):
    # ResourceQuota applies to the entire namespace. Gold B may share pipelines,
    # so do not impose the legacy four-Pod quota on unrelated shared workloads.
    objects = [obj for obj in resources('dedicated', namespace=NAMESPACE, name_prefix=PREFIX)
               if obj['kind'] != 'ResourceQuota']
    config = {
        'namespace': NAMESPACE,
        'submitter_service_account': PREFIX + '-submitter',
        'driver_service_account': PREFIX + '-driver',
        'executor_service_account': PREFIX + '-executor',
        'runtime_configmap': CONFIGMAP,
        'node_selector': {'karpenter.sh/nodepool': 'clothes-query-dev-compute-spark'},
        'spark_conf': {},
    }
    if trade_publication:
        if image is None:
            raise ValueError('Trade publication requires the verified business image digest')
        config.update(silver_database='silver', gold_database='gold_a', reprocess={
            'output_root': 's3://clothes-query-datalake',
            'inputs': {
                'orders': ['s3://clothes-query-datalake/bronze_v2/orders/'],
                'order_items': ['s3://clothes-query-datalake/bronze_v2/order-items/'],
                'payments': ['s3://clothes-query-datalake/bronze_v2/payments/'],
                'designs': ['s3://hm-ecommerce-data/seed_v2/product_design/product_design.parquet'],
                'variants': ['s3://hm-ecommerce-data/seed_v2/product_variant/product_variant.parquet'],
            },
        })
    if trade_publication and funnel_athena_workgroup is None and funnel_athena_output is None:
        funnel_athena_workgroup = FUNNEL_ATHENA_WORKGROUP
        funnel_athena_output = FUNNEL_ATHENA_OUTPUT
    if funnel_athena_workgroup is not None or funnel_athena_output is not None:
        if image is None or not funnel_athena_workgroup or not funnel_athena_output:
            raise ValueError('Funnel Athena settings require an image and both workgroup and output')
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', funnel_athena_workgroup):
            raise ValueError('Invalid Athena workgroup name')
        if not re.fullmatch(r's3://clothes-query-datalake/athena-results/[A-Za-z0-9/_-]+/', funnel_athena_output):
            raise ValueError('Funnel Athena output must be a dedicated datalake Athena results prefix')
        config.update(funnel_athena_workgroup=funnel_athena_workgroup,
                      funnel_athena_output=funnel_athena_output)
    if image is not None:
        if not IMAGE.fullmatch(image):
            raise ValueError('Use the confirmed Tokyo business repository with immutable sha256 digest')
        config['image'] = image
        objects.append({'apiVersion': 'v1', 'kind': 'ConfigMap',
                        'metadata': {'name': 'airflow-silver-gold-a-runtime', 'namespace': 'airflow'},
                        'data': {'config': json.dumps(config, sort_keys=True)}})
    return objects, config


def airflow_overlay(base, image):
    if not isinstance(base, dict):
        raise ValueError('Supply the actual existing Helm values mapping')
    objects, config = prepare(image)
    env = yaml.safe_load(base.get('extraEnv') or '[]')
    if not isinstance(env, list) or any(not isinstance(e, dict) or not e.get('name') for e in env):
        raise ValueError('Expected extraEnv YAML list')
    if any(e['name'] == ENV_NAME for e in env):
        raise ValueError('Existing pipeline runtime config must be reviewed before replacement')
    bundles = base.get('dagProcessor', {}).get('dagBundleConfigList', [])
    if not any(b.get('kwargs', {}).get('subdir') == 'infra/platform/airflow/dags'
               and b.get('kwargs', {}).get('tracking_ref') == 'main' for b in bundles):
        raise ValueError('Keep the existing main infrastructure DAG bundle')
    # Preserve all existing Secret/agent/probe references; add one reference only.
    return {'extraEnv': yaml.safe_dump(env + [{
        'name': ENV_NAME, 'valueFrom': {'configMapKeyRef': {
            'name': 'airflow-silver-gold-a-runtime', 'key': 'config'}}}], sort_keys=False),
        'config': {'core': {'dags_are_paused_at_creation': 'True'}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image')
    parser.add_argument('--trade-publication', action='store_true')
    parser.add_argument('--funnel-athena-workgroup')
    parser.add_argument('--funnel-athena-output')
    parser.add_argument('--existing-helm-values', type=Path)
    parser.add_argument('--helm-overlay', type=Path)
    args = parser.parse_args()
    objects, config = prepare(args.image, args.trade_publication,
                              funnel_athena_workgroup=args.funnel_athena_workgroup,
                              funnel_athena_output=args.funnel_athena_output)
    if args.helm_overlay:
        if not args.image or not args.existing_helm_values:
            parser.error('Helm overlay requires verified image digest and actual existing values')
        base = yaml.safe_load(args.existing_helm_values.read_text(encoding='utf-8-sig'))
        overlay = airflow_overlay(base, args.image)
        args.helm_overlay.parent.mkdir(parents=True, exist_ok=True)
        args.helm_overlay.write_text(yaml.safe_dump(overlay, sort_keys=False), encoding='utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump_all(objects, sort_keys=False), encoding='utf-8')
    print(json.dumps({'prepared_objects': len(objects), 'namespace': NAMESPACE,
                      'image_config_included': 'image' in config, 'jobs': 0,
                      'node_pools': 0, 'shared_namespace_quota_created': False, 'applied': False}))


if __name__ == '__main__':
    main()
