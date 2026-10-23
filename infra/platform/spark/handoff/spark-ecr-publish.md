# Spark ECR 발행 안내

2026-10-23 저장소와 개발자 push 권한을 실제 적용했다. 이미지 자체는 아직 미발행이다.

| 용도 | 주소 |
|---|---|
| 기본 Spark 이미지 | 827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/spark-base |
| Silver·Gold A 업무 이미지 | 827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/silver-gold-a |

개발자 ARN은 arn:aws:iam::827913617635:user/de-ai-18이다. 이번 정책은 위 두 저장소의 이미지 push/pull과 ECR 로그인 토큰 발급만 추가한다. 저장소 삭제·다른 저장소 push·S3·Glue·EKS 권한은 이 정책으로 추가하지 않는다. 사용자가 이미 가진 다른 정책은 유지한다. 실행 중인 Driver/Executor의 Pod Identity와는 별개다.

## 담당 및 순서

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

빌드 예시는 pipelines/README.md의 운영 이미지 명령을 따른다. 최종 기본 digest를 받기 전에는 placeholder로 push하지 않는다. linux/amd64 플랫폼을 사용한다. 태그는 IMMUTABLE이므로 기존 태그를 덮어쓰지 말고 새 커밋 태그를 사용한다.

push 후 확인 명령:

```powershell
aws ecr describe-images --region ap-northeast-1 --repository-name clothes-query-dev/silver-gold-a --image-ids imageTag=<커밋해시> --query 'imageDetails[0].imageDigest' --output text
```

describe-images는 메타데이터 조회 권한이 별도로 있어야 한다. 이번 push 정책에는 포함하지 않았으므로 권한이 없으면 docker push 출력의 digest를 전달하면 된다. 실패 시 오류 문구만 공유하고 비밀번호·로그인 토큰·접근 키는 보내지 않는다.
