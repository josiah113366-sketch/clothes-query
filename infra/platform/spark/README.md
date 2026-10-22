# Spark 실행 기반 — 상시 배포 비활성

최초에는 코드만 준비했고, 이후 사용자 승인으로 2026-10-22 임시 합성 시험을 수행했다. 상시 Spark 배포는 비활성 상태이며 공용 메모리 확대는 참고 대안이다. 실제 시험과 정리는 아래 기록을 따른다.

## 2026-10-22 짧은 합성 시험 결과

- 로컬 기본 이미지 빌드, Spark 4.2.0 합성 계산, S3A/AWS provider/PostgreSQL/Kafka 클래스 로딩 통과. 실제 업무 저장소에는 접속하거나 데이터를 쓰지 않았다.
- 도쿄에서 실행마다 별도 임시 namespace·ECR·t3a.large 한 대분 NodePool을 생성했다. 기존 NodeClass를 재사용했으며 Terraform state나 기존 노드풀·업무 workload는 변경하지 않았다. 시험 2회 모두 노드 기동·이미지 pull·제출기 실행까지 확인했다.
- 클라우드 제출은 Spark 4.2의 NetworkPolicy 생성에 필요한 submitter 권한 누락으로 실패했다. 두 번째 시험에서 403 원인을 확보했고, runtime.py에 spark namespace 한정 NetworkPolicy create/get/patch/delete 권한과 회귀 검사를 추가했다. **수정 후 클라우드 재시험은 하지 않았다.** Driver/Executor 계산·동적 할당·업무 처리량/메모리는 아직 실측 완료가 아니다.
- 비용을 줄이기 위해 두 시험 모두 즉시 namespace와 노드풀을 삭제했고, 임시 EC2 2대의 terminated와 ECR 삭제를 확인했다. 기존 노드는 2대 그대로다. 10분 WhenEmpty 자동 축소를 기다려 검증한 것은 아니다.
- 로컬 검사 12개와 기본 YAML 렌더 통과. 공유 Spark enabled=false 유지. 노드만 생겼다고 실행 검증 완료로 보지 않는다.

## 현재 확인과 두 후보

### 사용자 결정 (2026-10-22)

- 배치는 **Spark 전용 노드풀**로 선택했다. 공용 메모리 확대안은 참고 대안으로만 남긴다.
- 작업이 없으면 전용 노드가 **0대까지 축소**되는 구성을 준비한다. 현재 후보는 빈 노드 10분 후 정리이며, 정확한 삭제 시각을 보장하지 않는다.
- 실행 주기는 미정이다. 작업 종료 후 제출기·Driver·Executor를 정리해야 노드가 비며, 계속 실행하는 스트리밍 Pod가 남으면 0대로 축소되지 않는다.
- **S3 Bronze → Silver/Gold**에 더해 **RDS·Kafka 직접 읽기**도 검토 범위에 포함한다. 모든 작업이 세 저장소를 읽는 것으로 확정하지 않는다. RDS 테이블·읽기 전용 계정·JDBC/TLS, Kafka 토픽·인증·consumer group/offset, S3 경로·checkpoint 및 쓰기 규칙은 미정이다. Gold가 기존 gold_b를 뜻하는지도 팀원에게 확인 후 전달받는다. 연결 정보는 변수/Secret으로 분리하고, 실제 권한은 범위 확정 후 준비한다.
- 최초 노드 타입은 **t3a.large(2CPU/8GiB)**, 전용 풀 한도는 **한 대분인 2CPU/8GiB**로 선택했다. 공유 auto tfvars와 전용 예시에 반영하되 enabled=false는 유지한다. 노드풀 한도는 순간적인 노드 수나 요금의 엄격한 상한을 보장하지 않는다. 실행 이미지는 추가 확인한다.
- 최초 코드 준비 이후 짧은 합성 시험만 추가 승인받았다. 임시 리소스는 정리했고 공유 설정의 enabled=false는 유지한다. 상시 배포는 아직 하지 않는다.
- 이미지 담당: 인프라에서 Spark 기본 이미지와 S3·PostgreSQL JDBC·Kafka 연결 라이브러리를 준비하고, 팀원이 업무 코드와 진입 파일을 추가한다. Spark/Hadoop/Scala 및 연결 라이브러리 버전을 함께 맞춘다. 임시 ECR의 시험 이미지는 정리했고 팀원이 참조할 상시 이미지 저장소에는 아직 발행하지 않았다.
- Spark 버전은 **4.2.0**으로 선택했다. [기본 이미지 파일](image/README.md)에 Dockerfile·연결 의존성 POM·체크섬·jar 충돌 검사 도구를 두었다. digest 고정과 로컬 빌드/클래스 로딩은 통과했고 실제 저장소 접속은 미검증이다.

