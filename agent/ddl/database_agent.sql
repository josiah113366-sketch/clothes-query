-- 조사 에이전트 Glue 데이터베이스. 인프라 담당이 이미 만들어 두었다면 건너뛴다(IF NOT EXISTS라서 다시 실행해도 안전).
-- 조사 리포트와 실행 기록은 gold_b 밖에 둔다 (조사만 하고 재처리로 이어지지 않는 경우가 있어서, Gold B 담당 권장).
CREATE DATABASE IF NOT EXISTS agent
COMMENT '조사 에이전트의 원인 리포트와 실행 기록 (agent/ddl)'
LOCATION 's3://clothes-query-datalake/agent/';
