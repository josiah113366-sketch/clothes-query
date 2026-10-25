"""SageMaker Processing Job으로 후기 점수화를 한 번 실행한다 (팀 계정용). 컨테이너 안에서는 로컬 경로만 쓰고, S3 입출력은 SageMaker가 처리한다.
모델 버전 세트(가중치·실행 코드·라이브러리·이미지·번호·추론 설정)는 릴리스 묶음의 manifest 에서 읽는다(release_bundle.py).
SSM 파라미터(Terraform infra/stacks/sagemaker-review-score)에서는 역할·서브넷·태그·S3 경로처럼 버전과 무관한 값과, 지금 쓸 버전 이름(release) 하나만 읽는다.
코드에 계정 ID·버킷 이름을 두지 않는다.
실행: python deploy/run_processing_job.py --input-key <Silver 후기 파일 S3 키> [--release 2.4b_score_s2c] [--select-unscored] [--date 2026-10-20] [--wait] [--dry-run]
      --release: 실행할 모델 버전. 기본은 SSM 설정의 release. 버전을 바꾸는 것(되돌림 포함)은 SSM 값 하나만 바꾸면 된다
      실행 전에 manifest 형식과 S3 가중치(파일 이름·크기)를 대조해 어긋나면 Job 을 만들지 않는다
      --select-unscored: 점수 로그(review_score_log)에 이미 있는 후기는 빼고 남은 후기만 점수화한다(0건이면 Job 을 만들지 않음).
        --input-key 없이 쓰면 Silver 실행 출력(current.json 의 run_id)에서 최대 --max-reviews 건(기본 1500)을 고른다. --run-id 로 실행을 직접 지정할 수 있다.
        --input-key 와 같이 쓰면 그 JSONL 파일에서 고른다(시험용).
      (입력은 후기 파일 하나의 S3 키. score_batch.py가 파일 하나만 읽는다)
결과: 각 후기를 **자기 작성일(KST)** 폴더에 쓴다: <output_prefix>year=YYYY/month=MM/day=DD/scores_<model_version>_<실행시각>.parquet (+ <output_prefix>_summary_*.json).
      output_prefix 는 Iceberg MERGE 의 입력(staging)이다. 열은 review_id,aspect,score,model_version,model_version_no,analyzed_at,review_date(후기 작성일).
      작성일은 후기 행(review_date_kst 등)에서 읽는다. 행에 없으면 --date, 없으면 입력 키의 year=/month=/day= 를 쓰고, 그것도 없으면 점수를 매기지 않고 오류(no_review_date)에 남긴다.
      파일명에 실행시각이 들어가 같은 날짜·같은 model_version 을 다시 실행해도 덮어쓰지 않고 새 파일이 쌓인다(중복은 merge.sql 이 처리). 실행한 날짜는 경로에 쓰지 않는다.
오류: 파싱 실패 후기는 <error_prefix>year=YYYY/month=MM/day=DD/errors_<model_version>_<실행시각>.jsonl (실패가 있을 때만)"""
import argparse
import json
import re
import time

import boto3

import release_bundle as rb

SSM_NAME = '/clothes-query/dev/sagemaker-review-score/config'
DATE_IN_KEY = re.compile(r'year=(\d{4})/month=(\d{2})/day=(\d{2})')
VERSION_RE = re.compile(r'[A-Za-z0-9._-]+')
VERSION_NO_RE = re.compile(r'\d{1,2}\.\d')   # 모델 번호 "x.y": 메이저 0~99, 마이너 0~9. 평가 모델/로직 변경은 메이저, 작은 수정은 마이너를 올린다(x.9 다음은 메이저)
# SageMaker 는 ContainerArguments 의 문자열 하나가 256자를 넘으면 거절한다(ValidationException).
# 그래서 긴 명령을 한 줄로 만들지 않고, bash -c 의 "$@" 로 인자를 나눠 넘긴다: bash -c '<명령>' <$0> <$1> <$2> ...
# 라이브러리는 릴리스 묶음의 code/requirements.txt(버전 고정 목록)로 설치한다. 버전마다 설치 목록이 고정돼 재실행해도 같은 환경이 된다
RUN = 'pip install -q -r /opt/ml/processing/code/requirements.txt && python /opt/ml/processing/code/score_batch.py "$@"'


