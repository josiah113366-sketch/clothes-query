# ecr module

WEB/WAS용 ECR 두 개와 선택적 Connect 저장소, immutable tag·scan on push를 관리한다.

`enable_gold_b_repository=true`는 `<name>/gold-b` 저장소만 추가한다. 기존 Spark publisher 정책은 두 저장소 범위를 유지하고 Gold B publisher를 추측하지 않는다.

`enable_spark_repositories=true`는 기존 저장소를 보존하고 spark-base/silver-gold-a 두 저장소를 추가한다. spark_publisher_user_arns의 같은 계정 IAM 사용자에게 해당 두 저장소 push/pull과 registry token 발급 정책을 추가한다. 토큰 발급은 AWS API 특성상 Resource=*이고 나머지 권한은 두 저장소에 제한한다. 기존 사용자 정책을 회수하거나 사용자의 전체 권한을 축소하는 작업은 아니다. 새 역할 ARN으로 교체할 때는 사용자 정책 연결 방식과 구분해 설계한다.

## 입력과 출력

- 배포 사양: 추가 앱별 필수 입력 없음. 이름은 clothes-query-dev/web 및 clothes-query-dev/was다.
- 연결 입력: `name`. [호출 스택](../../stacks/ecr/main.tf)에서 연결한다.
- `enable_connect_repository=false`가 기본이다. true이면 기존 WEB/WAS 주소를 유지하고 `<name>/connect`만 추가한다.
- 출력: 민감한 `repository_urls`, `repository_arns`, 선택적 `connect_publisher_policy` JSON. 정책 출력은 IAM 역할/정책을 생성하거나 연결하지 않는다.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[ecr 스택](../../stacks/ecr/README.md)에서 실행한다. force_delete=false. 롤백 이미지가 자동 제거되지 않도록 lifecycle은 아직 넣지 않았다. 이미지가 있는 저장소 삭제에는 별도 정리가 필요하다.
