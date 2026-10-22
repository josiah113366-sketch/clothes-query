"""SageMaker Processing Job으로 후기 점수화를 한 번 실행한다 (팀 계정용). 컨테이너 안에서는 로컬 경로만 쓰고, S3 입출력은 SageMaker가 처리한다.
역할·이미지·서브넷·태그·S3 경로는 Terraform(infra/stacks/sagemaker-review-score)이 만든 SSM 파라미터에서 읽는다. 코드에 계정 ID·버킷 이름을 두지 않는다.
실행: python deploy/run_processing_job.py --input-key <Silver 후기 파일 S3 키> [--date 2026-10-20] [--model-version 2.4b_score_s2c] [--wait] [--dry-run]
      (입력은 후기 파일 하나의 S3 키. score_batch.py가 파일 하나만 읽는다)
결과: 각 후기를 **자기 작성일(KST)** 폴더에 쓴다: <output_prefix>year=YYYY/month=MM/day=DD/scores_<model_version>_<실행시각>.parquet (+ <output_prefix>_summary_*.json).
      output_prefix 는 Iceberg MERGE 의 입력(staging)이다. 열은 review_id,aspect,score,model_version,analyzed_at,review_date(후기 작성일).
      작성일은 후기 행(review_date_kst 등)에서 읽는다. 행에 없으면 --date, 없으면 입력 키의 year=/month=/day= 를 쓰고, 그것도 없으면 점수를 매기지 않고 오류(no_review_date)에 남긴다.
      파일명에 실행시각이 들어가 같은 날짜·같은 model_version 을 다시 실행해도 덮어쓰지 않고 새 파일이 쌓인다(중복은 merge.sql 이 처리). 실행한 날짜는 경로에 쓰지 않는다.
오류: 파싱 실패 후기는 <error_prefix>year=YYYY/month=MM/day=DD/errors_<model_version>_<실행시각>.jsonl (실패가 있을 때만)"""
import argparse
import json
import re
import time

import boto3

SSM_NAME = '/clothes-query/dev/sagemaker-review-score/config'
MODEL_DIR_NAME = '2.4b_score_s2c'   # upload_model.py로 <model_prefix><이름>/ 에 올린 합친 모델 폴더
DATE_IN_KEY = re.compile(r'year=(\d{4})/month=(\d{2})/day=(\d{2})')
VERSION_RE = re.compile(r'[A-Za-z0-9._-]+')
CMD = ('pip install -q "transformers==4.53.3" accelerate pyarrow && '
       'python /opt/ml/processing/code/score_batch.py --model-dir /opt/ml/processing/model '
       '--input /opt/ml/processing/input/{name} --output-root /opt/ml/processing/output '
       '--error-root /opt/ml/processing/errors --model-version {mv}{dflt}')


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


def build_request(c, input_key, instance=None, max_seconds=None, name=None, date=None, model_version=None):
    """SSM 설정 c 로 create_processing_job 인자를 만든다 (AWS 호출 없음)."""
    name = name or f'{c["job_name_prefix"]}-{time.strftime("%Y%m%d-%H%M%S")}'
    fname = input_key.rsplit('/', 1)[-1]
    mv = model_version or c.get('model_version') or MODEL_DIR_NAME
    if not VERSION_RE.fullmatch(mv):
        raise SystemExit(f'model_version 형식 오류(영문·숫자·._- 만): {mv}')
    dflt = default_date(input_key, date)
    req = dict(
        ProcessingJobName=name, RoleArn=c['role_arn'],
        AppSpecification=dict(ImageUri=c['image_uri'], ContainerEntrypoint=['bash', '-c'],
                              ContainerArguments=[CMD.format(name=fname, mv=mv, dflt=f' --default-date {dflt}' if dflt else '')]),
        ProcessingResources=dict(ClusterConfig=dict(InstanceCount=1, InstanceType=instance or c['instance_type'],
                                                    VolumeSizeInGB=c['volume_size_gb'])),
        # 비용 안전장치: 이 시간이 지나면 SageMaker가 작업을 중단한다
        StoppingCondition=dict(MaxRuntimeInSeconds=max_seconds or c['max_runtime_seconds']),
        ProcessingInputs=[
            s3_input('model', f'{c["model_prefix"]}{MODEL_DIR_NAME}/', '/opt/ml/processing/model'),
            s3_input('code', f'{c["code_prefix"]}score_batch.py', '/opt/ml/processing/code'),
            s3_input('input', f's3://{c["bucket"]}/{input_key}', '/opt/ml/processing/input'),
        ],
        # score_batch.py 가 컨테이너 출력 폴더 안에 year=/month=/day=/ 하위 폴더를 만들고, SageMaker 가 그 구조 그대로 S3 접두사(staging) 아래에 올린다.
        # 파일명에 실행시각이 들어가 같은 날짜·버전을 다시 실행해도 덮어쓰지 않는다
        ProcessingOutputConfig=dict(Outputs=[
            dict(OutputName='scores', S3Output=dict(S3Uri=c['output_prefix'], LocalPath='/opt/ml/processing/output', S3UploadMode='EndOfJob')),
            dict(OutputName='errors', S3Output=dict(S3Uri=c['error_prefix'], LocalPath='/opt/ml/processing/errors', S3UploadMode='EndOfJob')),
        ]),
        Tags=c['tags'],   # Component 태그: 비용 추적용
    )
    if c.get('network'):   # use_vpc=true 일 때만 값이 있다
        req['NetworkConfig'] = dict(VpcConfig=dict(SecurityGroupIds=c['network']['security_groups'],
                                                   Subnets=c['network']['subnets']))
    return req


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-key', required=True, help='버킷 안의 후기 파일 키(CSV review_id,text 또는 JSONL)')
    ap.add_argument('--date', default=None, help='작성일을 알 수 없는 후기에 쓸 날짜(KST, YYYY-MM-DD). 기본은 입력 키의 year=/month=/day=')
    ap.add_argument('--model-version', default=None, help='출력 열·파일명의 model_version. 기본은 SSM 설정의 model_version')
    ap.add_argument('--ssm-name', default=SSM_NAME)
    ap.add_argument('--region', default='ap-northeast-1')
    ap.add_argument('--instance', default=None, help='기본은 SSM 설정의 instance_type')
    ap.add_argument('--max-seconds', type=int, default=None, help='기본은 SSM 설정의 max_runtime_seconds')
    ap.add_argument('--dry-run', action='store_true', help='요청 내용만 출력하고 Job은 만들지 않는다(과금 없음)')
    ap.add_argument('--wait', action='store_true')
    a = ap.parse_args()
    c = json.loads(boto3.client('ssm', region_name=a.region).get_parameter(Name=a.ssm_name)['Parameter']['Value'])
    req = build_request(c, a.input_key, a.instance, a.max_seconds, date=a.date, model_version=a.model_version)
    if a.dry_run:
        print(json.dumps(req, ensure_ascii=False, indent=2))
        return
    sm = boto3.client('sagemaker', region_name=c['region'])
    sm.create_processing_job(**req)
    name = req['ProcessingJobName']
    print('시작:', name, flush=True)
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
