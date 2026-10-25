# Gold B 시나리오·재처리 시연 점검표

> 상태: **제안** (2026-10-25, `pipelines/gold-b-ops-fixes`). 사건을 거는 법과 판정 기준은 [이상 이력·정답표 설계](../agent/anomaly-answer-key.md)와 [시뮬레이터 컨트롤러](../../tasks/sim-controller.md)를 따른다. 이 문서는 사건마다 **무엇을 걸고, 어느 층에서 무엇이 보여야 하는지**를 한곳에 모은 확인 순서다. 기준값이 바뀌면 원래 문서가 우선이다.

시나리오 정의는 2026-10-23에 바뀌었다. **시나리오 2의 채점 사건은 S3 Sink 정지**(`SINK_PAUSE`)다. 폭주 모드로는 Sink가 다 소화해서 지연이 생기지 않는다. **시나리오 3(데이터 오염)은 형식이 깨진 메시지가 아니라** DB에 넣은 업무 규칙 위반 행이다. 성공 결제 중복은 R5, 주문 총액 불일치는 R6(Silver)이 잡는다. 형식이 깨진 메시지(R4, `malformed_events`)를 넣는 사건은 없어서 시연·채점 대상이 아니다.

## 시연 전에 준비할 것

| 항목 | 확인 방법 | 담당 |
|---|---|---|
| 적재 잡이 Kafka를 따라잡음 | 최근 묶음 로그가 분당 수천 건 이하(2만 건 꽉 차지 않음), 아래 SQL ①의 `newest_kafka_ts`가 1~2분 안 | 재영 님·은서 |
| 지연 수집기가 1분마다 기록 | 아래 SQL ②에서 분마다 15줄(토픽 5 × 파티션 3), `connector_state` RUNNING | 재영 님 |
| 판정 DAG가 5분마다 돔 | `gold_b.detection_runs`에 5분마다 줄 | 주현 님 |
| 재처리 DAG `gold_b_reprocess`가 켜짐 | Airflow에서 켜짐(꺼져 있으면 승인한 재처리가 시작되지 않음) | 재영 님 |
| 대시보드 역할의 결제 뷰 읽기 | 결제 관제 화면 아래 "※ 현재는 더미 데이터입니다"가 없음 (`payment_states`·`payment_attempts`의 `glue:GetTable`) | 재영 님 |
| 시연 시각 | 일상 모드 저녁 피크(한국 18~24시). 새벽은 주문이 적어 R1이 늦다 | 성철 님 |

시각은 원장·판정 모두 **UTC**다. 대시보드는 KST로 바꿔 보여 준다. 아래 SQL의 `<…>`는 그때 값으로 바꾼다.

## 시나리오 1: PG 장애 (R1)

**거는 법:** `sim controller pg-outage --pg PG_B --extra-fail 0.85 --minutes 10` (컨트롤러 화면의 PG 장애 버튼과 같음). PG_B의 실패율이 0.85만큼 더해져 10분 이어진다.

| 층 | 보여야 하는 것 | 언제까지 |
|---|---|---|
| 결제 원장 ① | PG_B의 `FAILED`가 늘고 실패 코드가 PG 원인(`PG_TIMEOUT`·`PG_ERROR`)이다. PG_A와 고객 원인 실패(잔액·한도·거절)는 평소대로 | 1~2분 안 (적재 1분 주기) |
| 뷰 `payment_attempts` | PG_B의 `failure_cause = 'PG'` 비율이 20%를 넘는다 (SQL ③) | 같음 |
| 판정 | `gold_b.anomaly`에 `R1_PG_FAILURES`, 종류 `PG_FAILURE_SPIKE`, 대상 `pg = PG_B` (SQL ⑥) | 시작 뒤 **15분** 안 (허용 지연) |
| 대시보드 결제 관제 | "PG별 PG 원인 실패 비율" 선에서 PG_B만 튀고, 게이지가 빨강(15% 이상), 원인별 건수에서 PG_B의 PG 칸이 커짐 | 화면 새로 고침(캐시 1~2분) |
| 조사·승인 | 리포트 결론이 "결제 층의 실제 PG 장애, 데이터 문제 아님, 재처리 권하지 않음" | 조사 DAG 주기 |
| 끝난 뒤 | 10분 뒤 PG_B 비율이 평소(약 1%)로 돌아오고 새 R1 이상이 더 생기지 않는다 | 끝 + 15분 |

**안 될 때:** 결제 관제가 더미면 뷰 권한부터 본다. 원장에 실패가 안 늘면 시뮬레이터 제어 파일(`pg_extra_fail`)과 적재 잡 로그를 본다. 원장은 맞는데 R1이 없으면 판정 잡의 3분 대기(비율 규칙)와 순찰 기록을 본다.

