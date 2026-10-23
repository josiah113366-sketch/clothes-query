"""Prepare a local access plan or merged Terraform inputs. Never call AWS/kubectl."""
import argparse
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from runtime import validate_names


def prefix(uri, bucket):
    if not isinstance(uri, str):
        raise ValueError('An explicit S3 prefix URI is required')
    parsed = urlsplit(uri)
    key = parsed.path.lstrip('/')
    if (parsed.scheme != 's3' or parsed.netloc != bucket or parsed.query or parsed.fragment
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_.=-]*/', key)
            or '//' in parsed.path or any(p in {'.', '..'} for p in key.split('/'))):
        raise ValueError('Use a literal, non-root prefix in the approved bucket, ending in /')
    if key.startswith(('ground_truth/', 'gold_b/', 'agent/')):
        raise ValueError('Trade preparation cannot grant access to protected/unrelated prefixes')
    return key


def access_plan(contract):
    pending = contract['pending']
    bucket = contract['supplied_contract']['bucket']
    reads = [prefix(pending['inputs'][key]['uri'], bucket) for key in ['orders', 'order_items', 'payments']]
    writes = [prefix(pending['outputs'][key], bucket) for key in ['silver_uri', 'gold_a_uri']]
    if any(not path.startswith(expected) for path, expected in zip(reads, ['bronze/orders/', 'bronze/order-items/', 'bronze/payments/'])):
        raise ValueError('Inputs must remain within the three supplied Bronze roots')
    if not writes[0].startswith('silver/runtime/trade/') or not writes[1].startswith('gold_a/runtime/trade/'):
        raise ValueError('Writes must remain within the supplied trade output roots')
    missing = [key for key in ['namespace', 'service_account_prefix', 'config_request_prefix_uri'] if not pending.get(key)]
    return {'bucket': bucket, 'read_prefixes': reads, 'read_write_prefixes': writes,
            'delete_permissions': False, 'missing_binding_inputs': missing,
            'complete_job_policy': False, 'applied': False,
            'remaining_job_contract': ['S3 committer and temporary cleanup', 'business image/entry/arguments',
                                       'fixed test inputs', 'Glue schemas/publication', 'namespace sharing']}


def merged_bindings(contract, existing):
    plan = access_plan(contract)
    if plan['missing_binding_inputs']:
        raise ValueError('Missing binding inputs: ' + ', '.join(plan['missing_binding_inputs']))
    pending = contract['pending']
    namespace, name_prefix = pending['namespace'], pending['service_account_prefix']
    validate_names(namespace, name_prefix)
    if len(name_prefix) > 23:
        raise ValueError('Use a prefix of at most 23 characters for workload-access binding keys')
    config_prefix = prefix(pending['config_request_prefix_uri'], plan['bucket'])
    if config_prefix.startswith(('bronze/', 'silver/', 'gold_a/')) and not any(
            config_prefix.startswith(p) for p in plan['read_prefixes'] + plan['read_write_prefixes']):
        raise ValueError('Configuration input cannot widen the supplied data prefixes')
    # Keep input files credential-free and preserve all supported existing stack inputs.
    if set(existing) - {'expected_account_id', 'state_bucket', 'state_region', 'aws_region', 'bindings'}:
        raise ValueError('Unexpected existing variable: pass only workload-access stack inputs')
    result = copy.deepcopy(existing)
    bindings = result.setdefault('bindings', {})
    access = {p: ['s3:GetObject'] for p in plan['read_prefixes']}
    for p in plan['read_write_prefixes']:
        access[p] = ['s3:GetObject', 's3:PutObject']
    access.setdefault(config_prefix, ['s3:GetObject'])
    for role in ['driver', 'executor']:
        key = name_prefix + '-' + role
        binding = {'namespace': namespace, 'service_account': key, 's3_access': copy.deepcopy(access)}
        if key in bindings and bindings[key] != binding:
            raise ValueError('Refuse to overwrite an existing binding: ' + key)
        if any(other != key and (value['namespace'], value['service_account']) == (namespace, key)
               for other, value in bindings.items()):
            raise ValueError('Namespace/ServiceAccount is already associated under another binding')
        bindings[key] = binding
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, default=Path(__file__).parent / 'handoff/silver-gold-a.example.yaml')
    parser.add_argument('--plan-output', type=Path)
    parser.add_argument('--existing-vars', type=Path)
    parser.add_argument('--bindings-output', type=Path)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding='utf-8-sig'))
    plan = access_plan(contract)
    if args.bindings_output:
        if not args.existing_vars:
            parser.error('--bindings-output requires --existing-vars; do not replace the existing map')
        existing = json.loads(args.existing_vars.read_text(encoding='utf-8-sig'))
        try:
            merged = merged_bindings(contract, existing)
        except ValueError as error:
            parser.error(str(error))
        if args.bindings_output.resolve() == args.existing_vars.resolve():
            parser.error('Write to a separate review file; do not overwrite existing shared inputs')
        args.bindings_output.parent.mkdir(parents=True, exist_ok=True)
        args.bindings_output.write_text(json.dumps(merged, indent=2)+'\n', encoding='utf-8')
    if args.plan_output:
        args.plan_output.parent.mkdir(parents=True, exist_ok=True)
        args.plan_output.write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(plan))


if __name__ == '__main__':
    main()
