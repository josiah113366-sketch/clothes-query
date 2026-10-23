import unittest
from render import access, runtime

IMAGE = '827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/gold-b-lag-collector@sha256:' + 'a' * 64


class CollectorRuntimeTest(unittest.TestCase):
    def test_sink_group_cannot_commit_or_join(self):
        acls = access()[0]['spec']['authorization']['acls']
        sink = next(a for a in acls if a['resource'].get('name') == 'connect-bronze-s3-sink-v2')
        self.assertEqual(sink['operations'], ['Describe'])
        self.assertFalse(any('Write' in a['operations'] or 'Alter' in a['operations'] for a in acls))

    def test_network_access_combines_namespace_and_collector_label(self):
        for policy in access()[1:]:
            peer = policy['spec']['ingress'][0]['from'][0]
            self.assertEqual(peer['namespaceSelector']['matchLabels']['kubernetes.io/metadata.name'], 'pipelines')
            self.assertEqual(peer['podSelector']['matchLabels']['app'], 'gold-b-lag-collector')
        self.assertFalse(any(o['kind'] in ['Kafka', 'KafkaConnect', 'KafkaNodePool'] for o in access()))

    def test_v2_only_and_small_nonroot_runtime_without_new_node(self):
        sa, cm, dep = runtime(IMAGE)
        self.assertFalse(sa['automountServiceAccountToken'])
        self.assertEqual(cm['data']['GOLD_B_SINK_GROUP'], 'connect-bronze-s3-sink-v2')
        self.assertEqual(dep['spec']['replicas'], 1)
        self.assertEqual(dep['spec']['strategy']['type'], 'Recreate')
        spec = dep['spec']['template']['spec']
        self.assertEqual(spec['nodeSelector'], {'karpenter.sh/nodepool': 'clothes-query-dev-api'})
        self.assertTrue(spec['containers'][0]['securityContext']['readOnlyRootFilesystem'])
        self.assertEqual(spec['volumes'][0]['secret']['defaultMode'], 0o440)

    def test_floating_or_other_images_rejected(self):
        for image in ['python:latest', IMAGE.replace('gold-b-lag-collector', 'detection-job')]:
            with self.assertRaises(ValueError):
                runtime(image)


if __name__ == '__main__':
    unittest.main()