def container_args(fname, mv, mvno, dflt, bs):
    """bash -c 에 넘길 인자 목록. 첫 원소가 실행할 명령, 둘째는 $0 자리 이름, 나머지가 score_batch.py 의 인자다."""
    args = [RUN, 'score_batch',
            '--model-dir', '/opt/ml/processing/model',
            '--input', f'/opt/ml/processing/input/{fname}',
            '--output-root', '/opt/ml/processing/output',
            '--error-root', '/opt/ml/processing/errors',
            '--log-root', '/opt/ml/processing/logs',
            '--model-version', mv,
            '--model-version-no', str(mvno),
            '--bs', str(bs)]
    if dflt:
        args += ['--default-date', dflt]
    too_long = [x for x in args if len(x) > 256]
    if too_long:
        raise SystemExit(f'ContainerArguments 항목이 256자를 넘습니다: {too_long[0][:60]}...')
    return args


def s3_input(name, uri, local):
    return dict(InputName=name, S3Input=dict(S3Uri=uri, LocalPath=local, S3DataType='S3Prefix', S3InputMode='File'))


def default_date(input_key, date=None):
    """작성일을 알 수 없는 후기에 쓸 기본 날짜(YYYY-MM-DD). --date 가 우선이고, 없으면 입력 키의 year=/month=/day=. 없으면 None."""
    if date:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            raise SystemExit(f'--date 형식은 YYYY-MM-DD 입니다: {date}')
        return date
    m = DATE_IN_KEY.search(input_key)
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else None


def registry_uri(c, override=None):
    """릴리스 묶음 위치. --registry-uri > SSM registry_prefix > model_prefix 옆의 model-registry/releases/ 순서."""
    uri = override or c.get('registry_prefix')
    if not uri:
        # model_prefix = s3://<버킷>/review-score/model/ → s3://<버킷>/review-score/model-registry/releases/
        uri = c['model_prefix'].rstrip('/').rsplit('/', 1)[0] + '/model-registry/releases/'
    rb.split_uri(uri)
    return uri


def load_release(s3, c, release, reg_uri):
    """버전의 manifest 를 읽고 형식·가중치를 확인한다. 어긋나면 Job 을 만들지 않고 멈춘다."""
    m = rb.read_manifest(s3, reg_uri, release)
    if m is None:
        raise SystemExit(f'{release} 의 manifest 가 없습니다({reg_uri}{release}/{rb.MANIFEST}). '
                         'upload_model.py 로 묶음을 만든 버전만 실행할 수 있습니다')
    errs = rb.check_manifest(m, release) or rb.verify_weights(s3, m)
    if errs:
        raise SystemExit('manifest 확인 실패:\n  ' + '\n  '.join(errs))
    return m