## 시나리오 2: S3 Sink 정지 (R3)

**거는 법** (컨트롤러는 기록만 남기고, 정지·재개는 사람이 한다):

```bash
sim controller sink-pause --minutes 25
kubectl patch kafkaconnector bronze-s3-sink-v2 -n kafka --type merge -p '{"spec":{"state":"paused"}}'
# 25분쯤 뒤
kubectl patch kafkaconnector bronze-s3-sink-v2 -n kafka --type merge -p '{"spec":{"state":"running"}}'
sim controller end
```

| 층 | 보여야 하는 것 | 언제까지 |
|---|---|---|
| 지연 기록 ③ | 모든 토픽의 `lag_msgs`가 계속 늘고, `lag_sec`이 900초 톱니를 넘어 1,200초 이상으로 오른다. `connector_state`가 `PAUSED` (SQL ②) | 정지 뒤 1분부터. 1,200초는 정지 시점에 따라 5~20분 |
| 유입 ② | `topic_messages`의 분당 건수는 **평소대로**다 (SQL ④). 유입은 그대로인데 지연만 커지면 폭주가 아니라 Bronze 적재 자체의 문제다 | 같음 |
| Gold B 적재 | 영향 없음. 적재 잡은 Kafka를 직접 읽는다 | - |
| 판정 | `R3_BRONZE_LAG`, 종류 `BRONZE_LAG_SPIKE`, 모든 토픽 | 정지 뒤 **30분**(권장 35분) 안. 발표 중에는 미리 걸어 두는 것이 현실적이다 |
| 대시보드 파이프라인 상태 > 지연·점검 | 지연 선이 점선 경고(1,020초)를 넘고, "확인할 토픽" 표에 `PAUSED` 토픽이 보인다. 토픽별 유입 그래프는 평평하다 | 화면 새로 고침 |
| 재개 뒤 | 다음 파일 전환(최대 15분) 안에 `lag_msgs`가 줄고 톱니 모양으로 돌아온다. `connector_state` RUNNING | 재개 + 15분 |

**참고: 폭주 모드** (`sim controller mode burst`, 15분 뒤 자동 복귀, 채점 안 함): 유입 ②가 크게 늘지만 지연 ③은 톱니 그대로여야 한다. "지연 평소·유입 증가 = 잘 처리 중(이상 아님)"을 보여 줄 때 쓴다. R3이 생기면 오탐이다.

## 시나리오 3: 데이터 오염 - 성공 결제 중복 (R5)

**거는 법:** `sim controller pollution --kind DUPLICATE_SUCCESS_PAYMENT --count 5`. 성공 결제가 있는 최근 주문 5건에 `SUCCESS` 결제를 한 건씩 더 넣는다. 새 행의 `completed_at`은 기존 성공 결제의 +2초라 **과거 시각**일 수 있다. 즉시 끝나며(`ended_by: complete`), 정답표 끝 기록의 `result.order_ids`에 주문 번호가 남는다.

| 층 | 보여야 하는 것 | 언제까지 |
|---|---|---|
| 결제 원장 ① | 새 결제 5줄(`cdc_op` c). `loaded_at`은 지금이고 시간 폴더는 **원래 결제 시각** 폴더다 (과거 날짜 폴더일 수 있음) | 1~2분 안 |
| 뷰 `payment_attempts` | 그 주문들의 `SUCCESS`가 2건 (SQL ⑤). 결과 주문 번호 = 정답표 `order_ids` | 같음 |
| 판정 | `R5_DUPLICATE_SUCCESS`, 종류 `DUPLICATE_SUCCESS_PAYMENT`, 근거의 `sample_order_ids`가 정답 주문과 겹침 | 주입 뒤 **10분** 안 |
| 대시보드 결제 관제 | "성공 결제가 2건 이상인 주문" 칸에 그 주문들 (최근 적재 기준, `dashboard/gold-b-scenarios`) | 화면 새로 고침 |
| 형식 오류 화면 | **변화 없음**. 형식은 맞는 데이터다 | - |
| 조사·승인 | 승인 화면이 "재처리로 해결되지 않을 수 있음"(`UNFIXABLE_BY_REPROCESS`)을 보인다. 재처리해도 원본 DB가 그대로라 재판정은 `STILL_OPEN` | - |

**주문 총액 불일치**(`--kind ORDER_TOTAL_MISMATCH`)는 Gold B 원장에 주문 금액이 없어 Gold B로는 보이지 않는다. Silver 품질 결과와 R6이 맡고, Silver 정기 실행이 정해지기 전까지 채점에서 뺀다.

