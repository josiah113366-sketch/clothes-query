"""SageMaker Processing Job으로 후기 점수화를 한 번 실행한다. 컨테이너 안에서는 로컬 경로만 쓰고, S3 입출력은 SageMaker가 처리한다.
실행: python deploy/run_processing_job.py --bucket <버킷> --input-key input/reviews_100.csv --output-prefix output/run1/ [--instance ml.g4dn.xlarge]"""
import argparse
import time

import boto3

IMAGE = '763104351884.dkr.ecr.{region}.amazonaws.com/pytorch-training:2.5.1-gpu-py311-cu124-ubuntu22.04-sagemaker'
CMD = ('pip install -q "transformers==4.53.3" accelerate && '
       'python /opt/ml/processing/code/score_batch.py --model-dir /opt/ml/processing/model '
       '--input /opt/ml/processing/input/{name} --output /opt/ml/processing/output/scores.csv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bucket', required=True)
    ap.add_argument('--input-key', required=True)
    ap.add_argument('--output-prefix', required=True)
    ap.add_argument('--region', default='ap-northeast-1')
    ap.add_argument('--instance', default='ml.g4dn.xlarge')
    ap.add_argument('--role-arn', default=None)
    ap.add_argument('--max-seconds', type=int, default=3600, help='비용 안전장치: 이 시간이 지나면 SageMaker가 작업을 중단한다')
    ap.add_argument('--wait', action='store_true')
    a = ap.parse_args()
    sm = boto3.client('sagemaker', region_name=a.region)
    role = a.role_arn or boto3.client('iam').get_role(RoleName=f'review-score-sagemaker-processing-{a.region}')['Role']['Arn']
    name = f'review-score-{time.strftime("%Y%m%d-%H%M%S")}'
    base = f's3://{a.bucket}'
    fname = a.input_key.rsplit('/', 1)[-1]
    sm.create_processing_job(
        ProcessingJobName=name, RoleArn=role,
        AppSpecification=dict(ImageUri=IMAGE.format(region=a.region), ContainerEntrypoint=['bash', '-c'],
                              ContainerArguments=[CMD.format(name=fname)]),
        ProcessingResources=dict(ClusterConfig=dict(InstanceCount=1, InstanceType=a.instance, VolumeSizeInGB=50)),
        StoppingCondition=dict(MaxRuntimeInSeconds=a.max_seconds),
        ProcessingInputs=[
            dict(InputName='model', S3Input=dict(S3Uri=f'{base}/model/2.4b_score_s2c/', LocalPath='/opt/ml/processing/model', S3DataType='S3Prefix', S3InputMode='File')),
            dict(InputName='code', S3Input=dict(S3Uri=f'{base}/code/score_batch.py', LocalPath='/opt/ml/processing/code', S3DataType='S3Prefix', S3InputMode='File')),
            dict(InputName='input', S3Input=dict(S3Uri=f'{base}/{a.input_key}', LocalPath='/opt/ml/processing/input', S3DataType='S3Prefix', S3InputMode='File')),
        ],
        ProcessingOutputConfig=dict(Outputs=[dict(OutputName='scores', S3Output=dict(S3Uri=f'{base}/{a.output_prefix}', LocalPath='/opt/ml/processing/output', S3UploadMode='EndOfJob'))]),
        Tags=[dict(Key='project', Value='review-score')],
    )
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
