# ecr module

WEB/WAS용 ECR 두 개, immutable tag·scan on push를 관리한다.

## 입력과 출력

- 배포 사양: 추가 앱별 필수 입력 없음. 이름은 clothes-query-dev/web 및 clothes-query-dev/was다.
- 연결 입력: `name`. [호출 스택](../../stacks/ecr/main.tf)에서 연결한다.
- 출력: `repository_urls`.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[ecr 스택](../../stacks/ecr/README.md)에서 실행한다. force_delete=false. 롤백 이미지가 자동 제거되지 않도록 lifecycle은 아직 넣지 않았다. 이미지가 있는 저장소 삭제에는 별도 정리가 필요하다.