## 재처리 시연 리허설

재처리는 **같은 원본을 다시 처리해 Gold B 원장의 옛 결과를 바꾸는 일**이다. 원본(Kafka·DB)이 틀린 경우(실제 PG 장애, DB 오염)는 재처리해도 그대로라 재판정이 `STILL_OPEN`이 정상이다. 그래서 리허설은 "흐름이 끝까지 도는가"와 "결과가 기대대로인가"를 따로 본다.

### R-1. 같은 입력 재처리 (흐름 확인, 재영 님 시험)

- **요청:** Athena로 `REQUESTED`·`APPROVED` 두 줄 (`rq-test-20261024-01`, 2026-10-21 16:00~17:00 UTC, 규칙 `0.2.0`, `KAFKA`). 승인 화면은 이상이 있어야 요청을 만든다.
- **기대:** 그 시간 폴더 ②는 5,588줄 그대로 파일 1개, ①은 41줄 그대로 파일 1개, ④ 0줄. `reprocess_events`에 `STARTED` → `LEDGER_REPLACED` 1줄(detail `messages` 5588, `written` ① 41·② 5588, `kept` 0, `missing_topics` `["reviews.raw"]`) → 판정 잡의 `REDETECTED`·`VERIFIED`(`NO_ANOMALY_BEFORE`). 바뀌는 값은 `loaded_at`뿐이다.
- 같은 범위를 한 번 더 요청하면 결과가 같아야 한다 (재현성, 설계 9단계).

### R-2. 승인 화면을 거치는 재처리 (실제 흐름)

1. 시나리오 1을 걸어 R1 이상이 생기게 한다.
2. 승인 화면에서 그 이상으로 재처리를 요청하고 승인한다 (요청 뒤 60분 안). 범위는 1시간 폴더로 넓어진다.
3. **시간 폴더가 끝나기 전에 승인했으면 poller가 폴더 끝 + 10분까지 기다렸다가 시작한다** (2026-10-25부터). 승인 뒤 60분 안에 시작하지 못하면 승인 만료라 새로 요청한다.
4. `reprocess_events`: `STARTED`(source `KAFKA`) → 폴더마다 `LEDGER_REPLACED` → 5~10분 안에 판정 잡의 `REDETECTED`·`VERIFIED`. 폴더가 여러 개면 재판정은 5분에 한 폴더씩이다.
5. **기대 결과는 `STILL_OPEN`**이다. 실제 PG 장애라 다시 처리해도 실패는 그대로다. 대시보드 재처리 이력 화면에 단계가 순서대로 보인다.
6. 한 시간치(지금 약 14만 건)는 약 40초·220MB다 (2026-10-25 로컬 측정). 한 요청은 5시간 안쪽으로 둔다 (Pod 메모리 상한 2Gi).

### R-3. 결과가 바로잡히는 재처리 (팀 결정 필요)

컨트롤러에는 **Gold B 쪽 처리 오류**를 만드는 사건이 없어서, 재처리로 `RESOLVED`가 되는 시연은 따로 꾸며야 한다. 두 가지 안이 있다 (**미정**).

| 안 | 하는 일 | 기대 결과 | 부담 |
|---|---|---|---|
| 잘못된 판정 줄 넣기 | 지난 시간대 결제 메시지 몇 건에 대해 ④ 오류 줄을 시험용으로 넣는다 (결제 5% 이상이면 R4, 그 결제는 `INVALID_LATEST`로 보류) | 재처리하면 ④ 줄이 지워지고 결제가 돌아와 재판정 `RESOLVED` | 공유 원장에 시험 줄을 쓴다. R4는 채점 대상이 아니다 |
| 규칙 바꾸기 | 규칙표를 일부러 틀리게 바꾼 이미지로 적재하다 고친 이미지로 재처리 | 새 규칙 버전으로 바뀌고 옛 판정은 이력으로 남음 (설계 9단계) | 이미지 빌드·배포 두 번, 운영 적재를 건드린다 |

### R-4. 실패·경계 확인

