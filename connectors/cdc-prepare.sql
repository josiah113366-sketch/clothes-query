-- CDC 전용 계정과 publication. 사용자가 마스터 계정으로 한 번 실행한다 (Claude는 실행하지 않는다).
-- RDS 의 업무 테이블은 postgres DB 에 있다 (로컬 Docker 는 clothes DB). 반드시 RDS 의 postgres DB 에 접속해 실행한다.
-- 실행: psql -X "host=<RDS 주소> dbname=postgres user=<마스터> sslmode=verify-full sslrootcert=<RDS CA 번들>" -f connectors/cdc-prepare.sql
-- 비밀번호는 이 파일과 명령행에 쓰지 않는다. 실행 전에 환경 변수 CDC_DB_PASSWORD 에 넣는다 (Secrets Manager 에 저장한 값).
-- 같은 이름의 계정이나 publication 이 이미 있으면 오류로 멈춘다 (덮어쓰지 않는다).
\set ON_ERROR_STOP on
\getenv cdc_password CDC_DB_PASSWORD
\if :{?cdc_password}
\else
  \echo 'CDC_DB_PASSWORD 가 없습니다. 멈춥니다.'
  \quit
\endif

BEGIN;
-- 연결: 복제 1 + 메타데이터 조회 1 + heartbeat.action.query 1, 재시작 겹침 여유 2.
CREATE ROLE clothes_cdc WITH LOGIN PASSWORD :'cdc_password' CONNECTION LIMIT 5;
-- RDS 에서는 REPLICATION 속성 대신 이 역할로 복제 연결(slot 생성·읽기) 권한을 준다.
GRANT rds_replication TO clothes_cdc;
GRANT CONNECT ON DATABASE postgres TO clothes_cdc;
GRANT USAGE ON SCHEMA public TO clothes_cdc;
-- snapshot 은 SELECT 로 읽는다. 회원은 PII 없는 10컬럼만 컬럼 단위로 허용한다.
GRANT SELECT (member_id, signup_at, signup_channel, gender, age_band, region_sigungu,
              marketing_consent, status, withdrawn_at, created_at) ON public.members TO clothes_cdc;
GRANT SELECT ON public.orders, public.order_items, public.payments TO clothes_cdc;
-- publication 은 테이블 소유자(마스터)만 만들 수 있다. members_archive, product_* 는 넣지 않는다.
CREATE PUBLICATION cdc_pub FOR TABLE public.members, public.orders, public.order_items, public.payments;
COMMIT;

-- 확인
SELECT rolname, rolcanlogin, rolconnlimit FROM pg_roles WHERE rolname = 'clothes_cdc';
SELECT pubname, schemaname, tablename FROM pg_publication_tables WHERE pubname = 'cdc_pub' ORDER BY tablename;

-- 되돌리기 (필요할 때만, 커넥터를 먼저 지우고 slot 이 inactive 인지 확인한 뒤 마스터로 실행한다)
-- SELECT pg_drop_replication_slot('cdc_slot');
-- DROP PUBLICATION cdc_pub;
-- REVOKE ALL ON public.members, public.orders, public.order_items, public.payments FROM clothes_cdc;
-- REVOKE USAGE ON SCHEMA public FROM clothes_cdc;
-- REVOKE CONNECT ON DATABASE postgres FROM clothes_cdc;
-- REVOKE rds_replication FROM clothes_cdc;
-- DROP ROLE clothes_cdc;
