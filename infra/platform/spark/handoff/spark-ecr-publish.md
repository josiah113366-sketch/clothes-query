# Spark ECR 발행 안내

2026-10-23 저장소와 개발자 push 권한을 실제 적용했고, 기본 이미지 발행·검증까지 완료했다. 업무 이미지는 동료가 빌드·발행한다.

| 용도 | 주소 |
|---|---|
| 기본 Spark 이미지 | 827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/spark-base |
| Silver·Gold A 업무 이미지 | 827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/silver-gold-a |

개발자 ARN은 arn:aws:iam::827913617635:user/de-ai-18이다. 이번 정책은 위 두 저장소의 이미지 push/pull과 ECR 로그인 토큰 발급만 추가한다. 저장소 삭제·다른 저장소 push·S3·Glue·EKS 권한은 이 정책으로 추가하지 않는다. 사용자가 이미 가진 다른 정책은 유지한다. 실행 중인 Driver/Executor의 Pod Identity와는 별개다.

## 담당 및 순서

기본 이미지의 고정 참조:

```text
827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/spark-base@sha256:9548d0949843699f8722a4eb78551129ab718a340a618a06f088483c0ac7985f
```

Spark 4.2.0 / Python 3.10.12 / Java 21 / Scala 2.13 / Hadoop 3.5.0, linux/amd64다. PyYAML 6.0.3·boto3 1.43.71·PyArrow 25.0.1·tzdata 2026.3을 포함한다. 네트워크 없는 로컬 검증에서 위 버전·JAR 10개 체크섬·S3A/Pod Identity credential provider/Kafka/PostgreSQL 클래스 로딩·가짜 숫자 1,000개 계산·Parquet 왕복을 통과했다. ECR manifest/config가 검증한 로컬 이미지와 같은 것을 확인했다. 실제 AWS 업무 입력·S3 쓰기·실행 권한 검증을 대신하지 않는다.

1. 인프라 담당자가 기본 Spark 이미지를 발행하고 immutable digest를 전달한다. Spark 4.2.0 / Python 3.10.12 기준이다.
2. 동료는 main의 pipelines/Dockerfile을 저장소 루트 context로 빌드한다. SPARK_IMAGE에는 전달받은 기본 이미지의 전체 @sha256 참조, CODE_REF와 이미지 태그에는 실제 커밋 해시를 지정한다.
3. 동료가 업무 저장소에 push하고 최종 업무 이미지 @sha256 참조를 전달한다. 명령과 자원 조건이 달라졌으면 함께 전달한다.
4. 인프라 담당자가 digest를 runtime ConfigMap에 연결한다. 이미지 push만으로 DAG가 실행되거나 Spark 노드가 생성되지는 않는다.

## 로그인

de-ai-18 자격증명을 선택한 터미널에서 실행한다. 다른 사용자의 키를 전달받을 필요는 없다. AWS CLI profile을 사용한다면 해당 profile을 선택한 뒤 실행한다.

```powershell
aws sts get-caller-identity
aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin 827913617635.dkr.ecr.ap-northeast-1.amazonaws.com
```

최신 main을 받은 저장소 루트에서 빌드·push한다. 코드는 깨끗한 커밋 상태로 준비하고 CODE_REF에는 실제 업무 코드 커밋을 사용한다. 태그는 IMMUTABLE이므로 기존 태그를 덮어쓰지 말고 새 커밋 태그를 사용한다.

```powershell
$sparkBase = '827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/spark-base@sha256:9548d0949843699f8722a4eb78551129ab718a340a618a06f088483c0ac7985f'
$pipelineCommit = (git rev-parse HEAD).Trim()
$pipelineImage = "827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/silver-gold-a:${pipelineCommit}"
docker build --platform linux/amd64 -f pipelines/Dockerfile --build-arg "SPARK_IMAGE=$sparkBase" --build-arg "CODE_REF=$pipelineCommit" -t $pipelineImage .
# 빌드가 성공한 경우에만 실행한다.
docker push $pipelineImage
```

push 후 확인 명령:

```powershell
aws ecr describe-images --region ap-northeast-1 --repository-name clothes-query-dev/silver-gold-a --image-ids imageTag=<커밋해시> --query 'imageDetails[0].imageDigest' --output text
```

describe-images는 메타데이터 조회 권한이 별도로 있어야 한다. 이번 push 정책에는 포함하지 않았으므로 권한이 없으면 docker push 출력의 digest를 전달하면 된다. 실패 시 오류 문구만 공유하고 비밀번호·로그인 토큰·접근 키는 보내지 않는다.
