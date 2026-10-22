# 판정·조사 개발 연결

## 접속 역할

`agent-development-access` 스택은 동료의 명시된 IAM 신원만 신뢰하는 별도 개발자 역할을 만든다. `namespace-access.yaml`은 그 역할의 EKS group에 `agent` namespace Pod/Job 생성·조회·정리, 로그·이벤트·ServiceAccount 조회를 허용한다. Secret·RBAC·ServiceAccount 수정, exec, 다른 namespace, node 조회는 허용하지 않는다.

Pod 생성자는 해당 namespace의 ServiceAccount를 사용해 AWS 작업을 실행할 수 있다. 따라서 이것은 판정·조사 개발을 위한 신뢰된 개발자 권한이며 데이터 접근 자체를 차단하는 격리 경계는 아니다. namespace에 더 강한 ServiceAccount를 추가할 때 재검토한다. 기존 관리자 역할 접근은 유지되므로 계정 전체의 권한 축소를 뜻하지 않는다.

```powershell
aws eks update-kubeconfig --region ap-northeast-1 --name clothes-query-dev-eks --role-arn <개발자-역할-ARN> --alias clothes-query-dev-agent
kubectl --context clothes-query-dev-agent auth can-i create jobs -n agent
kubectl --context clothes-query-dev-agent auth can-i get pods --subresource=log -n agent
kubectl --context clothes-query-dev-agent auth can-i get secrets -n agent
kubectl --context clothes-query-dev-agent auth can-i create pods -n kafka
```

예상 결과는 yes, yes, no, no다. kubeconfig 명령은 현재 context도 바꾸므로 관리 작업 전에는 context를 확인한다. 이 접속은 Kubernetes 리소스 배포용이며 업무 AWS API는 Pod의 `detection-job`/`investigation-agent` ServiceAccount 역할을 사용한다.

## 이미지 등록

판정 저장소는 `clothes-query-dev/detection-job`, 조사 저장소는 `clothes-query-dev/investigation-agent`다. 실제 URL은 비공개 output으로 전달한다. 개발자 역할로 AssumeRole하는 AWS CLI 프로필 `agent-dev`를 만든 뒤 아래처럼 실행한다. 장기 키를 이미지나 Pod에 넣지 않는다.

```powershell
aws configure set profile.agent-dev.role_arn <개발자-역할-ARN>
aws configure set profile.agent-dev.source_profile <본인-AWS-프로필>
aws configure set profile.agent-dev.region ap-northeast-1
$registry = '<비공개-ECR-registry>'
$imageTag = '<새로운-커밋-SHA>'
aws ecr get-login-password --profile agent-dev --region ap-northeast-1 | docker login --username AWS --password-stdin $registry
docker build --platform linux/amd64 -t "${registry}/clothes-query-dev/detection-job:${imageTag}" agent/detect
docker push "${registry}/clothes-query-dev/detection-job:${imageTag}"
```

PR #46 Dockerfile 기준 build context는 `agent/detect`이고 ENTRYPOINT는 `python run_job.py`다. 위 명령은 해당 PR 파일을 받은 뒤 실행하며 아직 실제 빌드 성공을 뜻하지 않는다. 태그는 immutable이므로 덮어쓰지 말고 새 SHA를 사용한다. push 후 repository/tag/digest와 필요한 환경변수·자원·실행 명령을 인프라 담당에게 전달한다. 이번 준비에서 Docker를 시작하거나 이미지를 빌드하지 않는다.

## Airflow 승인 API

현재 개발 Airflow는 3.3.2 / Simple Auth Manager다. 승인 백엔드는 EKS 내부 Airflow Service에 `POST /auth/token`으로 JSON `{"username":"approval","password":"<Secret에서 읽은 값>"}`을 보내고 반환된 `access_token`을 `Authorization: Bearer ...`로 사용한다. 그 다음 `POST /api/v2/dags/{dag_id}/dagRuns`를 호출한다. 토큰 만료 시 다시 발급하고 비밀번호·JWT는 브라우저/로그/Git에 넣지 않는다. 서버는 TLS를 종단하는 외부 ALB가 아니라 내부 Service로 준비돼 있으며 실제 접속 값은 비공개 전달한다.

승인 사용자 로그인·DAG 실행은 이전 설치 검증에서 확인했다. Simple Auth의 user 역할은 특정 DAG 하나만 허용하는 세밀한 권한을 대신하지 않는다. 대시보드 namespace·ServiceAccount·Airflow Secret 공급·네트워크 정책을 받은 뒤 실제 Pod를 연결한다. IAM 역할만으로 Airflow JWT가 발급되지는 않는다. [공식 토큰 안내](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/auth-manager/simple/token.html).

## 확정된 기반과 협의 대기

- 기존 판정/조사 Pod Identity·workgroup·각각의 `athena-results/detection/`, `athena-results/investigation/` 결과 경로를 유지한다. `ground_truth/` 금지도 유지한다.
- 판정 쓰기 제안: `gold_b.anomaly`, `gold_b.detection_runs`, `gold_b.reprocess_events`; 각 `gold_b/<테이블>/`; Athena INSERT INTO. 아직 쓰기 권한은 활성화하지 않는다. 은서 님과 DDL·LOCATION·시간 파티션·파일 형식·INSERT SQL을 확정한 뒤 필요한 Glue 파티션 권한까지 맞춘다. INSERT는 기존 파일 갱신이 아닌 추가이므로 재시도 중복도 별도로 처리한다.
- 조사 쓰기: 후속 답변으로 Glue DB `agent`, S3 `agent/<테이블>/`로 분리하기로 결정했다. 테이블 이름/DDL/쓰기 방식은 입력 대기이며 다른 장부는 읽기만 유지한다. 데이터 역할 변경은 별도 후속 작업으로 관리한다.
- 대시보드: namespace·ServiceAccount, 승인 기록 INSERT SQL, workgroup, 호출 DAG ID·conf·중복 승인 처리 계약을 요청한다. 실제 역할/Pod Identity는 해당 입력을 받은 뒤 연결한다.
- 판정 DAG 제안은 `detect_job_5min`, `*/5 * * * *`, `ATHENA_WORKGROUP`에 기존 판정 workgroup을 주입하는 것이다. 업무 DAG를 생성·활성화하지 않는다. 이미지 digest·명령·자원·timeout·재시도·UTC 처리 계약을 받은 뒤 연결하고 실제 5분 실행을 측정한다.
- Bedrock은 모델 ID·Converse/tool-use 요구·리전 범위를 정한 뒤 조사 Pod 역할에 허용한다. 도쿄 endpoint 지원과 도쿄 내 추론은 다르며 cross-region profile을 임의로 활성화하지 않는다. 모델 목록 조회는 실제 호출 성공·계정 이용 가능성을 보장하지 않는다.

2026-10-21 읽기 전용 조회에서 `amazon.nova-lite-v1:0`는 Tokyo ON_DEMAND/ACTIVE이고 계정 availability가 AUTHORIZED/AVAILABLE이었다. `anthropic.claude-haiku-4-5-20251001-v1:0`도 계정 availability는 AVAILABLE이지만 목록상 INFERENCE_PROFILE 전용이다. 아직 모델 호출·조사 Pod 권한 추가·리전 간 추론 허용은 하지 않았다. Nova Lite는 직접 호출 후보이며 실제 조사 품질·tool-use 호환은 별도 검증한다.

5분 내 완료, INSERT 재시도의 중복 방지, Simple Auth의 특정 DAG만 허용, 개발자 기존 광범위 권한의 전체 회수는 현재 준비만으로 보장하지 않는다.
