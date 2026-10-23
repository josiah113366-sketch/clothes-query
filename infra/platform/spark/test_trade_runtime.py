import copy
import unittest
import yaml

from prepare_trade_runtime import prepare, airflow_overlay

IMAGE = '827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/silver-gold-a@sha256:' + 'a' * 64


class TradeRuntimeTests(unittest.TestCase):
    def test_no_digest_does_not_create_jobs_or_airflow_config(self):
        objects, config = prepare()
        self.assertNotIn('image', config)
        self.assertFalse(any(o['kind'] in {'Pod', 'Job', 'CronJob', 'NodePool', 'ResourceQuota', 'ClusterRole'} for o in objects))
        self.assertTrue(all(o['metadata'].get('namespace') != 'airflow' for o in objects))

    def test_templates_mount_the_matching_configmap_and_use_three_accounts(self):
        objects, config = prepare(IMAGE)
        cm = next(o for o in objects if o['kind'] == 'ConfigMap' and o['metadata']['namespace'] == 'pipelines')
        for role in ['driver', 'executor']:
            template = yaml.safe_load(cm['data'][role + '-pod-template.yaml'])
            self.assertEqual(template['spec']['serviceAccountName'], config[role + '_service_account'])
            self.assertEqual(template['spec']['tolerations'][0]['value'], 'spark')
        driver = yaml.safe_load(cm['data']['driver-pod-template.yaml'])
        self.assertEqual(driver['spec']['volumes'][0]['configMap']['name'], cm['metadata']['name'])
        self.assertEqual(len([o for o in objects if o['kind'] == 'ServiceAccount']), 3)

    def test_wrong_repository_or_tag_is_rejected(self):
        for image in [IMAGE.replace('silver-gold-a', 'investigation-agent'), IMAGE.replace('ap-northeast-1', 'ap-northeast-2'), IMAGE.split('@')[0] + ':latest']:
            with self.subTest(image=image), self.assertRaises(ValueError):
                prepare(image)

    def test_overlay_preserves_existing_env_and_dag_bundle(self):
        base = {'extraEnv': yaml.safe_dump([{'name': 'AIRFLOW_AGENT_CONFIG', 'valueFrom': {'configMapKeyRef': {'name': 'existing-agent', 'key': 'config'}}}]),
                'dagProcessor': {'dagBundleConfigList': [{'name': 'dags-folder', 'kwargs': {'subdir': 'infra/platform/airflow/dags', 'tracking_ref': 'main'}}]}}
        before = copy.deepcopy(base)
        overlay = airflow_overlay(base, IMAGE)
        self.assertEqual(base, before)
        env = yaml.safe_load(overlay['extraEnv'])
        self.assertEqual(env[0], yaml.safe_load(base['extraEnv'])[0])
        self.assertEqual(env[-1]['name'], 'AIRFLOW_PIPELINE_RUNTIME')
        self.assertNotIn('dagProcessor', overlay)
        with self.assertRaises(ValueError):
            airflow_overlay({**base, 'extraEnv': overlay['extraEnv']}, IMAGE)


if __name__ == '__main__':
    unittest.main()
