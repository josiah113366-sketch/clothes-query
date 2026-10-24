import copy
import json
import unittest

from prepare import foundation, pending_ingest
from persistent import render


class PersistentTests(unittest.TestCase):
    def setUp(self):
        self.cm = next(o for o in foundation() if o['kind'] == 'ConfigMap')
        config = pending_ingest('gold_b/_checkpoints/streaming_ingest/')
        config['image'] = '827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/gold-b@sha256:' + 'a' * 64
        self.cm['data']['ingest.config.json'] = json.dumps(config)

    def test_one_recreated_driver_keeps_identity_pool_and_checkpoint(self):
        before = copy.deepcopy(self.cm)
        service, deploy = render(self.cm)
        self.assertEqual(self.cm, before)
        self.assertEqual(deploy['spec']['replicas'], 1)
        self.assertEqual(deploy['spec']['strategy'], {'type': 'Recreate'})
        self.assertEqual(service['spec']['selector'], deploy['spec']['selector']['matchLabels'])
        spec = deploy['spec']['template']['spec']
        self.assertEqual(spec['serviceAccountName'], 'gold-b-ingest-driver')
        self.assertEqual(spec['restartPolicy'], 'Always')
        self.assertNotIn('activeDeadlineSeconds', spec)
        container = spec['containers'][0]
        self.assertIn('client', container['args'])
        self.assertIn('spark.kubernetes.driver.pod.name=$(POD_NAME)', container['args'])
        self.assertEqual(next(e['value'] for e in container['env'] if e['name'] == 'GOLD_B_CHECKPOINT'),
                         's3a://clothes-query-datalake/gold_b/_checkpoints/streaming_ingest/')
        self.assertEqual({v['name'] for v in spec['volumes']}, {'infra', 'kafka-tls'})

    def test_reject_trial_settings_or_changed_checkpoint(self):
        for field in ['trial', 'checkpoint', 'identity', 'deadline']:
            with self.subTest(field=field):
                cm = copy.deepcopy(self.cm)
                if field == 'trial': cm['data']['validate_ingest.py'] = 'test'
                if field == 'checkpoint':
                    config = json.loads(cm['data']['ingest.config.json'])
                    config['env']['GOLD_B_CHECKPOINT'] += 'other/'
                    cm['data']['ingest.config.json'] = json.dumps(config)
                if field in ['identity', 'deadline']:
                    import yaml
                    template = yaml.safe_load(cm['data']['driver-pod-template.yaml'])
                    if field == 'identity': template['spec']['serviceAccountName'] = 'wrong'
                    else: template['spec']['activeDeadlineSeconds'] = 600
                    cm['data']['driver-pod-template.yaml'] = yaml.safe_dump(template)
                with self.assertRaises(ValueError): render(cm)
