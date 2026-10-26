# Dashboard 접근 스택

공유 설정의 `enable_gold_a_reads=true`는 Gold A 지표·보류 조회용 읽기 정책을 추가한다. 기존 역할·workgroup·승인 쓰기는 유지한다. [검증과 화면 설정 반영 절차](../../../docs/tasks/infra-dashboard-gold-a-read.md)를 따른다.

선행 eks/storage state를 읽어 승인 대시보드 전용 IAM 역할·inline policy·Athena workgroup·Pod Identity association 4개를 관리한다. 새 노드·ALB·S3 버킷·업무 테이블·대시보드 앱은 만들지 않는다. state key는 dashboard-access 전용이며 기존 스택과 공유하지 않는다.

공유 deployment.auto.tfvars.json의 namespace/ServiceAccount/workgroup/결과 경로/1GiB 쿼리 상한을 사용한다. backend 위치는 deployment.backend.hcl이다. init -backend-config=deployment.backend.hcl 후 validate·plan을 확인한다. [연결 안내](../../platform/dashboard-access/README.md)를 따른다.

원본 읽기는 이상 이력·조사 리포트·재처리 기록에만, 업무 쓰기는 reprocess_events/에만 허용한다. 상태값은 IAM으로 제한하지 않는다. 삭제 전 앱 실행 여부와 association 사용을 확인하며 force_destroy=false로 쿼리 기록이 있는 workgroup 삭제를 보호한다.

## Gold A 시연 근거 읽기

`gold-a-demo-evidence-read-only`는 `enable_gold_a_reads=true`일 때 기존 대시보드 역할에만 추가되는 별도 inline policy다. checkpoint의 검증 완료 tip·고정 manifest·완료 기록·inventory에 `s3:GetObject`만 준다. 앱은 정확한 키를 GetObject하므로 새 ListBucket 권한은 필요 없다. 기존 Athena 지표 조회용 prefix 제한 ListBucket은 유지한다. 업무 쓰기·checkpoint 변경·Gold B·Spark·Airflow 역할과 기존 공통 정책은 변경하지 않는다.

내일 적용 순서와 검증은 [작업 기록](../../../docs/tasks/infra-dashboard-gold-demo-read.md)을 따른다. 이 IAM PR을 먼저 승인·머지하고 최신 main에서 plan/apply한 뒤, 대시보드 앱 PR을 승인·머지한다. 앱 PR 머지는 기존 CI/CD의 운영 이미지 빌드·배포를 자동 시작하므로 IAM 적용 전에 머지하지 않는다.