| 상황 | 기대 결과 |
|---|---|
| 시간 폴더가 끝나기 전 승인 | 기다렸다가 폴더 끝 + 10분 뒤 시작. 로그에 "시간 폴더가 끝나길 기다리는 승인 n개" |
| 승인 뒤 60분 안에 시작 못 함 | 고르지 않음 (승인 만료). 승인 화면에서 새로 요청 |
| 규칙 버전이 이미지와 다름 (예: `0.1.0`) | 바로 `FAILED`(`retryable` false), 원장 그대로 |
| Pod가 자원 부족으로 못 뜸 | `STARTED` 없이 끝나고 다음 5분 실행이 다시 고름 (승인 만료 전까지) |
| Kafka 보관 기간(7일)이 지난 시간대 | Bronze v2에서 읽음: `STARTED`의 source `BRONZE`와 `bronze_folders`. Bronze v2가 10-20부터 있어 **10-27 오후(KST)부터** 10-20 시간대로 확인할 수 있다 |
| 파일 합치기와 겹침 | 같은 pool이라 동시에 돌지 않는다 (DAG 밖에서 손으로 돌릴 때만 주의) |

## 파일 합치기 확인

- **날짜:** 예약 실행은 매일 00:30 UTC(한국 09:30)에 어제(UTC)를 합친다. 적재 잡이 따라잡으며 쌓은 **10-20~10-23은 손으로 한 번씩** 날짜 입력(`day`)을 넣어 실행한다 (2026-10-25 기준 `topic_messages` 파일 295·205·752·633개).
- **기대:** 그 날의 원장 4개 시간 폴더마다 파일 1개(`part-compact-…`), 시간 폴더마다 줄 수 전후 같음(SQL ⑦), 로그 `파일 합치기 <날>: 폴더 N개, 원래 파일 M개 → N개, 줄 K개`, 한 번 더 돌리면 `폴더 0개`.

## 확인 SQL (Athena)

```sql
-- ① 적재 신선도: 가장 최근 Kafka 시각과 적재 시각
SELECT max(kafka_timestamp) AS newest_kafka_ts, max(loaded_at) AS newest_loaded
FROM gold_b.topic_messages WHERE dt = '<오늘 UTC 날짜>';

-- ② 지연: 토픽별 1분 측정 (가장 느린 파티션, 밀린 합계, 상태)
SELECT collected_at, topic, max(lag_sec) AS lag_sec, sum(lag_msgs) AS lag_msgs,
       array_join(array_agg(DISTINCT connector_state), ',') AS state
FROM gold_b.bronze_lag_snapshots
WHERE dt = '<UTC 날짜>' AND hour IN ('<HH>', '<HH+1>')
GROUP BY 1, 2 ORDER BY 1, 2;

-- ③ PG별 5분 단위 PG 원인 실패 비율
SELECT pg, from_unixtime(floor(to_unixtime(completed_at) / 300) * 300) AS five_min,
       count(*) AS attempts, count_if(failure_cause = 'PG') AS pg_cause,
       round(1.0 * count_if(failure_cause = 'PG') / count(*), 3) AS pg_rate
FROM gold_b.payment_attempts
WHERE completed_at >= TIMESTAMP '<시작 UTC>' - INTERVAL '30' MINUTE
GROUP BY 1, 2 ORDER BY 2, 1;

-- ④ 토픽별 분당 유입
SELECT topic, date_trunc('minute', kafka_timestamp) AS minute, count(*) AS n
FROM gold_b.topic_messages
WHERE dt = '<UTC 날짜>' AND hour IN ('<HH>', '<HH+1>')
GROUP BY 1, 2 ORDER BY 2, 1;

-- ⑤ 성공 결제가 2건 이상인 주문 (최근 적재 기준, R5와 같은 방식)
SELECT t.order_id, count(*) AS success_count, max(t.loaded_at) AS last_loaded
FROM gold_b.payment_attempts t
WHERE t.status = 'SUCCESS' AND t.order_id IN (
  SELECT order_id FROM gold_b.payment_attempts
  WHERE status = 'SUCCESS' AND loaded_at >= TIMESTAMP '<주입 UTC>' - INTERVAL '5' MINUTE)
GROUP BY t.order_id HAVING count(*) > 1;

-- ⑥ 판정 결과
SELECT rule_id, anomaly_type, scope_key, window_start, window_end, observed_value, status, detected_at
FROM gold_b.anomaly_current WHERE detected_at >= TIMESTAMP '<주입 UTC>' ORDER BY detected_at;

-- ⑦ 파일 합치기 전후: 시간 폴더별 줄 수와 파일 수
SELECT hour, count(*) AS rows, count(DISTINCT "$path") AS files
FROM gold_b.topic_messages WHERE dt = '<합친 날>' GROUP BY hour ORDER BY hour;

-- ⑧ 재처리 기록
SELECT request_id, step, "at", actor, source, window_start, window_end, detail
FROM gold_b.reprocess_events WHERE "at" >= TIMESTAMP '<승인 UTC>' ORDER BY request_id, "at";
```
