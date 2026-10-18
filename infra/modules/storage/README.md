# storage module

state와 분리된 데이터 S3, 버저닝·암호화·공개 차단·TLS 정책를 관리한다.

## 입력과 출력

- 배포 사양: `bucket_name`: 기존 버킷과 충돌하지 않는 승인된 이름. 기존 버킷 재사용은 관리 state 확인과 별도 import 계획이 필요하다.
- 연결 입력: 없음. [호출 스택](../../stacks/storage/main.tf)에서 연결한다.
- 출력: `bucket_name`, `bucket_arn`.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[storage 스택](../../stacks/storage/README.md)에서 실행한다. force_destroy=false, prevent_destroy=true. 버전 및 객체를 자동 만료시키지 않으므로 보관량에 따라 요금이 누적된다. 수명주기는 데이터 보존 합의 후 추가한다.
