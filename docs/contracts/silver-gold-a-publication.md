# Silver·Gold A Glue·Athena 공개 명세

상태: **실행 ID 고정 조회 방식은 결정. 아래 DB·표 이름과 공개 레코드·권한은 인프라/소비자 검토안이며 아직 배포·구현하지 않았다.**

목적: 재영님은 카탈로그·S3·실행 권한을 연결하고, 대시보드와 R6 판정 잡은 어느 완료 결과를 읽어야 하는지 같은 기준으로 확인한다. 원천 입력 형식 규칙인 format_rules.yaml과는 다른 **결과 공개 계약**이다.

## 1. 결정과 현재 구현

| 항목 | 상태 |
|---|---|
| 실행별 불변 결과를 run_id로 고정 조회 | 결정 |
| 지표와 refresh_holds는 같은 channel/run_id로 조회 | 결정 |
| 현재 Spark Parquet·실행 manifest·completed/current 기록 | 구현됨(PR #82), 실제 EKS 실행 미검증 |
| Glue DB/표·실행 파티션 등록·Athena 조회 | 미구현 |
| 아래 silver_runs/gold_runs 공개 목록, completed_at | 미구현 |
| R6의 완료 실행 순차 소비 | 합의 방향. 현재 판정 코드는 최신 실행 하나 조회이므로 변경 필요 |
| 운영 리뷰 점수는 Iceberg 최신 점수 뷰 사용 | 결정, Gold A 조회 연결은 미구현 |

현재 current.json은 Spark 내부 최신 참조다. 이를 바꾸어도 Glue·Athena 공개가 자동으로 바뀌지 않는다. **Athena 공개 기준은 아래 완료 공개 목록**이며, 계산 완료와 카탈로그 공개 완료를 구분한다.

## 2. DB·표·파티션 제안

- Catalog: AwsDataCatalog, region: ap-northeast-1. DB 이름 silver / gold_a는 제안이며 기존 이름과 충돌 여부를 인프라에서 확인한다.
- Athena Engine 3를 대상으로 실제 저장 파일 조회를 검증한다. workgroup·쿼리 결과 prefix·암호화 설정은 재영님이 공유할 값이다.
- DB·표·뷰 정의와 스키마 변경은 배포 과정에서 관리한다. 실행 잡이 매번 CREATE TABLE 하거나 임의 스키마 변경을 하지 않는다.
- 기존 출력은 run_id별 전체 스냅샷이다. **이번 공개 계약에서는 날짜 파티션 LOCATION을 교체하지 않는다.** 날짜는 조회 조건이다. run_id 안의 날짜별 파티션 추가는 성능 검증 후 별도 결정이다.

### Silver

| 제안 표 | 파티션 | 역할·등록할 실제 데이터 위치 |
|---|---|---|
| silver.silver_runs | 없음 | 거래 Silver의 완료 공개 목록. silver/runtime/trade/catalog/completed/ 아래 실행별 Parquet 1행(신규) |
| silver.order_amount_checks | run_id STRING | R6용 공개 결과. silver/runtime/trade/catalog-data/runs/<run_id>/order_amount_checks/(신규 공개 투영) |
| silver.orders_current_runs | run_id STRING | silver/runtime/trade/runs/<run_id>/orders_current/ |
| silver.order_status_history_runs | run_id STRING | 같은 실행의 order_status_history/ |
| silver.order_items_runs | run_id STRING | 같은 실행의 silver_order_items/ |
| silver.payment_attempts_runs | run_id STRING | 같은 실행의 payment_attempts/ |
| silver.trade_quarantined_records_runs | run_id STRING | 같은 실행의 quarantined_records/ |
| silver.trade_dq_results_runs | run_id STRING | 같은 실행의 dq_results/ |
| silver.trade_impact_candidates_runs | run_id STRING | 같은 실행의 impact_candidates/ |

첫 공개는 R6·거래/판매 조회부터 연결한다. Silver 상세 UTC TIMESTAMP 컬럼은 아래 정밀도 게이트를 통과한 후에만 Athena에 공개한다. R6를 위해 원문·전체 격리 테이블의 읽기 권한을 넓히지 않는다.

### Gold A

| 제안 표 | 파티션 | 현재 Spark 데이터셋·위치 |
|---|---|---|
| gold_a.gold_runs | channel STRING | gold_a/runtime/<channel>/catalog/completed/ 아래 공개 목록(신규) |
| gold_a.order_sales_hourly_runs | run_id STRING | gold_a/runtime/trade/runs/<run_id>/order_sales_hourly/ |
| gold_a.product_sales_daily_runs | run_id STRING | 같은 거래 실행의 product_sales_daily/ |
| gold_a.funnel_session_product_runs | run_id STRING | gold_a/runtime/funnels/runs/<run_id>/funnel_session_product/ |
| gold_a.funnel_daily_runs | run_id STRING | 같은 퍼널 실행의 funnel_daily/ |
| gold_a.review_product_daily_runs | run_id STRING | gold_a/runtime/reviews/runs/<run_id>/review_product_daily/ |
| gold_a.review_aspect_daily_runs | run_id STRING | 같은 리뷰 실행의 review_aspect_daily/ |
| gold_a.refresh_holds_runs | channel STRING, run_id STRING | trade/funnels의 같은 실행 refresh_holds/ |

channel은 trade / funnels / reviews다. run_id는 channel 안에서 재사용하지 않는다. review_aspect_daily는 현재 선택 입력이며 생성 여부를 공개 목록의 available_tables_json에 기록한다. 점수 미요청과 정상 0건을 구분한다. 리뷰 Gold는 현재 품질 오류 시 전체 갱신 중단이며 refresh_holds를 생성하지 않는다. 리뷰용 빈 holds 파티션을 임의로 만든 것으로 간주하지 않는다.

후속 Silver 공개 대상(이번 첫 거래 공개와 분리):

| 제안 표 | 파티션 | 현재 출력 위치 |
|---|---|---|
| silver.click_events_runs | run_id STRING | silver/runtime/clicks/runs/<run_id>/click_events/ |
| silver.reviews_runs | run_id STRING | silver/runtime/reviews/runs/<run_id>/silver_reviews/ |

클릭·리뷰는 해당 계층의 불변 manifest로 입력을 고정한다. 위 silver_runs는 우선 거래/R6 목록으로 한정하며 클릭·리뷰 완료 공개 목록을 같은 표에 섞지 않는다. 후속 확장 시 별도 목록 또는 channel 구분 계약을 먼저 추가한다. 모델이 정제 리뷰를 읽을 권한과 Gold A가 모델 점수를 읽을 권한은 서로 다른 실행 역할에 연결한다.

회원 Spark 출력은 아직 없어 운영 표 목록에 넣지 않는다. 상품 기준정보는 각 실행의 products/manifest.json으로 고정되며 별도 Athena 공개는 필요 소비자와 범위를 정한 뒤 추가한다.

## 3. 실행 고정·조회 규칙

1. 대시보드 갱신 시작 시 gold_runs에서 channel별 공개 실행을 한 번 선택한다.
2. 선택한 channel/run_id를 **해당 화면의 모든 쿼리에 동일하게 전달**한다.
3. metric 테이블은 run_id, refresh_holds는 channel/run_id로 필터한다.
4. 여러 실행의 결과를 합산하지 않는다. 거래 run_id를 퍼널/리뷰 run_id로 재사용해 조회하지 않는다.
5. 실행 ID를 지정하지 않는 최신 뷰는 탐색용 편의 기능으로만 고려한다. 여러 번의 쿼리에서 최신을 각각 다시 선택하면 실행이 섞이므로 대시보드 일관성 보장에 사용하지 않는다.

```sql
-- 화면 갱신 시작 때 한 번 선택. completed_at은 아래 공개 순서 조건을 충족해야 한다.
SELECT run_id, completed_at, quality_status, held_scope_count, source_manifest
FROM gold_a.gold_runs
WHERE channel = 'trade' AND status = 'COMPLETED'
ORDER BY completed_at DESC, run_id DESC
LIMIT 1;

-- 선택한 실행 ID를 아래 모든 쿼리에 고정해서 전달한다.
SELECT hour_start_kst, order_count, paid_order_count, approved_amount
FROM gold_a.order_sales_hourly_runs
WHERE run_id = '<선택한 실행 ID>';

SELECT table_name, key_json, reason, previous_result_available, last_normal_result_json
FROM gold_a.refresh_holds_runs
WHERE channel = 'trade' AND run_id = '<같은 실행 ID>';
```

PARTIAL은 공개 실패가 아니다. 해당 실행의 지표에는 이전 정상 보류 범위와 새 정상 범위가 함께 있을 수 있다. refresh_holds의 key_json·previous_result_available과 previous_run_id를 함께 표시한다. 이전 정상 결과가 없는 보류 범위는 정상 매출 0으로 표시하지 않는다.

COMPLETED 공개 목록이 없는 channel은 미생성으로 표시한다. 공개 목록의 건수 0과 테이블 없음, 쿼리 실패를 구분한다. 실패한 최신 시도는 완료 공개 목록에 없으므로 그 실패 여부는 Airflow/실행 기록에서 확인한다. 이전 공개 실행을 최신 성공으로 계속 읽는 것이 실패 탐지를 대신하지 않는다.

## 4. 완료 공개 목록(신규 구현 필요)

### silver.silver_runs — 거래 Silver/R6

| 컬럼 | 공개 타입 | 의미 |
|---|---|---|
| run_id | STRING | 거래 Silver 실행 ID, 1실행 1행 |
| completed_at | TIMESTAMP | 카탈로그 등록까지 끝낸 공개 완료 시각, UTC·밀리초 |
| status | STRING | 이 표에는 COMPLETED만 기록 |
| quality_status | STRING | PASS / INCOMPLETE. 품질 오류가 있어도 검사가 완료되면 공개 가능 |
| checked_at | TIMESTAMP | 검사 시각, UTC·밀리초 공개 표현 |
| coverage_status | STRING | 현재 UNVERIFIED. 공개 완료가 Kafka 원천 완전성을 보장하지 않음 |
| checked_at_utc | STRING | 검사 시각 원본의 UTC 소수초 6자리 표현 |
| source_manifest | STRING | 불변 Silver 실행 manifest URI |
| format_rule_version | STRING | 실행이 적용한 YAML 규칙 버전 |
| format_rule_sha256 | STRING | 해당 규칙 파일 해시 |
| code_ref | STRING | 업무 이미지의 코드 버전 |
| order_amount_check_count | BIGINT | 검사 행 수. 0건 실행도 완료 목록에 존재 |
| available_tables_json | STRING | 공개를 완료한 데이터셋 이름·건수 목록 JSON |

format_rule_version/format_rule_sha256은 현재 manifest.format_rules.version/sha256에서 가져온다. 공개 완료 상태는 원본 입력의 누락 없음이나 Kafka offset 처리 완료를 증명하지 않는다.

status와 quality_status를 혼동하지 않는다. Silver INCOMPLETE 결과를 빼 버리면 R6가 읽어야 할 MISMATCH·참조 대기를 놓친다. FAILED나 저장 중인 실행은 silver_runs에 넣지 않는다.

### gold_a.gold_runs

기본 컬럼: run_id STRING, completed_at TIMESTAMP(UTC 밀리초), status STRING(COMPLETED), quality_status STRING(PASS/PARTIAL), source_manifest STRING, silver_run_id STRING, silver_manifest STRING, products_manifest STRING, silver_clicks_manifest STRING(퍼널만), previous_run_id STRING, held_scope_count BIGINT, available_tables_json STRING, code_ref STRING. channel은 STRING 파티션 키다.

리뷰는 model input 조회 ID·고정 결과 참조·선택 정책·실제 모델 버전 집합을 manifest에 추가해야 한다. 리뷰별 최신 모델 뷰에는 여러 모델 버전이 섞일 수 있으므로 단일 model_version으로 출처를 대신하지 않는다.

### completed_at·순서 보장 조건

- checked_at은 실행 검사에 부여한 시각으로 카탈로그 공개 완료 시각이 아니므로 R6 소비 커서로 사용하지 않는다.
- completed_at은 카탈로그 공개 순서에 맞춰 발급한다. **같은 완료 목록을 쓰는 공개자는 하나로 직렬화하고 후속 공개의 completed_at이 이전보다 반드시 커야 한다.** 밀리초가 같으면 이전 값 +1밀리초 이상으로 발급하는 방식도 검토한다. 실패/재시작 후에도 이전 공개 값을 복원해야 한다.
- 단순 datetime.now()·run_id 정렬·DAG 하나의 max_active_runs=1만으로 이 조건을 보장했다고 하지 않는다. 특히 trade/funnels가 같은 Silver 거래 목록에 기록하므로 공개 직렬화가 필요하다.
- 이 조건과 장애 복구가 아직 구현되지 않았다. 구현·검증 전에는 주현님에게 (completed_at, run_id) 커서로 실행을 절대 건너뛰지 않는다고 보장하지 않는다.

## 5. R6 제공 표

행 기준: **실행 × 주문 × 검사 종류당 1행**. 현재 검사 이름은 order_item_total_match다.

| 컬럼 | 공개 타입 | 현재 상태 |
|---|---|---|
| run_id | STRING 파티션 키 | 원본 Parquet에도 동일 값 존재. 파티션 값과 일치 검사 필요 |
| checked_at | TIMESTAMP | 현재 원본은 마이크로초. 공개 투영에서 TIMESTAMP_MILLIS로 저장하는 안은 미구현 |
| checked_at_utc | STRING | 원본 검사 시각 정밀도 보존용 신규 공개 컬럼(제안) |
| order_id | STRING | 구현됨 |
| check_name | STRING | 구현됨 |
| check_version | STRING | 구현됨. 금액 검사 버전이며 YAML/지문 버전과 별개 |
| status | STRING | PASS / MISMATCH / UNVERIFIED / PENDING_REFERENCE / ITEM_ERROR |
| order_total_amount | BIGINT | 원화 정수 |
| item_total_amount | BIGINT | 원화 정수. 검증 불가 시 NULL |
| amount_difference | BIGINT | **주문상품 합계 − 주문 총액**. NULL을 0으로 채우지 않음 |
| source_manifest | STRING | 불변 실행 manifest URI |

```sql
-- 주현님: 마지막 처리 커서 이후 완료 실행을 모두 순서대로 읽는다.
SELECT run_id, completed_at, quality_status, source_manifest
FROM silver.silver_runs
WHERE status = 'COMPLETED'
  AND (completed_at > TIMESTAMP '<마지막 공개 완료 시각>'
       OR (completed_at = TIMESTAMP '<같은 시각>' AND run_id > '<마지막 실행 ID>'))
ORDER BY completed_at, run_id;

-- 반환된 실행을 하나씩 처리. 전체 상태를 읽어 해소를 확인한다.
SELECT run_id, checked_at, order_id, check_name, check_version, status,
       order_total_amount, item_total_amount, amount_difference, source_manifest
FROM silver.order_amount_checks
WHERE run_id = '<처리할 실행 ID>' AND check_name = 'order_item_total_match';
```

MISMATCH는 발생/지속, 후속 PASS는 해소 재판정에 사용한다. UNVERIFIED/PENDING_REFERENCE/ITEM_ERROR·행 부재·0건 실행은 해소 근거가 아니다. 처리 위치 저장·중복 방지·이상 이력·VERIFIED는 주현님 담당이며, 현재 최신 실행만 읽는 코드를 순차 소비로 바꿔야 한다. 정기 주기는 미확정이므로 몇 분 이내 탐지 보장은 하지 않는다.

## 6. 카탈로그 등록·공개 순서

1. Spark가 실행별 원본 결과·품질·manifest를 저장하고 입력 불변 여부를 확인한다.
2. 공개 대상 manifest를 고정한다. 타임스탬프 공개 투영이 필요하면 별도 경로에 저장하며 원본 실행을 수정하지 않는다.
3. **그 실행에 속한 모든 대상 표**의 run_id 파티션을 등록하고 스키마·LOCATION·예상 건수·시각 타입을 확인한다.
4. 모두 성공한 뒤에만 완료 공개 목록의 실행 레코드를 신규 저장한다. 소비자는 이 레코드와 동일 실행의 파티션을 기준으로 조회한다.
5. 중간 실패면 완료 공개 레코드를 만들지 않는다. 기존 공개 실행은 유지하고, 일부 등록된 미공개 파티션은 원인을 수정해 같은 실행으로 등록을 재시도할 수 있다.

완료 목록은 실행별로 고정된 객체 키에 Parquet 1행을 조건부 신규 쓰기하는 안이다. 같은 실행을 새 part 파일로 반복 저장해 중복 행을 만들지 않는다.

동일 실행 공개 재시도는 레코드/LOCATION/스키마/건수 일치를 확인해 중복 공개하지 않는다. 다르면 실패한다. 이전 실행 파티션 LOCATION을 새 실행으로 바꾸지 않는다. 완료 레코드 손실·중복·부분 등록 복구는 구현 시 검증한다.

등록은 인프라가 배포한 표에 대해 Glue BatchCreatePartition 또는 Athena ALTER TABLE ADD PARTITION 방식으로 구현한다(제안). 기존 비-Hive 경로를 정확히 지정한다. MSCK REPAIR나 파티션 프로젝션이 완료 상태를 선택해 주는 것으로 해석하지 않는다.

```sql
-- 아래 DB/표는 제안이며 아직 실행하지 않는다.
ALTER TABLE gold_a.order_sales_hourly_runs ADD
PARTITION (run_id = '<run_id>')
LOCATION 's3://clothes-query-datalake/gold_a/runtime/trade/runs/<run_id>/order_sales_hourly/';

ALTER TABLE gold_a.refresh_holds_runs ADD
PARTITION (channel = 'trade', run_id = '<같은 run_id>')
LOCATION 's3://clothes-query-datalake/gold_a/runtime/trade/runs/<run_id>/refresh_holds/';
```

루트 LOCATION을 여러 데이터셋이 섞인 runs/ 전체로 설정해 스캔하지 않는다. 각 등록 파티션은 하나의 데이터셋 폴더만 가리킨다. 테이블의 기본 LOCATION은 같은 계층·channel 아래 빈 catalog-tables/<table>/ prefix(예: gold_a/runtime/trade/catalog-tables/order_sales_hourly_runs/)로 두는 안이며 생성될 실제 prefix/권한은 인프라와 확정한다. 런타임 등록 주체는 Driver 또는 후속 공개 태스크 중 정해야 한다. 표 생성/스키마 관리와 실행 파티션 등록 역할을 분리한다.

## 7. 시각·물리 타입 검증 게이트

현재 Spark는 UTC 컬럼·checked_at을 Parquet TIMESTAMP_MICROS로 저장한다. 이것이 Athena Engine 3에서 손실·오류 없이 그대로 읽힌다고 검증한 상태가 아니다. AWS 문서에는 TIMESTAMP 정밀도 3 초과 시 직렬화 오류 가능성이 명시돼 있다.

- source 시각·지문 계산·Silver 원본은 마이크로초를 유지한다. Athena를 위해 지문 입력을 밀리초로 절삭하지 않는다.
- R6/공개 메타데이터는 공개용 TIMESTAMP_MILLIS + 정확한 UTC 6자리 STRING을 함께 저장하는 안을 제안한다. 이 투영은 별도 catalog-data/ prefix에 쓰며 현재 원본 파일을 덮어쓰지 않는다. 원본과 키·상태·금액·건수가 같아야 한다.
- completed_at은 공개 순서용 밀리초 시각으로 관리한다. 원천 이벤트 순서나 Kafka 처리 범위를 증명하는 필드가 아니다.
- 실제 Athena에서 소수초 0/3/6자리와 날짜 경계·NULL·0건을 읽어 보기 전에는 상세 Silver DDL을 운영 확정하지 않는다. 공통 시각 파싱 보완과 Athena 저장 타입 문제는 별개다.
- Gold A의 현재 날짜는 DATE, KST 시각은 STRING, 건수/금액은 BIGINT, 평균/비율은 DOUBLE로 읽는 안이다. 현재 스키마를 바꾸지 않는다.

## 8. 운영 리뷰 모델 입력과 결과 공개

Gold A 입력: clothes_query_dev_review_score.review_aspect_scores_latest. WHERE review_date BETWEEN ...로 KST 리뷰 작성일을 선택한다. 이 뷰는 Iceberg 원본에서 **리뷰마다** 가장 큰 model_version_no의 속성 전체를 고른다.

현재 Gold A build_aspects는 파일의 단일 model_version을 선택하는 구현이다. 따라서 뷰를 읽는 어댑터뿐 아니라 버전별 그룹/출처 표현도 보완해야 한다. view query가 끝난 결과를 한 번 고정하고 query_execution_id·결과 객체 목록·모델 버전·KST 범위를 manifest에 남긴다. 매번 변하는 최신 뷰를 같은 실행에서 반복 조회하지 않는다. Athena 조회 ID 자체를 Iceberg snapshot ID라고 기록하지 않는다.

모델 입력을 고정한 뒤 생성한 review_aspect_daily를 run_id로 공개한다. 현재 3분류 자동 변환은 없고 -2~2 정수 점수만 사용한다. 원본 Iceberg 파일 삭제·VACUUM·모델 재채점은 모델 파이프라인 담당이며 이번 공개 잡의 정리 권한에 포함하지 않는다.

## 9. 권한·담당자

| 역할 | 필요한 범위 | 이번 명세가 부여하지 않는 범위 |
|---|---|---|
| 재영님 배포 역할 | silver/gold_a DB·표·뷰 생성/변경, workgroup·S3·역할 연결 | 업무 계산 규칙 변경 |
| Spark Driver/Executor | 승인된 Bronze·상품 입력 읽기, 업무 결과 저장. 기존 커미터 정리 범위 | 원천/상품/리뷰 Iceberg 파일 삭제 |
| 공개 등록 역할(실행 위치 미정) | 해당 표 GetTable/GetPartition/BatchCreatePartition 등과 catalog 메타데이터/투영 결과 쓰기 | 런타임 CREATE/DELETE TABLE, 과거 실행 교체 |
| 대시보드 | 공개된 Gold A 지표·gold_runs·refresh_holds 조회 및 Athena 결과 접근 | Silver 원문·격리·ground_truth 접근 |
| R6 판정 잡 | silver_runs와 order_amount_checks, 그 데이터 prefix 및 Athena 결과 접근 | Silver 전체 원문/격리 테이블 접근 |
| 조사 에이전트 | 기존 Gold B 이상 이력의 근거로 조사 | 이번 명세로 Silver 직접 읽기 권한을 추가하지 않음 |

Athena SQL에서 완료 목록을 필터하는 것은 접근 권한 경계 자체가 아니다. 실제 Glue/Lake Formation/S3/IAM 권한을 역할별로 확인해야 한다. 새 catalog/completed/·catalog-data/는 기존 실행 경로와 구분해 인프라에 전달한다. 버킷 목록 권한·KMS·Athena 결과 prefix 권한도 확인한다. 신규 광범위 권한을 여기서 적용하지 않는다.

## 10. 구현·검증 체크리스트

- [ ] 재영님: DB/표 이름·workgroup/결과 경로·관리 주체 확인
- [ ] 현지: completed_at·완료 공개 목록·직렬화/재시작 순서 보장 구현
- [ ] 현지: R6 공개 투영과 원본 정밀도 보존, Athena 시각 타입 검증
- [ ] 현지/재영: run_id 파티션 등록·부분 실패/동일 실행 재시도 구현
- [ ] 대시보드 담당: 갱신당 channel/run_id 한 번 선택, 지표/holds 고정 조회
- [ ] 주현님: 최신 하나 조회를 미처리 완료 실행 순차 소비로 전환, 0건/대기/행 부재 미해소 검증
- [ ] 정상 → 금액 MISMATCH/PARTIAL → 계속 MISMATCH → 원본 수정 → PASS 흐름 검증
- [ ] 두 실행을 빠르게 공개해도 같은 화면에 실행이 섞이지 않는지 확인
- [ ] 미공개 파티션·저장 실패·등록 실패가 완료 목록에 나타나지 않는지 확인
- [ ] 리뷰 Athena 입력 고정·혼합 모델 버전·과거 작성일 재채점 공개 연결

현재 정기 실행 주기와 R6 시연 포함 여부는 확정하지 않는다. 위 코드는 제안 SQL 예시이며 AWS 리소스 생성·DDL 실행·권한 적용은 수행하지 않았다.

## 11. 현재 물리 스키마 근거

아래는 실제 로컬 Spark 저장 manifest의 schemas로 확인한 거래 스키마다. UTC TIMESTAMP는 원본 타입이며 위 Athena 정밀도 게이트 이전에 호환이 확정됐다는 의미가 아니다. run_id는 조회 파티션으로 추가하며 원본 파일에 같은 이름이 있는 R6는 파티션 값과 일치 검증한다.

### 거래 Silver

**dq_results**

```text
source_dataset STRING, input_count BIGINT, accepted_count BIGINT, quarantined_count BIGINT, duplicate_count BIGINT, conflict_count BIGINT, pending_count BIGINT, status STRING, check_version STRING, format_rules STRING
```

**impact_candidates**

```text
source_dataset STRING, source_row_number BIGINT, source_record_id STRING, valid BOOLEAN, order_id STRING, order_item_id STRING, payment_id STRING, article_id STRING, session_id STRING, status STRING, ordered_at STRING, updated_at STRING, completed_at STRING, cdc_op STRING, source_ts_ms BIGINT, source STRING
```

**order_amount_checks**

```text
order_id STRING, check_name STRING, check_version STRING, status STRING, order_total_amount BIGINT, item_total_amount BIGINT, amount_difference BIGINT, run_id STRING, checked_at TIMESTAMP(UTC 원본 마이크로초), source_manifest STRING
```

**order_status_history**

```text
order_id STRING, previous_status STRING, status STRING, status_reason STRING, changed_at_utc TIMESTAMP(UTC 원본 마이크로초), changed_at_kst STRING, source_ts_ms BIGINT
```

**orders_current**

```text
order_id STRING, member_id STRING, session_id STRING, status STRING, status_reason STRING, total_amount BIGINT, ordered_at_utc TIMESTAMP(UTC 원본 마이크로초), ordered_at_kst STRING, updated_at_utc TIMESTAMP(UTC 원본 마이크로초), updated_at_kst STRING, source_ts_ms BIGINT
```

**payment_attempts**

```text
payment_id STRING, order_id STRING, attempt_no BIGINT, method STRING, pg STRING, amount BIGINT, status STRING, failure_code STRING, requested_at_utc TIMESTAMP(UTC 원본 마이크로초), requested_at_kst STRING, completed_at_utc TIMESTAMP(UTC 원본 마이크로초), completed_at_kst STRING, payment_content_hash STRING, fingerprint_version STRING
```

**quarantined_records**

```text
source_dataset STRING, source_row_number BIGINT, source_file STRING, source_line BIGINT, source_record_id STRING, record_key STRING, order_id STRING, field STRING, error_code STRING, reason STRING, category STRING, rule_id STRING, check_version STRING, order_total_amount BIGINT, item_total_amount BIGINT, amount_difference BIGINT, kafka_reference STRING
```

**silver_order_items**

```text
order_item_id STRING, order_id STRING, article_id STRING, quantity BIGINT, unit_price BIGINT, item_amount BIGINT
```

### 거래 Gold A

**order_sales_hourly**

```text
hour_start_kst STRING, order_count BIGINT, paid_order_count BIGINT, approved_amount BIGINT
```

**product_sales_daily**

```text
sales_date_kst DATE, article_id STRING, product_code BIGINT, paid_order_count BIGINT, sold_quantity BIGINT, item_sales_amount BIGINT
```

**refresh_holds**

```text
table_name STRING, key_json STRING, reason STRING, previous_result_available BOOLEAN, last_normal_result_json STRING
```

### 퍼널·리뷰(현재 코드 정의 기준)

```text
funnel_session_product:
  session_id STRING, article_id STRING, product_code BIGINT,
  first_view_at_kst STRING, first_cart_at_kst STRING, first_order_at_kst STRING, first_paid_at_kst STRING,
  has_view BOOLEAN, has_cart BOOLEAN, has_order BOOLEAN, has_paid BOOLEAN, ordered_after_cart BOOLEAN
funnel_daily:
  funnel_date_kst DATE, article_id STRING, product_code BIGINT,
  view_sessions BIGINT, cart_sessions BIGINT, order_sessions BIGINT, paid_sessions BIGINT, cart_order_sessions BIGINT,
  view_to_cart_rate DOUBLE, view_to_order_rate DOUBLE, view_to_paid_rate DOUBLE,
  cart_to_order_rate DOUBLE, order_to_paid_rate DOUBLE
review_product_daily:
  review_date_kst DATE, article_id STRING, product_code BIGINT,
  review_count BIGINT, rating_sum BIGINT, low_rating_count BIGINT,
  average_rating DOUBLE, low_rating_rate DOUBLE
review_aspect_daily:
  review_date_kst DATE, article_id STRING, product_code BIGINT, aspect STRING, model_version STRING,
  scored_review_count BIGINT, score_sum BIGINT, score_neg2_count BIGINT, score_neg1_count BIGINT,
  score_zero_count BIGINT, score_pos1_count BIGINT, score_pos2_count BIGINT, average_score DOUBLE
```

현재 리뷰 속성 출력은 단일 버전 선택의 파일 입력 구현이며, 최신 모델 뷰 연결이 완료됐다는 의미가 아니다.

## 근거

- [실행·물리 스키마](../../pipelines/spark_batch.py), [보류 범위 병합](../../pipelines/gold_a/__init__.py), [리뷰 Spark 집계](../../pipelines/gold_a/reviews.py)
- [기존 공통 계약·대조/재처리](README.md), [인프라 전달 기준](../../infra/platform/spark/handoff/README.md)
- [AWS: 비-Hive 파티션의 명시적 LOCATION 등록](https://docs.aws.amazon.com/athena/latest/ug/partitions.html)
- [AWS: Athena Engine 3 타임스탬프 정밀도 제한](https://docs.aws.amazon.com/athena/latest/ug/engine-versions-reference-0003.html#engine-versions-reference-0003-timestamp-changes)
- [AWS: timestamp 데이터 형식](https://docs.aws.amazon.com/athena/latest/ug/data-types-timestamps.html)
