-- Gold B Glue 데이터베이스. Glue를 Terraform으로 관리하기로 하면 이 파일 대신 그쪽을 따른다 (재영 님 확인).
CREATE DATABASE IF NOT EXISTS gold_b
COMMENT 'Gold B 관제용 원장과 정리 뷰 (docs/design/gold-b/README.md)'
LOCATION 's3://clothes-query-datalake/gold_b/';
