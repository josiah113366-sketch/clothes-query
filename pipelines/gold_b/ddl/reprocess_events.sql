-- ⑤ 재처리 단계 하나 = 한 줄 (은서 + 주현 공동). 고치지 않고 단계마다 추가한다.
-- 현재 상태는 request_id별 마지막 줄의 step. 양이 적어 시간 폴더로 나누지 않는다.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_b.reprocess_events (
  request_id        STRING    COMMENT '재처리 요청 번호',
  step              STRING    COMMENT 'REQUESTED, APPROVED, REJECTED, STARTED, LEDGER_REPLACED, FAILED, REDETECTED, VERIFIED',
  at                TIMESTAMP COMMENT '이 단계를 기록한 시각 (UTC)',
  actor             STRING    COMMENT '누가 (역할 또는 잡 이름)',
  reason            STRING    COMMENT '왜',
  window_start      TIMESTAMP COMMENT '이 줄이 가리키는 시간대 시작 (REQUESTED는 승인 범위, LEDGER_REPLACED는 실제 교체한 시간 폴더)',
  window_end        TIMESTAMP COMMENT '이 줄이 가리키는 시간대 끝',
  rule_version      STRING    COMMENT '다시 계산에 쓴 형식 검사 규칙 버전',
  source            STRING    COMMENT '다시 읽은 곳 (KAFKA, BRONZE)',
  attempt           INT       COMMENT '몇 번째 시도',
  parent_request_id STRING    COMMENT '이전 요청 (재시도 추적)',
  detail            STRING    COMMENT '실패 이유, 교체한 폴더 목록 같은 짧은 설명'
)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_b/reprocess_events/'
TBLPROPERTIES (
  'parquet.compression' = 'SNAPPY'
);
