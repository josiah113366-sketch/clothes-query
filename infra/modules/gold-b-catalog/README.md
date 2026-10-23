# Gold B Glue DB

기존 데이터 S3의 gold_b/를 가리키는 Glue 데이터베이스 하나를 관리한다. 서버·버킷·객체·표·뷰·크롤러·권한을 만들지 않는다. 표 정의는 pipelines/gold_b/ddl 담당자가 소유하며 database.sql은 실행하지 않는다. prevent_destroy로 실수로 DB를 지우는 계획을 차단한다. [독립 스택](../../stacks/gold-b-catalog/README.md)을 사용한다.
