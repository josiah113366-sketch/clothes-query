# ecr stack

WEB/WAS용 ECR 두 개와 선택적 Connect 저장소, immutable tag·scan on push.

2026-10-18 사용자 승인으로 Connect 저장소를 추가하고 PostgreSQL CDC/S3 Sink 플러그인 이미지의 실제 push·EKS pull을 확인했다. 현재 저장소3개이며 비공개 실배포 입력의 enable_connect_repository=true를 유지한다. 시험 데이터가 들어 있지 않은 이미지는 재사용을 위해 남겼다. 시험 Connect 런타임은 제거했다. [시험 결과](../../../docs/tasks/infra-pipeline-smoke.md).

- 선행: 기존 bootstrap.
- backend key: `clothes-query/dev/ecr/terraform.tfstate`.
- 입력: 추가 앱별 필수 입력 없음. 이름은 clothes-query-dev/web 및 clothes-query-dev/was다.
- `enable_connect_repository=false`가 기본이다. 비공개 tfvars에 true를 명시하면 `clothes-query-dev/connect`만 추가한다. 기존 WEB/WAS의 Terraform 주소와 이름은 유지한다. 실제 plan에서 교체/삭제가 없는지 확인한다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다.
- 출력: `repository_urls`, `repository_arns`, `connect_publisher_policy` (모두 sensitive).

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

force_delete=false. 롤백 이미지가 자동 제거되지 않도록 lifecycle은 아직 넣지 않았다. 이미지가 있는 저장소 삭제에는 별도 정리가 필요하다.

Connect 활성 후 false로 되돌리면 해당 저장소 삭제 계획이므로 단순한 비활성 스위치로 사용하지 않는다. 별도 IAM publisher identity·CI trust는 아직 정하지 않았다. `connect_publisher_policy`는 선택한 identity에 검토 후 연결할 최소 정책 **문서 출력**이며 현재 권한을 부여하지 않는다. 업로드 작업은 Connect repository ARN에만 허용하고, 리소스 단위 권한을 지원하지 않는 `GetAuthorizationToken`만 `Resource="*"`를 쓴다. [AWS 공식 push 정책](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html)

같은 계정 EKS 노드에는 기존 `AmazonEC2ContainerRegistryPullOnly`가 연결되어 있으므로 Connect Pod에 publisher IAM/Pod Identity를 추가하지 않는다. 노드의 image pull과 Pod의 데이터 접근 권한은 서로 다르다. 다른 계정/네트워크의 pull은 별도 검토 대상이다.

배포 환경에서 저장소 생성과 승인된 push 이후 반환된 레지스트리 digest를 Kafka chart의 `connect.image`에 넣는다. 로컬 이미지 ID를 대신 사용하지 않는다. 2026-10-18 시험은 실제 로그인·push/digest 고정·EKS pull을 수행했고 전용 임시 Docker 로그인 토큰은 제거했다. 이미지를 보관하면 저장 공간 비용이 발생한다.
