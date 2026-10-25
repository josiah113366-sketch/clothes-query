"""Airflow(업무 Pod) 실행 역할이 리뷰 점수화 흐름에 필요한 권한을 갖고 있는지 확인한다 (읽기 전용).

무엇을 하나
  IAM 의 policy simulator(simulate-principal-policy)로 "이 역할이 이 동작을 이 리소스에 할 수 있는가"를 계산해 표로 보여 준다.
  실제로 S3 를 읽거나 Athena 쿼리를 돌리거나 Job 을 만들지 않는다. AWS 를 바꾸는 API 는 하나도 부르지 않는다
  (iam:Simulate*, iam:Get*, iam:List*, ssm:GetParameter, athena:GetWorkGroup, s3:GetBucketEncryption, lakeformation:GetDataLakeSettings 만 사용).

어떤 역할을 보나
  `--role` 로 역할 이름을 준다(여러 번 가능). 안 주면 이름에 'airflow' 또는 'silver-gold-a-driver' 가 들어간 역할을 찾아 본다.
  (EKS 위 Airflow 의 업무 Pod 는 Pod Identity 로 별도 역할을 쓴다. 어느 역할인지는 인프라 담당(재영)에게 확인한다.)

버킷·워크그룹·DB·테이블·Job 역할 이름은 코드에 적지 않고 SSM 설정(sagemaker-review-score, athena-review-score)에서 읽는다.

확인 항목(역할마다)
  S3     silver/runtime/reviews/ 읽기(current.json, 실행별 Parquet) + 목록, staging 입력·결과 쓰기, Athena 결과 위치 쓰기
  Athena 워크그룹에 StartQueryExecution / GetQueryExecution / GetQueryResults
  Glue   silver_reviews_runs, review_score_log, 점수 테이블, staging 테이블, 최신 뷰에 GetTable·GetPartitions
  SageMaker  CreateProcessingJob / DescribeProcessingJob, Job 역할에 iam:PassRole
  KMS    버킷이 SSE-KMS 일 때만 Decrypt·GenerateDataKey
  Lake Formation  데이터 레이크 설정(기본 권한이 IAM_ALLOWED_PRINCIPALS 인지)을 보여 준다(참고용, 종료 코드에는 영향 없음)

종료 코드: 0 = 모두 허용, 1 = 하나라도 막힘(또는 확인 불가), 2 = 설정을 읽지 못함 또는 역할을 찾을 수 없음
실행: python deploy/check_airflow_access.py [--role <역할 이름>] ... [--region ap-northeast-1]
"""
import argparse
import json
import sys

SSM_SAGEMAKER = '/clothes-query/dev/sagemaker-review-score/config'
SSM_ATHENA = '/clothes-query/dev/athena-review-score/config'
DEFAULT_ROLE_HINTS = ('airflow', 'silver-gold-a-driver')   # 역할 이름에 들어 있으면 후보로 본다
SAMPLE_RUN = 'check-access-sample-run'                     # 가상의 run_id (실제 객체가 없어도 시뮬레이션은 가능)


def arn_parts(partition, account, region):
    """리소스 ARN 을 만드는 작은 도우미를 돌려준다."""
    def athena_wg(name): return f'arn:{partition}:athena:{region}:{account}:workgroup/{name}'
    def glue(path): return f'arn:{partition}:glue:{region}:{account}:{path}'
    def sm_job(name): return f'arn:{partition}:sagemaker:{region}:{account}:processing-job/{name}'
    return athena_wg, glue, sm_job


def s3_location(uri):
    """s3://버킷/키 → (버킷, 키)"""
    b, _, k = uri[5:].partition('/')
    return b, k


