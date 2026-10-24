import copy
from pathlib import Path
import unittest

import yaml

from prepare_trade_access import access_plan, merged_bindings, prefix


class TradeAccessTests(unittest.TestCase):
    def setUp(self):
        self.contract = yaml.safe_load((Path(__file__).parent / 'handoff/silver-gold-a.example.yaml').read_text(encoding='utf-8'))
        self.existing = {'expected_account_id': '123456789012', 'state_bucket': 'example-state', 'bindings': {
            'existing-sink': {'namespace': 'kafka', 'service_account': 'existing-sink', 's3_access': {'bronze/': ['s3:PutObject']}}
        }}

    def complete_identity(self):
        self.contract['pending'].update(namespace='example-pipelines', service_account_prefix='example-trade', config_request_prefix_uri='s3://clothes-query-datalake/run-requests/example-trade/')

    def test_supplied_contract_is_scoped_and_still_not_deployable(self):
        plan = access_plan(self.contract)
        self.assertEqual(plan['read_prefixes'], ['bronze_v2/orders/', 'bronze_v2/order-items/', 'bronze_v2/payments/'])
        self.assertEqual(plan['read_write_prefixes'], ['silver/runtime/trade/', 'gold_a/runtime/trade/'])
        self.assertEqual(set(plan['missing_binding_inputs']), {'namespace', 'service_account_prefix', 'config_request_prefix_uri'})
        self.assertFalse(plan['delete_permissions'])
        self.assertFalse(plan['applied'])
        with self.assertRaisesRegex(ValueError, 'Missing binding inputs'):
            merged_bindings(self.contract, self.existing)

    def test_merge_preserves_existing_inputs_and_limits_new_role_actions(self):
        self.complete_identity()
        snapshot = copy.deepcopy(self.existing)
        merged = merged_bindings(self.contract, self.existing)
        self.assertEqual(self.existing, snapshot)
        self.assertEqual(merged['bindings']['existing-sink'], snapshot['bindings']['existing-sink'])
        self.assertEqual(merged['state_bucket'], snapshot['state_bucket'])
        self.assertEqual(len(merged['bindings']), 3)
        self.assertNotIn('example-trade-submitter', merged['bindings'])
        for role in ['driver', 'executor']:
            access = merged['bindings']['example-trade-' + role]['s3_access']
            self.assertEqual(access['bronze_v2/orders/'], ['s3:GetObject'])
            self.assertEqual(access['silver/runtime/trade/'], ['s3:GetObject', 's3:PutObject'])
            self.assertEqual(access['gold_a/runtime/trade/'], ['s3:GetObject', 's3:PutObject'])
            self.assertEqual(access['run-requests/example-trade/'], ['s3:GetObject'])
            self.assertEqual(set(a for actions in access.values() for a in actions), {'s3:GetObject', 's3:PutObject'})
            self.assertNotIn('ground_truth/', access)

    def test_reject_existing_binding_and_identity_collisions(self):
        self.complete_identity()
        self.existing['bindings']['example-trade-driver'] = {'namespace': 'other', 'service_account': 'old', 's3_access': {'other/': ['s3:GetObject']}}
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            merged_bindings(self.contract, self.existing)
        del self.existing['bindings']['example-trade-driver']
        self.existing['bindings']['other-key'] = {'namespace': 'example-pipelines', 'service_account': 'example-trade-driver', 's3_access': {'other/': ['s3:GetObject']}}
        with self.assertRaisesRegex(ValueError, 'already associated'):
            merged_bindings(self.contract, self.existing)

    def test_reject_cross_bucket_wildcard_root_and_protected_prefixes(self):
        for uri in ['s3://other-bucket/requests/', 's3://clothes-query-datalake/', 's3://clothes-query-datalake/requests/*/', 's3://clothes-query-datalake/ground_truth/requests/', 's3://clothes-query-datalake/gold_b/', 's3://clothes-query-datalake/a/../b/', 's3://clothes-query-datalake/a/?secret=value']:
            with self.assertRaises(ValueError):
                prefix(uri, 'clothes-query-datalake')

    def test_reject_accidentally_broadened_input_and_config(self):
        self.contract['pending']['inputs']['orders']['uri'] = 's3://clothes-query-datalake/bronze_v2/'
        with self.assertRaisesRegex(ValueError, 'three supplied'):
            access_plan(self.contract)
        self.setUp()
        self.complete_identity()
        self.contract['pending']['config_request_prefix_uri'] = 's3://clothes-query-datalake/silver/'
        with self.assertRaisesRegex(ValueError, 'cannot widen'):
            merged_bindings(self.contract, self.existing)

    def test_reject_unknown_stack_keys_and_too_long_identity_prefix(self):
        self.complete_identity()
        self.existing['password'] = 'example-not-a-real-password'
        with self.assertRaisesRegex(ValueError, 'Unexpected existing variable'):
            merged_bindings(self.contract, self.existing)
        del self.existing['password']
        self.contract['pending']['service_account_prefix'] = 'x'*24
        with self.assertRaisesRegex(ValueError, '23 characters'):
            merged_bindings(self.contract, self.existing)
