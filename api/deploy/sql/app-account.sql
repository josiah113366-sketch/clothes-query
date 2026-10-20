-- 업무 API(WAS) 전용 DB 계정. 사용자가 마스터 계정으로 RDS의 **postgres DB**에 접속해 한 번 실행한다.
-- (RDS 업무 테이블은 postgres DB에 있다. 로컬 Docker는 clothes DB.)
--
-- psql 15 이상: 환경 변수 API_DB_PASSWORD 에 Secrets Manager 값을 넣고
--   psql -X "host=<RDS 주소> dbname=postgres user=<마스터> sslmode=verify-full sslrootcert=<CA>" -f api/deploy/sql/app-account.sql
-- DBeaver: 아래 BEGIN; ~ COMMIT; 만 붙여 넣고 :'api_password' 자리에 비밀번호 문자열을 넣어 실행한다.
--          실행 후 편집기 내용과 실행 기록을 지우고 저장하지 않는다.
-- 같은 이름의 계정이 있으면 오류로 멈춘다(덮어쓰지 않는다).
\set ON_ERROR_STOP on
\getenv api_password API_DB_PASSWORD
\if :{?api_password}
\else
  \echo 'API_DB_PASSWORD 가 없습니다. 멈춥니다.'
  \quit
\endif

BEGIN;
-- 연결: 풀 최대 10(API_DB_POOL_MAX) + 재시작 겹침 여유
CREATE ROLE clothes_app WITH LOGIN PASSWORD :'api_password' CONNECTION LIMIT 15;
GRANT CONNECT ON DATABASE postgres TO clothes_app;
GRANT USAGE ON SCHEMA public TO clothes_app;
GRANT SELECT, INSERT ON public.members TO clothes_app;
GRANT SELECT, INSERT, UPDATE ON public.orders TO clothes_app;
GRANT SELECT, INSERT ON public.order_items, public.payments TO clothes_app;
GRANT SELECT ON public.product_variant TO clothes_app;
-- members_archive, product_design 은 권한 없음. members UPDATE(탈퇴)는 탈퇴 작업에서 정한다.
COMMIT;

-- 확인
SELECT rolname, rolcanlogin, rolconnlimit FROM pg_roles WHERE rolname = 'clothes_app';
SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) AS privileges
FROM information_schema.role_table_grants
WHERE grantee = 'clothes_app' GROUP BY table_name ORDER BY table_name;

-- 되돌리기 (필요할 때만, API Pod를 먼저 내린 뒤 마스터로 실행)
-- REVOKE ALL ON public.members, public.orders, public.order_items, public.payments, public.product_variant FROM clothes_app;
-- REVOKE USAGE ON SCHEMA public FROM clothes_app;
-- REVOKE CONNECT ON DATABASE postgres FROM clothes_app;
-- DROP ROLE clothes_app;
