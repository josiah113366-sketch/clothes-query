"""SageMaker Processing Job으로 후기 점수화를 한 번 실행한다 (팀 계정용). 컨테이너 안에서는 로컬 경로만 쓰고, S3 입출력은 SageMaker가 처리한다.
역할·이미지·서브넷·태그·S3 경로는 Terraform(infra/stacks/sagemaker-review-score)이 만든 SSM 파라미터에서 읽는다. 코드에 계정 ID·버킷 이름을 두지 않는다.
실행: python deploy/run_processing_job.py --input-key bronze/reviews/year=2026/month=10/day=20/part-00000.jsonl [--wait] [--dry-run]
      (입력은 후기 파일 하나의 S3 키. score_batch.py가 파일 하나만 읽는다)
결과: <output_prefix><작업 이름>/scores.csv (+ scores.csv.summary.json)"""
import argparse
import json
import time

import boto3

SSM_NAME = '/clothes-query/dev/sagemaker-review-score/config'
MODEL_DIR_NAME = '2.4b_score_s2c'   # upload_model.py로 <model_prefix><이름>/ 에 올린 합친 모델 폴더
CMD = ('pip install -q "transformers==4.53.3" accelerate && '
       'python /opt/ml/processing/code/score_batch.py --model-dir /opt/ml/processing/model '
       '--input /opt/ml/processing/input/{name} --output /opt/ml/processing/output/scores.csv')


def s3_input(name, uri, local):
    return dict(InputName=name, S3Input=dict(S3Uri=uri, LocalPath=local, S3DataType='S3Prefix', S3InputMode='File'))


def build_request(c, input_key, instance=None, max_seconds=None, name=None):
    """SSM 설정 c 로 create_processing_job 인자를 만든다 (AWS 호출 없음)."""
    name = name or f'{c["job_name_prefix"]}-{time.strftime("%Y%m%d-%H%M%S")}'
    fname = input_key.rsplit('/', 1)[-1]
    req = dict(
        ProcessingJobName=name, RoleArn=c['role_arn'],
        AppSpecification=dict(ImageUri=c['image_uri'], ContainerEntrypoint=['bash', '-c'],
                              ContainerArguments=[CMD.format(name=fname)]),
        ProcessingResources=dict(ClusterConfig=dict(InstanceCount=1, InstanceType=instance or c['instance_type'],
                                                    VolumeSizeInGB=c['volume_size_gb'])),
        # 비용 안전장치: 이 시간이 지나면 SageMaker가 작업을 중단한다
        StoppingCondition=dict(MaxRuntimeInSeconds=max_seconds or c['max_runtime_seconds']),
        ProcessingInputs=[
            s3_input('model', f'{c["model_prefix"]}{MODEL_DIR_NAME}/', '/opt/ml/processing/model'),
            s3_input('code', f'{c["code_prefix"]}score_batch.py', '/opt/ml/processing/code'),
            s3_input('input', f's3://{c["bucket"]}/{input_key}', '/opt/ml/processing/input'),
        ],
        ProcessingOutputConfig=dict(Outputs=[dict(OutputName='scores', S3Output=dict(
            S3Uri=f'{c["output_prefix"]}{name}/', LocalPath='/opt/ml/processing/output', S3UploadMode='EndOfJob'))]),
        Tags=c['tags'],   # Component 태그: 비용 추적용
    )
    if c.get('network'):   # use_vpc=true 일 때만 값이 있다
        req['NetworkConfig'] = dict(VpcConfig=dict(SecurityGroupIds=c['network']['security_groups'],
                                                   Subnets=c['network']['subnets']))
    return req


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-key', required=True, help='버킷 안의 후기 파일 키(CSV review_id,text 또는 JSONL)')
    ap.add_argument('--ssm-name', default=SSM_NAME)
    ap.add_argument('--region', default='ap-northeast-1')
    ap.add_argument('--instance', default=None, help='기본은 SSM 설정의 instance_type')
    ap.add_argument('--max-seconds', type=int, default=None, help='기본은 SSM 설정의 max_runtime_seconds')
    ap.add_argument('--dry-run', action='store_true', help='요청 내용만 출력하고 Job은 만들지 않는다(과금 없음)')
    ap.add_argument('--wait', action='store_true')
    a = ap.parse_args()
    c = json.loads(boto3.client('ssm', region_name=a.region).get_parameter(Name=a.ssm_name)['Parameter']['Value'])
    req = build_request(c, a.input_key, a.instance, a.max_seconds)
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
