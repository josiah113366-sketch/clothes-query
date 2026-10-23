# Silver·Gold A 연결 준비

**최신 상태(2026-10-23, #82 머지 후)는 [연결 준비 결과](silver-gold-a-ready.md)를 따른다.** 아래는 경로 확정 전 준비 이력이다. namespace·고정 입력·상품 기준정보 중 확인된 항목과 현재 검토용 권한은 최신 문서에 정리했다. 준비 완료와 실제 AWS 적용은 구분한다.

동료의 상세 명세를 [계약 예시](silver-gold-a.example.yaml)에 반영했고, [전달 문안](message-to-pipelines.md)을 준비했다. 출력을 제안 경로로 코드에 준비했으며 실제 권한 적용은 하지 않았다. 실행 요청 JSON prefix와 namespace·계정은 아직 미정이다.

## 경로별 권한 준비 도구

상위 prepare_trade_access.py는 알려진 경로의 로컬 계획만 출력한다. 기본 실행은 AWS·kubectl·Terraform을 호출하지 않고 IAM 리소스도 만들지 않는다.

```powershell
python infra/platform/spark/prepare_trade_access.py --plan-output .cache/silver-gold-a-access-plan.json
```

Bronze 주문·주문상품·결제는 GetObject, Silver·Gold A 거래 출력은 GetObject/PutObject만 준비한다. 실행 기록은 각 출력 루트의 manifest/completed/current에 포함하며 별도 기록 루트는 추측하지 않는다. 삭제·AbortMultipartUpload·ListMultipartUploadParts·Glue 권한은 아직 추가하지 않는다. 따라서 커미터를 포함한 완성 작업 정책이 아니다. 기본 이미지의 S3A JAR 포함만으로 실제 multipart 업로드/정리가 검증된 것도 아니다.

namespace·service_account_prefix·config_request_prefix_uri를 채운 별도 계약 파일이 있으면 --existing-vars와 --bindings-output으로 기존 workload-access 입력에 Driver/Executor binding을 병합한 검토 파일을 만들 수 있다. 기존 파일을 직접 덮어쓰지 않고, 기존 binding 변경·동일 계정의 중복 연결·넓은/보호 경로·다른 버킷은 거부한다. 기존 stack 입력은 보존하고 제출기에는 S3 역할을 추가하지 않는다. 이름과 config prefix가 없으면 출력 생성을 거부한다. 생성 성공도 배포 준비 완료를 뜻하지 않으며 실제 이미지·커미터·S3 endpoint 정책과 기존 IAM 정책의 합산 효과를 확인해야 한다. 이 도구는 명시적 Deny 정책을 추가하지 않으며 기존 역할/개발자 권한을 축소하지 않는다.

이 폴더는 전달받을 정보를 정리한다. 업무 DAG·Spark 변환 코드를 만들지 않고 AWS/Kubernetes를 변경하지 않는다. [silver-gold-a.example.yaml](silver-gold-a.example.yaml)의 confirmed_runtime은 사용자가 선택한 실행 기반이고 pending은 팀원과 확정할 값이다. colleague_proposal은 아직 인프라 확정값이 아닌 동료 제안이다. YAML을 채워도 자동 배포되거나 권한이 생기지 않는다.

## 경로 확정 전 준비한 것

- 실행 기반: spark-submit, Spark 4.2.0, t3a.large 한 대분, Driver 1개·Executor 1~2개. 기본 이미지와 커넥터는 로컬 빌드/합성 실행 검증을 통과했다. 팀원이 쓸 영구 ECR/digest는 아직 제공하지 않는다.
- 기본 이미지에서 실제 확인한 Python은 **3.10.12**다. 팀원이 요구하는 버전·패키지와 호환되는지 확인한 뒤 사용한다. 다른 Python 버전이 필요하면 이미지 재구성이 필요하다.
- 이름 변경 대응: 상위 runtime.py에서 namespace·ServiceAccount/Role/ConfigMap 접두사·노드풀을 입력으로 받는다. 기본값은 기존 spark 구성이며 pipelines 또는 silver-gold-a를 확정하지 않는다.
- 계정 역할: `<prefix>-submitter`, `<prefix>-driver`, `<prefix>-executor`. 동료가 제안한 단일 ServiceAccount를 그대로 확정한 것이 아니다. S3를 읽는 Driver/Executor의 Pod Identity는 경로 확정 후 별도 연결한다.
- Airflow 역할은 대상 namespace의 Pod/Job 실행·상태/로그 조회·정리에 한정한다. scheduler 계정 자체는 기존 airflow/airflow-scheduler를 사용한다.

아래는 **파일 렌더 예시**다. 예시 이름은 실제 배포 결정이 아니며 명령은 클러스터에 접속하지 않는다.

```powershell
python infra/platform/spark/runtime.py `
  --namespace example-jobs --name-prefix example-work `
  --node-pool example-spark-pool --output .cache/example-spark.yaml
```

기본 출력에는 Namespace·RBAC·ResourceQuota·ConfigMap이 포함되지만 실행 Pod/Job은 없다. 같은 옵션을 --include-job 렌더에도 사용한다. **공유 namespace에 적용할 때 Namespace/ResourceQuota 소유자와 기존 예산을 먼저 검토**한다. 접두사가 달라도 ResourceQuota는 namespace 전체에 적용되며 독립 작업 예산이 되지 않는다. 같은 namespace의 Pod 생성 권한은 다른 ServiceAccount를 사용할 수 있으므로, 계정/역할 분리만으로 강한 보안 격리를 보장하지 않는다.

## 정보를 받으면 연결할 순서

1. namespace 공유·계정 이름, 정확한 읽기/쓰기/삭제 prefix와 Glue 필요 여부를 확정한다. ground_truth 접근은 추가하지 않는다. ListBucket은 prefix 조건, 객체 권한은 해당 경로로 제한한다. 쓰기 권한은 기존 파일 덮어쓰기도 가능하므로 재실행 계약을 확인한다.
2. 거래 magic committer 권한은 새 spark-access 스택으로 분리한다. 기존 workload-access bindings와 동일한 ServiceAccount를 중복 관리하지 않는다. prepare_trade_access.py의 기존 병합 출력은 Get/Put 검토용이며 magic 삭제·multipart를 포함한 최종 실행 정책이 아니다. 새 map으로 기존 CDC·Airflow 연결을 덮어쓰지 않는다. ECR/push 주체 ARN과 이미지 발행 절차를 맞춘다.
3. 실제 이미지 digest·진입 파일·인자를 받아 제출 Job을 렌더한다. 입력값이 미정인 상태에서 업무 실행 파일이나 권한을 추측해 채우지 않는다.
4. Airflow의 현재 DAG 공급 설정을 다시 확인하고 소스 경로/갱신 절차를 확정한다. 이전 대화의 Git bundle 안내만으로 현재 적용 상태라고 단정하지 않는다.
5. 동료가 작성한 DAG에서 먼저 Silver 성공 확인 후 Gold A를 실행한다. 순서·중복 실행 방지·동시성·완료 조건은 DAG 담당자가 구현하고, 인프라는 실행/취소 시 Driver·Executor 정리를 함께 검증한다. Job TTL은 업무 데이터 정리나 Driver 종료를 보장하지 않는다.

## 로그 확인 계약

제출기: `kubectl -n <namespace> logs job/<run-name>`

Driver: `kubectl -n <namespace> logs <run-name>-driver`

Executor 목록: `kubectl -n <namespace> get pods -l spark-role=executor`

동시에 여러 작업이 있다면 Spark application ID 라벨로 추가 필터한다. 현재 확인한 것은 Kubernetes Pod 로그다. Spark event log와 장기 S3 로그의 경로/권한은 미정이며 Airflow task 로그와 Spark 내부 로그는 서로 다르다. 업무 패키지의 Python 3.10.12 호환성은 팀원 확인이 필요하다.

## 2026-10-23 받은 명세 반영

- 계정 이름은 silver-gold-a-submitter / silver-gold-a-driver / silver-gold-a-executor로 준비했다. namespace는 Gold B 담당 확인 전 null이다.
- pipelines namespace를 공유한다면 runtime.py --existing-namespace 옵션으로 Namespace/ResourceQuota 소유권을 건드리지 않는 10개 객체를 검토한다. 이 렌더 자체는 namespace 공유를 승인하거나 리소스를 적용하지 않는다.
- 요청·입력 manifest 경로는 pipelines/requests/와 pipelines/input-manifests/ 기준이다. S3는 폴더 생성이 필요 없으므로 빈 placeholder를 쓰지 않는다. 정확한 요청 객체는 전달 대기다.
- 최초 S3 정책은 거래 Bronze 3개와 silver/runtime/trade/, gold_a/runtime/trade/만 준비한다. funnels/reviews가 코드에 있다는 이유로 접근 범위를 확장하지 않는다. 상품 기준정보 경로도 미정이다.
- DeleteObject는 각 출력의 runs/<run_id>/<dataset>/__magic_job-*/ 작업 객체로 제한한다. 정상 결과·manifest·완료 기록 삭제는 허용하지 않는다. AbortMultipartUpload와 ListMultipartUploadParts는 출력 최종 객체 경로에도 허용한다.
- S3 endpoint는 IAM과 별개다. network-magic.tfvars.example은 기존 작업을 보존해 추가할 전송 권한 검토안이고 자동 적용 파일이 아니다. 실제 AWS 검증 전 최종 committer 설정과 객체 경로를 맞춰야 한다.
- fs.s3a.committer.abort.pending.uploads=true는 목적지 아래 다른 진행 중 업로드도 조회/중단할 수 있다. 실제 업무 코드 확인 전 bucket multipart metadata listing은 기본 비활성이다. 설정과 필요 권한을 담당자에게 요청한다.
- 908c252는 현재 원격에 없어 소스 검증을 하지 못했다. 로컬 패키지/기본 이미지 검증과 업무 검증은 구분한다. 최초 입력 목록·상품 스냅샷·기대값·R6 completed_at/Glue 공개 명세도 대기다.

공식 참고: [Hadoop 3.5 S3A committers](https://hadoop.apache.org/docs/r3.5.0/hadoop-aws/tools/hadoop-aws/committers.html), [S3A 권한 설명](https://apache.github.io/hadoop/hadoop-aws/tools/hadoop-aws/assumed_roles.html). Python 패키지 최소 버전은 [PyArrow 25.0.1](https://pypi.org/project/pyarrow/25.0.1/)·[boto3 1.43.71](https://pypi.org/project/boto3/1.43.71/)의 Python>=3.10과 실제 이미지 실행을 확인했다.
