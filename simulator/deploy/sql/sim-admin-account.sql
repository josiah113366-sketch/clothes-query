-- 시뮬레이터 컨트롤러의 데이터 오염 전용 DB 계정 (docs/design/api.md 11절 "결정").
-- 사용자가 마스터 계정으로 RDS의 **postgres DB**에 접속해 한 번 실행한다. 앱 계정(clothes_app)·CDC 계정과 나눈다.
--
-- DBeaver: 아래 BEGIN; ~ COMMIT; 만 붙여 넣고 '여기에_붙여넣기' 안쪽을 Secrets Manager 에서 만든 비밀번호로 바꿔 실행한다.
--          실행 후 편집기 내용과 실행 기록을 지우고 저장하지 않는다.
-- 같은 이름의 계정이 있으면 오류로 멈춘다(덮어쓰지 않는다).

BEGIN;
-- 컨트롤러 하나만 쓰고, 오염은 한 번에 끝나는 짧은 트랜잭션이다
CREATE ROLE clothes_sim_admin WITH LOGIN PASSWORD '여기에_붙여넣기' CONNECTION LIMIT 3;
GRANT CONNECT ON DATABASE postgres TO clothes_sim_admin;
GRANT USAGE ON SCHEMA public TO clothes_sim_admin;
-- ORDER_TOTAL_MISMATCH: 결제 끝난 주문 골라 total_amount 를 바꾼다 (simulator/src/sim/controller/pollution.py)
GRANT SELECT, UPDATE ON public.orders TO clothes_sim_admin;
-- 중복 결제 오염: SUCCESS 결제를 골라 같은 내용으로 한 줄 더 넣는다
GRANT SELECT, INSERT ON public.payments TO clothes_sim_admin;
-- members, order_items, product_* 는 권한 없음
COMMIT;

-- 확인
SELECT rolname, rolcanlogin, rolconnlimit FROM pg_roles WHERE rolname = 'clothes_sim_admin';
SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) AS privileges
FROM information_schema.role_table_grants
WHERE grantee = 'clothes_sim_admin' GROUP BY table_name ORDER BY table_name;

-- 되돌리기 (필요할 때만, ECS 컨트롤러를 먼저 멈춘 뒤 마스터로 실행)
-- REVOKE ALL ON public.orders, public.payments FROM clothes_sim_admin;
-- REVOKE USAGE ON SCHEMA public FROM clothes_sim_admin;
-- REVOKE CONNECT ON DATABASE postgres FROM clothes_sim_admin;
-- DROP ROLE clothes_sim_admin;
