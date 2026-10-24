# Gold B 카탈로그 스택

기존 storage state를 읽어 Glue gold_b 데이터베이스 하나만 생성한다. gold-b-access/agent/dashboard 권한 스택과 별도 state key clothes-query/dev/gold-b-catalog/terraform.tfstate를 사용한다. DB의 수명주기를 접근 권한 변경과 분리한다. S3 버킷이나 데이터·테이블은 Terraform으로 관리하지 않는다.

공유 입력과 backend 파일을 사용해 init -backend-config=deployment.backend.hcl, validate, plan을 확인한다. 처음 plan은 Glue DB 생성 1개만 있어야 한다. 이미 DB가 있다면 덮어쓰기·import 없이 소유권을 확인한다. DB는 prevent_destroy로 보호한다.

DB 준비 후 담당자가 확정한 pipelines/gold_b/ddl의 5개 표 정의를 Athena에서 실행한다. database.sql은 제외한다. 컬럼·자료형·파티션·S3 경로를 원문과 대조하며 기존 표가 다르면 ALTER/DROP하지 않고 중단한다. 데이터 INSERT·크롤러·MSCK REPAIR·임의 파티션 등록은 이 작업에 포함하지 않는다. [적용 기록](../../../docs/tasks/infra-gold-b-catalog.md)을 따른다.