현재 main `194ff3a`의 `pipelines/`에서 SparkSession/pyspark/spark-submit 코드를 찾지 못했다. 일반 Python 파이프라인을 Spark 작업으로 자동 변환하지 않는다. 팀원의 실제 Spark 이미지·진입 파일·입출력/체크포인트 계약을 받아야 실행 검증이 가능하다.

| 후보 | 구성 | 월 추가 비용 예시 | 주의점 |
|---|---|---:|---|
| 이전 최소 후보 (미선택) | 공용 풀 유지, Spark용 t3a.medium | 1대 상시 약 **$48.13** | 현재 선택은 t3a.large이며 이 금액과 다름 |
| 공용 메모리 확대 | 기존 t3a.large → r6a.large, 2CPU/16GiB | 1대 유지 시 약 **+$31.81** | CPU 예약 조정과 노드 교체 계획이 필요 |

2026-10-22 도쿄 공식 단가·730시간 기준이다. 전용 1대는 EC2+Auto Mode $40.06과 기존 NodeClass의 OS 4GiB+데이터 80GiB gp3 $8.06을 포함한다. 별도 PVC는 없다. 공용안은 컴퓨팅 $80.04→$111.85이며 기존 디스크 용량은 같다고 계산했다. 세금·NAT/S3/전송·CPU credit 추가 과금은 제외한다. 예시 프로필은 벤치마크 결과가 아니며, 노드 수가 늘면 비용도 늘어난다.

### 전용 노드풀 후보

`compute` 스택에 `spark_node_pool` 입력을 추가했다. **기본과 공유 auto tfvars 모두 enabled=false**라 기존 설정으로는 Spark NodePool을 생성하지 않는다. 별도 state/NodeClass를 중복 생성하지 않고 기존 private NodeClass를 참조한다.

실제 적용을 결정하면 선택값을 공유 auto tfvars에 반영하고 현재의 비활성 CI guard도 함께 검토해야 한다. 로컬 var-file에서만 true로 켜 두고 Git에 false를 남기면, 다음 기본 apply가 기존 Spark NodePool을 삭제하려 할 수 있다.

`capacity/dedicated.tfvars.example`은 검토용이다. 활성화할 때는 `clothes-query-dev-compute-spark`, Spark 전용 taint, amd64·On-Demand·두 AZ, t3a.large 한 대분인 2CPU/8GiB의 예산을 사용한다. 모듈의 일반 기본값 대신 공유 auto tfvars의 선택값을 사용한다. 고정 replicas는 없고, 작업 파드가 없으면 노드도 0대일 수 있다. `WhenEmpty`/10분 정리로 실행 중인 작업을 저사용률만으로 통합하지 않는다. OS 패치·만료·장애 교체까지 막는 설정은 아니다.

전용 배치는 Driver 1개와 Executor 초기/최소 1개·최대 2개의 동적 할당으로 준비한다. Kubernetes에서 별도 shuffle service 없이 사용할 수 있도록 shuffle tracking을 켠다. Executor마다 계산 슬롯 1개와 CPU limit 1을 유지하되 CPU request는 500m로 둔다. 두 Executor가 CPU 2개를 독점 보장받는다는 뜻은 아니다.

최대 구성의 요청량은 Driver 250m/1GiB + Executor 2×500m/1.5GiB + 제출기 250m/0.5GiB = **1500m/4.5GiB**다. 이전 t3a.large 관측 가용량 약 1780m/7046MiB와 비교한 계산이며 실제 수용/성능 보장은 아니다. PySpark 네이티브 메모리·시스템 Pod·이미지를 실측해야 한다. 한도 때문에 추가 노드가 생성되지 못하면 Pod가 Pending일 수 있다. 상시 작업이면 Driver와 최소 Executor가 남아 노드도 상시 비용이 발생한다. 모든 작업 Pod가 정리되어야 빈 노드 정리가 가능하다. NodePool 예산은 순간적인 노드 수/요금의 엄격한 상한은 아니다.

