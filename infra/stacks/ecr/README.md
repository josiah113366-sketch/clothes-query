# ecr stack

WEB/WAS용 ECR 두 개, immutable tag·scan on push.

- 선행: 기존 bootstrap.
- backend key: `clothes-query/dev/ecr/terraform.tfstate`.
- 입력: 추가 앱별 필수 입력 없음. 이름은 clothes-query-dev/web 및 clothes-query-dev/was다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다.
- 출력: `repository_urls`.

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

force_delete=false. 롤백 이미지가 자동 제거되지 않도록 lifecycle은 아직 넣지 않았다. 이미지가 있는 저장소 삭제에는 별도 정리가 필요하다.
