-- 이상 "현재 보기": 같은 이상(anomaly_id)이 회차마다 여러 줄로 쌓이므로, 가장 최근 줄 하나만 보여 준다.
-- 대시보드 이상탐지 화면과 조사 도구(list_anomalies)가 쓴다. 최근 것은 detected_at, 같으면 run_id가 큰 것.
-- 해결 여부는 이 뷰가 아니라 reprocess_events의 VERIFIED 줄 detail(result)에 있다.
CREATE OR REPLACE VIEW gold_b.anomaly_current AS
SELECT run_id, anomaly_id, rule_id, rule_version, anomaly_type, source_table, window_start, window_end,
       scope_type, scope_key, metric, observed_value, baseline_value, baseline_kind, sample_size,
       episode_start, episode_end, evidence_ref, status, detected_at
FROM (
  SELECT a.*,
         ROW_NUMBER() OVER (PARTITION BY anomaly_id ORDER BY detected_at DESC, run_id DESC) AS rn
  FROM gold_b.anomaly a
)
WHERE rn = 1;