동적 할당은 실행 중인 작업의 수요에 반응하며 CPU 사용률만으로 증설하지 않는다. shuffle/cache를 보관한 Executor는 바로 회수되지 않을 수 있다. 실제 Spark 버전·배치/Structured Streaming 실행 형태의 지원 여부는 이미지 확정 후 검증한다. 근거: [Spark 작업 스케줄링](https://spark.apache.org/docs/latest/job-scheduling.html).

### 공용 메모리 확대 후보

`capacity/shared-memory.tfvars.example`은 기존 공용 풀의 타입과 용량 한도를 바꾸는 별도 대안이다. **전용안과 동시에 로드하지 않는다.** 한도 4CPU/32GiB는 r6a.large 두 대분의 교체/증설 여유이며, 한 대만 사용한다는 보장이 아니다.

현재 공용 CPU requests 1650m에 공유 Spark Driver 100m·Executor 500m·완료를 기다리는 제출기 100m를 더하면 **2350m**다. 기존 2CPU 노드의 allocatable 약 1780m를 넘어가므로 RAM만 늘리는 것으로 해결되지 않는다.

`cpu-sizing-candidates.yaml`은 실행 설정이 아닌 분석 자료다. 보조 구성 CPU requests를 줄이는 365m 후보에 브로커 500→250m·Connect 250→100m 후보까지 합하면 765m를 줄일 수 있다. 이 경우 기존 885m+Spark 700m=1585m로, 약 195m 여유가 생긴다는 계산이다. **아직 부하 검증되지 않았으며 현재 Helm 값은 변경하지 않았다.** Spark 렌더/변환 부하, Kafka 지연, Airflow burst, 추가 업무 Pod까지 검증해야 한다. requests를 줄여도 실제 메모리 사용량이 줄어드는 것은 아니다.

기존 Airflow private runtime에는 특정 hostname 고정이 확인됐다. 공용 노드 교체 전에 이 고정 해제/교체를 준비하지 않으면 Airflow가 새 노드로 이동하지 못한다. Kafka PVC의 AZ, 단일 broker와 Airflow 중단 가능성, NodePool drift/교체, 기존 Helm runtime override까지 함께 검토해야 한다. 노드 타입 변경은 무중단 메모리 증설이 아니다.

## 공통 실행 기반

### 입력 연결 설정 틀

사용자 선택에 따라 RDS·Kafka는 **설정 틀만 준비**하며, 실제 권한은 대상 확정 후 적용한다. [connections.example.yaml](connections.example.yaml)은 S3/RDS/Kafka 입력과 Silver/Gold/checkpoint 출력을 정리한 계약 예시다. 미정 값은 null이며 모든 입력의 enabled는 false다. 이것은 Kubernetes manifest나 Spark가 바로 읽는 설정이 아니며, runtime.py는 이 파일을 사용하지 않는다. 실제 작업 이미지에서 읽거나 Spark 옵션으로 변환하는 연결 구현은 이미지 담당자와 맞춘다.

RDS는 JDBC/TLS·읽기 계정·접속 Secret·동시 DB 연결 상한, Kafka는 실제 listener 인증·토픽·시작 offset·배치/스트리밍 방식을 확인해야 한다. Driver/Executor에 필요한 Secret 마운트와 JDBC/Kafka 의존성도 이미지/작업 설계에 맞춰 연결한다. IAM 역할만으로 PostgreSQL 테이블 권한이나 Kafka ACL이 생기지 않는다. SG·DB 권한·Kafka ACL·Secret·S3 정책은 이번 준비에서 생성하거나 변경하지 않는다.

`runtime.py`는 YAML 파일을 만드는 도구이며 AWS CLI/kubectl을 호출하지 않는다. 기본 출력 12개 객체에는 namespace `spark`, 계정 3개, namespace RBAC, ResourceQuota, 런타임 ConfigMap이 있다. **Pod/Job/NodePool을 기본 출력하지 않는다.**

- `spark-submitter`: 이미지 안의 spark-submit으로 Driver를 제출한다.
- Spark 4.2 NetworkPolicyFeatureStep이 Executor ingress 정책을 생성하므로 submitter에 해당 namespace의 NetworkPolicy create/get/patch/delete 권한이 필요하다. 클라우드 403 확인 후 코드에 추가했으며 아직 클라우드 재검증 전이다.
- `spark-driver`: Executor Pod·Service·ConfigMap을 관리한다.
- `spark-executor`: Kubernetes 관리 권한과 API token 자동 마운트가 없다.
- `airflow-scheduler`: spark namespace에서 제출 Pod/Job 실행·관찰·정리 가능. 실제 DAG는 포함하지 않는다.
- namespace 예산: requests 3CPU/6GiB, limits 4CPU/6GiB, 동시 활성 Pod 4개. 전용 배치는 Executor 초기/최소 1개·최대 2개의 Dynamic Allocation을 켠다. 참고용 공용 배치는 기존 Executor 1개 고정 프로필을 유지한다. 동시 여러 작업을 허용하는 예산이 아니며 DAG 실행 동시성은 별도로 제한해야 한다.

전용/공용 배치는 Driver·Executor·제출기 모두 같은 옵션을 선택해야 한다. namespace 분리만으로 실행 노드가 분리되지는 않으므로 nodeSelector/taint/toleration을 함께 사용한다. RBAC에는 Secret/RBAC/노드 관리 권한이 없지만 Pod 생성자는 해당 namespace의 실행 계정을 선택할 수 있으므로 강한 데이터 격리라고 보지 않는다.

## 로컬 검사·렌더

```powershell
python -m pip install -r infra/platform/spark/requirements.txt
python -m unittest discover -s infra/platform/spark -p 'test_*.py' -v
python infra/platform/spark/runtime.py --output .cache/spark-dedicated-prep.yaml
python infra/platform/spark/runtime.py --placement shared-memory --output .cache/spark-shared-prep.yaml
```

이미지와 진입 파일이 정해진 다음에만 `--include-job --image <repository>@sha256:<digest> --application-file local:///opt/jobs/main.py --run-name <고유 실행명>`을 추가해 제출 Job까지 렌더한다. 이것도 파일 생성만 하며 제출하지 않는다. 이미지는 Spark/Python/Java·실제 코드와 필요한 Hadoop/S3A 의존성을 포함해야 한다. Pod Identity 지원 SDK 버전도 이미지 담당자와 확인한다.

실행 인자는 `--application-arg=--input-root --application-arg=s3://example/input/`처럼 반복해서 전달할 수 있다. 인자는 셸 문자열로 합치지 않는다. 비밀번호·토큰은 인자/렌더 파일에 넣지 말고 별도 Secret 연결로 공급한다.

제출 Job은 Spark가 끝날 때까지 기다린다. 스트리밍이면 이 Pod도 계속 남고 requests를 소비한다. Job TTL은 종료된 제출 Job을 정리할 뿐, Driver Pod와 작업 데이터까지 정리한다고 가정하지 않는다. Airflow 취소/오류 시 고유 실행명으로 Driver를 종료하고 Executor 정리를 확인하는 계약이 필요하다. 업무 S3 데이터를 무조건 지우는 정리 코드는 넣지 않았다.

## 실제 적용 전 받을 것

1. Spark 버전·이미지 digest·이미지 안 진입 파일, 필요한 인자.
2. 배치/스트리밍 여부, Executor 수, 처리 지연 목표, 동시 실행 수.
3. S3 입력·출력·checkpoint 경로와 덮어쓰기/커밋/정리 방식.
4. Driver/Executor별 Pod Identity와 S3 정책. `workload-access.tfvars.example`은 미적용 최소 예시이며 현재 bindings를 대체하면 기존 CDC/Airflow 권한이 삭제될 수 있어 **병합만** 해야 한다. 실제 committer/checkpoint에는 DeleteObject나 endpoint 정책 변경이 추가로 필요할 수 있다. Glue 작업도 별도 확인한다.
5. 두 배치 후보 중 선택과, 공용안을 고르면 Airflow hostname·Kafka PVC·CPU requests 조정/노드 교체 계획.

역할을 만든 것만으로 S3가 연결되거나 기존 Python 코드가 Spark로 실행되는 것은 아니다. 실제 역할/연결/노드/성능 검증은 아직 하지 않았다. 작업 이미지 없이 테스트 데이터를 주입하거나 업무 DAG를 수정하지 않는다.

공식 근거: [Spark Kubernetes 실행](https://spark.apache.org/docs/latest/running-on-kubernetes.html), [Auto Mode NodePool](https://docs.aws.amazon.com/eks/latest/userguide/create-node-pool.html), [도쿄 EC2 가격](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-1/index.json), [도쿄 EKS 가격](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEKS/current/ap-northeast-1/index.json).