def build_checks(sm, at, bucket, account, region, partition='aws', kms_key_arn=None):
    """(그룹, 설명, 동작, 리소스 ARN 목록, 컨텍스트) 목록을 만든다. 컨텍스트는 s3:prefix 같은 조건 키 값."""
    wg_arn, glue_arn, job_arn = arn_parts(partition, account, region)
    b_arn = f'arn:{partition}:s3:::{bucket}'
    o = lambda key: f'{b_arn}/{key}'
    root = at['silver_reviews_root'].split('/', 3)[3] if at.get('silver_reviews_root') else 'silver/runtime/reviews/'
    root = root.rstrip('/') + '/'
    results_bucket, results_key = s3_location(at['results_location'])
    workgroup = at['workgroup']
    db = at['database']
    checks = []

    def add(group, desc, action, resources, ctx=None):
        checks.append((group, desc, action, resources, ctx or {}))

    # --- S3 ---
    add('S3', 'Silver current.json 읽기', 's3:GetObject', [o(root + 'current.json')])
    add('S3', 'Silver 실행 Parquet 읽기', 's3:GetObject', [o(f'{root}runs/{SAMPLE_RUN}/silver_reviews/part-0.parquet')])
    add('S3', 'Silver 경로 목록 조회', 's3:ListBucket', [b_arn], {'s3:prefix': [f'{root}runs/{SAMPLE_RUN}/silver_reviews/']})
    add('S3', '미점수 입력 쓰기(staging)', 's3:PutObject', [o(sm['unscored_prefix'].strip('/') + '/year=2026/month=10/day=25/unscored_x.jsonl')])
    add('S3', '미점수 입력 읽기(staging)', 's3:GetObject', [o(sm['unscored_prefix'].strip('/') + '/year=2026/month=10/day=25/unscored_x.jsonl')])
    if results_bucket == bucket:
        add('S3', 'Athena 결과 위치 쓰기', 's3:PutObject', [o(results_key.rstrip('/') + '/x.csv')])
        add('S3', 'Athena 결과 위치 읽기', 's3:GetObject', [o(results_key.rstrip('/') + '/x.csv')])
        add('S3', 'Athena 결과 위치 목록', 's3:ListBucket', [b_arn], {'s3:prefix': [results_key.rstrip('/') + '/']})
    # staging 결과(Job 이 쓴 Parquet)를 Athena 가 읽는다
    for name, loc in (('점수 staging', at.get('staging_location')), ('점수 로그 staging', at.get('staging_log_location'))):
        if loc:
            b, k = s3_location(loc)
            add('S3', f'{name} 읽기(MERGE 입력)', 's3:GetObject', [f'arn:{partition}:s3:::{b}/{k.rstrip("/")}/x.parquet'])
    # --- Athena ---
    for act in ('athena:StartQueryExecution', 'athena:GetQueryExecution', 'athena:GetQueryResults'):
        add('Athena', f'워크그룹 {act.split(":")[1]}', act, [wg_arn(workgroup)])
    # --- Glue (Athena 가 카탈로그를 읽을 때 호출자 권한으로 확인한다) ---
    tables = [('silver_reviews_runs', at.get('silver_reviews_runs_table')), ('review_score_log', at.get('log_table')),
              ('점수 테이블', at.get('table')), ('점수 staging', at.get('staging_table')),
              ('점수 로그 staging', at.get('staging_log_table')), ('최신 뷰', at.get('latest_view'))]
    add('Glue', '카탈로그·DB 조회', 'glue:GetDatabase', [glue_arn('catalog'), glue_arn(f'database/{db}')])
    for label, t in tables:
        if t:
            add('Glue', f'{label}({t}) GetTable', 'glue:GetTable', [glue_arn('catalog'), glue_arn(f'database/{db}'), glue_arn(f'table/{db}/{t}')])
    for label, t in tables[:1] + tables[3:5]:   # 파티션이 있는 외부 테이블
        if t:
            add('Glue', f'{label}({t}) GetPartitions', 'glue:GetPartitions', [glue_arn('catalog'), glue_arn(f'database/{db}'), glue_arn(f'table/{db}/{t}')])
    # --- SageMaker ---
    jp = sm.get('job_name_prefix', 'review-score')
    add('SageMaker', 'Processing Job 만들기', 'sagemaker:CreateProcessingJob', [job_arn(jp + '-x')])
    add('SageMaker', 'Processing Job 상태 조회', 'sagemaker:DescribeProcessingJob', [job_arn(jp + '-x')])
    if sm.get('role_arn'):
        add('SageMaker', 'Job 실행 역할 PassRole', 'iam:PassRole', [sm['role_arn']], {'iam:PassedToService': ['sagemaker.amazonaws.com']})
    # --- KMS (SSE-KMS 일 때만) ---
    if kms_key_arn:
        for act in ('kms:Decrypt', 'kms:GenerateDataKey'):
            add('KMS', f'버킷 암호화 키 {act.split(":")[1]}', act, [kms_key_arn])
    return checks