def build_request(c, m, reg_uri, input_key, instance=None, max_seconds=None, name=None, date=None):
    """SSM 설정 c 와 manifest m 으로 create_processing_job 인자를 만든다 (AWS 호출 없음)."""
    name = name or f'{c["job_name_prefix"]}-{time.strftime("%Y%m%d-%H%M%S")}'
    fname = input_key.rsplit('/', 1)[-1]
    # 이름과 번호는 manifest 에서만 가져온다(1:1 이 깨지지 않게 따로 덮어쓰는 인자를 두지 않는다)
    mv, mvno = m['model_version'], m['model_version_no']
    if not isinstance(mvno, str) or not VERSION_NO_RE.fullmatch(mvno):
        raise SystemExit(f'model_version_no 는 "x.y" 형식(예: 1.0)이어야 합니다: {mvno!r}')
    if not VERSION_RE.fullmatch(mv):
        raise SystemExit(f'model_version 형식 오류(영문·숫자·._- 만): {mv}')
    dflt = default_date(input_key, date)
    req = dict(
        ProcessingJobName=name, RoleArn=c['role_arn'],
        AppSpecification=dict(ImageUri=m['runtime']['image_uri'], ContainerEntrypoint=['bash', '-c'],
                              ContainerArguments=container_args(fname, mv, mvno, dflt, m['inference'].get('bs', 16))),
        ProcessingResources=dict(ClusterConfig=dict(InstanceCount=1, InstanceType=instance or c['instance_type'],
                                                    VolumeSizeInGB=c['volume_size_gb'])),
        # 비용 안전장치: 이 시간이 지나면 SageMaker가 작업을 중단한다
        StoppingCondition=dict(MaxRuntimeInSeconds=max_seconds or c['max_runtime_seconds']),
        ProcessingInputs=[
            # 가중치와 실행 코드는 manifest 가 가리키는 그 버전의 것만 쓴다 (code/ 에는 score_batch.py 와 requirements.txt)
            s3_input('model', m['weights']['uri'], '/opt/ml/processing/model'),
            s3_input('code', f'{reg_uri}{mv}/code/', '/opt/ml/processing/code'),
            s3_input('input', f's3://{c["bucket"]}/{input_key}', '/opt/ml/processing/input'),
        ],
        # score_batch.py 가 컨테이너 출력 폴더 안에 year=/month=/day=/ 하위 폴더를 만들고, SageMaker 가 그 구조 그대로 S3 접두사(staging) 아래에 올린다.
        # 파일명에 실행시각이 들어가 같은 날짜·버전을 다시 실행해도 덮어쓰지 않는다
        ProcessingOutputConfig=dict(Outputs=[
            dict(OutputName='scores', S3Output=dict(S3Uri=c['output_prefix'], LocalPath='/opt/ml/processing/output', S3UploadMode='EndOfJob')),
            dict(OutputName='errors', S3Output=dict(S3Uri=c['error_prefix'], LocalPath='/opt/ml/processing/errors', S3UploadMode='EndOfJob')),
            # 후기별 점수 로그(속성 0개 후기 포함). athena 스택의 staging 로그 테이블이 읽고 merge_log.sql 이 review_score_log 에 반영한다
            dict(OutputName='logs', S3Output=dict(S3Uri=c['log_prefix'], LocalPath='/opt/ml/processing/logs', S3UploadMode='EndOfJob')),
        ]),
        Tags=c['tags'],   # Component 태그: 비용 추적용
    )
    if c.get('network'):   # use_vpc=true 일 때만 값이 있다
        req['NetworkConfig'] = dict(VpcConfig=dict(SecurityGroupIds=c['network']['security_groups'],
                                                   Subnets=c['network']['subnets']))
    return req


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-key', default=None, help='버킷 안의 후기 파일 키(CSV review_id,text 또는 JSONL). --select-unscored 와 함께 쓰면 그 파일에서 미점수 후기를 고르고(시험용), 없으면 Silver 실행 출력에서 고른다')
    ap.add_argument('--run-id', default=None, help='--select-unscored(Silver 방식)가 읽을 Silver 실행 ID. 기본은 current.json 의 run_id')
    ap.add_argument('--max-reviews', type=int, default=1500, help='--select-unscored(Silver 방식)에서 이번 Job 에 넣을 최대 후기 수. Job 한 번의 한계(약 2,200건, 최대 실행시간 3600초) 안쪽으로 둔다')
    ap.add_argument('--date', default=None, help='작성일을 알 수 없는 후기에 쓸 날짜(KST, YYYY-MM-DD). 기본은 입력 키의 year=/month=/day=')
    ap.add_argument('--release', default=None, help='실행할 모델 버전(릴리스 묶음 이름). 기본은 SSM 설정의 release')
    ap.add_argument('--registry-uri', default=None, help='릴리스 묶음 위치. 기본은 SSM 설정(registry_prefix 또는 model_prefix 옆 model-registry/releases/)')
    ap.add_argument('--select-unscored', action='store_true',
                    help='Job 전에 select_unscored 를 실행해 점수 로그에 없는 후기만 입력으로 쓴다. 남은 후기가 0건이면 Job 을 만들지 않고 정상 종료')
    ap.add_argument('--athena-ssm-name', default='/clothes-query/dev/athena-review-score/config', help='--select-unscored 가 읽는 athena 설정 파라미터')
    ap.add_argument('--ssm-name', default=SSM_NAME)
    ap.add_argument('--region', default='ap-northeast-1')
    ap.add_argument('--instance', default=None, help='기본은 SSM 설정의 instance_type')
    ap.add_argument('--max-seconds', type=int, default=None, help='기본은 SSM 설정의 max_runtime_seconds')
    ap.add_argument('--dry-run', action='store_true', help='요청 내용만 출력하고 Job은 만들지 않는다(과금 없음)')
    ap.add_argument('--wait', action='store_true')
    a = ap.parse_args()
    c = json.loads(boto3.client('ssm', region_name=a.region).get_parameter(Name=a.ssm_name)['Parameter']['Value'])
    release = a.release or c.get('release')
    if not release:
        raise SystemExit('실행할 버전이 없습니다. --release 를 주거나 SSM 설정에 release 를 넣으세요(sagemaker 스택)')
    reg_uri = registry_uri(c, a.registry_uri)
    m = load_release(boto3.client('s3', region_name=a.region), c, release, reg_uri)
    print(f'버전 {release} (번호 {m["model_version_no"]}' + (f', {m["based_on"]} 되돌림' if m.get('based_on') else '') + ')', flush=True)
    input_key = a.input_key
    selected_info = None
    if a.select_unscored and not a.input_key:
        # (A) Silver 실행 출력에서 점수 없는 후기만 골라 최대 --max-reviews 건을 새 입력으로 쓴다(Athena 읽기 전용 외부 테이블 사용)
        import select_unscored as su
        ssm = boto3.client('ssm', region_name=a.region)
        at_cfg = json.loads(ssm.get_parameter(Name=a.athena_ssm_name)['Parameter']['Value'])
        no = a.model_version_no if a.model_version_no is not None else m['model_version_no']   # 번호는 릴리스 묶음(manifest)에서 온다
        selected_info = su.select_unscored_from_silver(boto3.client('s3', region_name=a.region), boto3.client('athena', region_name=a.region),
                                                       c, at_cfg, no, a.run_id, a.max_reviews, a.dry_run)
        print(f"Silver 실행 {selected_info['run_id']}: 전체 {selected_info['silver_total']}건, 이미 점수 있음 {selected_info['scored']}건, "
              f"점수 필요 {selected_info['unscored_total']}건 → 이번에 {selected_info['selected']}건, 남음 {selected_info['remaining']}건", flush=True)
        if not selected_info['selected']:
            print('남은 후기가 없어 Job 을 만들지 않습니다.')
            return
        input_key = selected_info['output_key']
    elif a.select_unscored:
        # (B) 시험용: 주어진 JSONL 파일에서 이미 점수가 있는 후기를 뺀다
        import select_unscored as su
        ssm = boto3.client('ssm', region_name=a.region)
        at_cfg = json.loads(ssm.get_parameter(Name=a.athena_ssm_name)['Parameter']['Value'])
        no = a.model_version_no if a.model_version_no is not None else m['model_version_no']   # 번호는 릴리스 묶음(manifest)에서 온다
        res = su.select_unscored(boto3.client('s3', region_name=a.region), boto3.client('athena', region_name=a.region), c['bucket'],
                                 a.input_key, c['unscored_prefix'], at_cfg, no, a.date, a.dry_run)
        print(f"입력 {res['input']}건(입력 안 중복 {res['duplicate']}건), 이미 점수 있음 {res['scored']}건, 점수 필요 {res['unscored']}건", flush=True)
        if not res['unscored']:
            print('남은 후기가 없어 Job 을 만들지 않습니다.')
            return
        input_key = res['output_key'] if res['output_key'] else a.input_key
    elif not a.input_key:
        raise SystemExit('--input-key 가 필요합니다(또는 --select-unscored 로 Silver 실행 출력에서 고르기)')
    req = build_request(c, m, reg_uri, input_key, a.instance, a.max_seconds, date=a.date)
    if a.dry_run:
        print(json.dumps(req, ensure_ascii=False, indent=2))
        return
    sm = boto3.client('sagemaker', region_name=c['region'])
    sm.create_processing_job(**req)
    name = req['ProcessingJobName']
    print('시작:', name, flush=True)
    if selected_info:
        print(f"Job 이 끝나면 작성일 {', '.join(selected_info['review_dates'])} 에 대해 merge.sql → merge_log.sql 을 실행하세요 (남은 후기 {selected_info['remaining']}건)", flush=True)
    while a.wait:
        d = sm.describe_processing_job(ProcessingJobName=name)
        print(time.strftime('%H:%M:%S'), d['ProcessingJobStatus'], d.get('FailureReason', ''), flush=True)
        if d['ProcessingJobStatus'] in ('Completed', 'Failed', 'Stopped'):
            if d['ProcessingJobStatus'] == 'Completed':
                t = (d['ProcessingEndTime'] - d['ProcessingStartTime']).total_seconds()
                print(f'실행 시간(과금 대상에 가까움) {t:.0f}초')
            break
        time.sleep(30)


if __name__ == '__main__':
    main()
