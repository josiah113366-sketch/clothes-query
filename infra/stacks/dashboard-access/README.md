# Dashboard 접근 스택

선행 eks/storage state를 읽어 승인 대시보드 전용 IAM 역할·inline policy·Athena workgroup·Pod Identity association 4개를 관리한다. 새 노드·ALB·S3 버킷·업무 테이블·대시보드 앱은 만들지 않는다. state key는 dashboard-access 전용이며 기존 스택과 공유하지 않는다.

공유 deployment.auto.tfvars.json의 namespace/ServiceAccount/workgroup/결과 경로/1GiB 쿼리 상한을 사용한다. backend 위치는 deployment.backend.hcl이다. init -backend-config=deployment.backend.hcl 후 validate·plan을 확인한다. [연결 안내](../../platform/dashboard-access/README.md)를 따른다.

원본 읽기는 이상 이력·조사 리포트·재처리 기록에만, 업무 쓰기는 reprocess_events/에만 허용한다. 상태값은 IAM으로 제한하지 않는다. 삭제 전 앱 실행 여부와 association 사용을 확인하며 force_destroy=false로 쿼리 기록이 있는 workgroup 삭제를 보호한다.