def find_roles(iam, hints):
    """이름에 힌트 문자열이 들어간 역할 이름을 찾는다."""
    found = []
    for page in iam.get_paginator('list_roles').paginate():
        for r in page['Roles']:
            if any(h in r['RoleName'] for h in hints):
                found.append(r['RoleName'])
    return sorted(found)


def simulate(iam, role_arn, action, resources, ctx):
    """한 동작을 시뮬레이션해 'allowed' / 'implicitDeny' / 'explicitDeny' 중 하나를 돌려준다."""
    ctxs = [{'ContextKeyName': k, 'ContextKeyValues': v, 'ContextKeyType': 'string'} for k, v in ctx.items()]
    kw = dict(PolicySourceArn=role_arn, ActionNames=[action], ResourceArns=resources)
    if ctxs:
        kw['ContextEntries'] = ctxs
    decisions = []
    for page in iam.get_paginator('simulate_principal_policy').paginate(**kw):
        decisions += [r['EvalDecision'] for r in page['EvaluationResults']]
    # 리소스가 여러 개인 항목(Glue 등)은 전부 허용돼야 통과로 본다
    return 'allowed' if decisions and all(d == 'allowed' for d in decisions) else (
        'explicitDeny' if 'explicitDeny' in decisions else 'implicitDeny')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # 터미널 코드페이지와 관계없이 한글이 깨지지 않게
    import boto3
    ap = argparse.ArgumentParser(description='Airflow 실행 역할의 리뷰 점수화 권한 확인(읽기 전용)')
    ap.add_argument('--role', action='append', help='확인할 IAM 역할 이름(정책 이름이 아님. 여러 번 가능). 없으면 이름으로 찾는다')
    ap.add_argument('--region', default='ap-northeast-1')
    ap.add_argument('--ssm-sagemaker', default=SSM_SAGEMAKER)
    ap.add_argument('--ssm-athena', default=SSM_ATHENA)
    a = ap.parse_args()
    try:
        ssm = boto3.client('ssm', region_name=a.region)
        sm = json.loads(ssm.get_parameter(Name=a.ssm_sagemaker)['Parameter']['Value'])
        at = json.loads(ssm.get_parameter(Name=a.ssm_athena)['Parameter']['Value'])
        for k in ('silver_reviews_root', 'silver_reviews_runs_table'):
            if not at.get(k):
                print(f'주의: athena 설정(SSM)에 {k} 가 없습니다. athena-review-score 스택 apply 전이므로 기본값으로 점검합니다.')
        at.setdefault('silver_reviews_runs_table', 'silver_reviews_runs')
        at.setdefault('silver_reviews_root', f"s3://{sm['bucket']}/silver/runtime/reviews/")
    except Exception as e:
        print('SSM 설정을 읽지 못했습니다:', e)
        return 2
    account = boto3.client('sts', region_name=a.region).get_caller_identity()['Account']
    iam = boto3.client('iam', region_name=a.region)
    bucket = sm['bucket']

    # 버킷 암호화 확인: SSE-KMS 일 때만 KMS 권한을 본다
    kms_key = None
    try:
        enc = boto3.client('s3', region_name=a.region).get_bucket_encryption(Bucket=bucket)['ServerSideEncryptionConfiguration']['Rules'][0]['ApplyServerSideEncryptionByDefault']
        print(f"버킷 암호화: {enc['SSEAlgorithm']}" + (' (KMS 권한도 확인)' if enc['SSEAlgorithm'].startswith('aws:kms') else ' (KMS 권한 불필요)'))
        if enc['SSEAlgorithm'].startswith('aws:kms') and enc.get('KMSMasterKeyID'):
            kms_key = enc['KMSMasterKeyID']
    except Exception as e:
        print('버킷 암호화를 확인하지 못했습니다(KMS 항목 건너뜀):', type(e).__name__)

    roles = a.role or find_roles(iam, DEFAULT_ROLE_HINTS)
    if not roles:
        print('확인할 역할이 없습니다. --role 로 Airflow 업무 Pod 의 IAM 역할 이름을 주세요.')
        return 2
    print('확인할 역할:', ', '.join(roles))

    checks = build_checks(sm, at, bucket, account, a.region, kms_key_arn=kms_key)
    try:   # athena 워크그룹의 결과 위치가 SSM 설정과 같은지도 본다(읽기 전용)
        wg = boto3.client('athena', region_name=a.region).get_work_group(WorkGroup=at['workgroup'])['WorkGroup']
        loc = wg['Configuration']['ResultConfiguration'].get('OutputLocation')
        print(f"워크그룹 결과 위치: {'SSM 설정과 같음' if loc and loc.rstrip('/') == at['results_location'].rstrip('/') else '다름 → ' + str(loc)}")
    except Exception as e:
        print('워크그룹을 읽지 못했습니다:', type(e).__name__)

    bad = 0
    for role in roles:
        try:
            arn = iam.get_role(RoleName=role)['Role']['Arn']
        except iam.exceptions.NoSuchEntityException:
            # 정책 이름을 --role 에 넣는 실수가 잦아, 같은 이름의 고객 관리형 정책이 있으면 알려 준다
            is_policy = any(p['PolicyName'] == role for page in iam.get_paginator('list_policies').paginate(Scope='Local') for p in page['Policies'])
            print(f'\n역할을 찾을 수 없습니다: {role}')
            if is_policy:
                print('이건 정책 이름입니다. 정책을 붙일 역할 이름(예: clothes-query-dev-silver-gold-a-driver)을 넣으세요.')
            return 2
        print(f'\n== 역할 {role}')
        print(f"{'그룹':<10}{'확인 항목':<52}{'동작':<36}결과")
        for group, desc, action, res, ctx in checks:
            try:
                d = simulate(iam, arn, action, res, ctx)
            except Exception as e:
                d = f'확인 불가({type(e).__name__})'
            ok = d == 'allowed'
            bad += 0 if ok else 1
            print(f"{group:<10}{desc:<52}{action:<36}{'있음' if ok else '없음 [' + d + ']'}")
    # Lake Formation: 권한 모드 확인(참고용)
    try:
        lf = boto3.client('lakeformation', region_name=a.region).get_data_lake_settings()['DataLakeSettings']
        defaults = [p['Principal']['DataLakePrincipalIdentifier'] for p in lf.get('CreateDatabaseDefaultPermissions', [])]
        print('\nLake Formation: 새 DB 기본 권한 주체 =', defaults or '(없음)',
              '→ IAM 권한만으로 동작(IAM_ALLOWED_PRINCIPALS)' if 'IAM_ALLOWED_PRINCIPALS' in defaults else '→ Lake Formation 권한 부여가 따로 필요할 수 있음')
    except Exception as e:
        print('\nLake Formation 설정을 읽지 못했습니다:', type(e).__name__)
    print(f"\n{'모든 항목 허용' if not bad else f'막힌 항목 {bad}건'} (시뮬레이션 기준, 실제 호출은 하지 않음)")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
