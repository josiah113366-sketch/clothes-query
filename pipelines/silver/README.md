# Silver 입력·출력 현황

## 결정: 회원 현재 상태 (`members_current`)

| 항목 | 기준 |
|---|---|
| 입력 | `bronze/members-events/year=YYYY/month=MM/day=DD/*.json` 전체 이력. 폴더 날짜는 UTC Kafka 수집일 |
| 출력 | 로컬 `silver/members_current/as_of=YYYY-MM-DD/part-00000.jsonl` |
| 한 행의 기준 | 해당 UTC 수집일까지의 `member_id`당 최신 상태 1행 |
| 중복·순서 | 같은 회원의 동일 내용·원천 시각은 한 번만 반영. 더 큰 `__source_ts_ms` 선택. 같은 시각에 내용이 다르면 오류 |
| 재처리 | 지정 날짜까지의 전체 이력을 다시 읽어 해당 `as_of` 결과 파일 교체 |
| 제외 | 이름·이메일·전화번호 등 PII. Source 커넥터가 입수에서 제외하며 Silver도 필요한 필드만 선택 |

```powershell
python -m pipelines.silver.members --input-root <로컬 또는 s3://버킷/bronze/members-events> --output-root pipelines/silver/.local/lake --through-date 2026-10-14
```

`as_of`는 실행 시각이 아니라 **어느 UTC 수집 날짜까지 읽었는지**를 뜻한다. 이전 날짜 결과를 다시 만들더라도 최신 날짜 결과를 덮어쓰지 않는다. 현재 확인한 실제 파일은 초기 스냅샷(`__op=r`)뿐이다. `c/u` 선택 규칙은 합성 입력으로만 검증했으며 실제 변경 이벤트가 오면 다시 확인해야 한다. 첫 버전은 로컬 Silver 출력만 지원한다.

## 결정: 현재 구현된 리뷰 입력

| 항목 | 기준 |
|---|---|
| 입력 | 리뷰 시뮬레이터 `--sink lake`의 `reviews/year=YYYY/month=MM/day=DD/*.jsonl` (UTC 작성일). 기존 `reviews/dt=YYYY-MM-DD/*.jsonl`도 함께 지원 |
| 출력 | `silver/reviews/dt=YYYY-MM-DD/part-00000.jsonl` (`dt`는 KST 작성일) |
| 한 행의 기준 | `review_id`당 현재 `review_created` 1건 |
| 재처리 | 지정한 KST 날짜별 결과 파일 교체. 같은 범위를 두 번 실행해도 행 수 증가 없음 |
| 중복 | 같은 `review_id`의 재전송/재생성은 `emitted_at`이 가장 늦은 행을 선택. 동시간 충돌은 실패 |
| 보존 | 원문, 별점, 원천 `product_id`, `order_id`, 작성 시각, 전송 시각 |
| 제외 | `member_id`와 `reviews_truth/` 평가 라벨은 운영 분석 출력에 넣지 않음 |

## 미정: 다른 Silver 입력 연결

| 데이터 | 현재 연결 상태 | 구현 전 확인할 것 |
|---|---|---|
| 주문·주문상품·결제 CDC | 가상 입력용 계산 규칙 구현, 실제 Bronze 미연결 | 실제 Bronze 컬럼, CDC 순서·삭제 처리, 중복 식별값 |
| 클릭 이벤트 | `main`에 실제 Bronze 출력 없음 | 세션·상품 키, 이벤트 시각과 중복 기준 |
| 상품 기준정보 | 생성기는 H&M article_id를 product_id로 읽을 수 있고, 대체 임시 상품 모드도 있음 | 실제 입력의 상품 키 출처·상품 스냅샷 위치 확인 |
| 리뷰 AI 분석 결과 | 전달 스키마 없음 | `review_id`, 속성, 감성, 모델 버전, 분석 시각 |

이 표는 구현 상태를 기록한다. 미정 항목의 키나 집계 기준을 임의로 확정하지 않는다.

## 실행

저장소 루트에서 실행한다. `--input-root`와 `--output-root`는 로컬 폴더 또는 `s3://버킷/접두사`다. S3를 쓸 때만 `boto3`와 읽기·쓰기 권한이 필요하다.

```powershell
python -m pipelines.silver.reviews --input-root review-simulator/.local/lake --output-root pipelines/silver/.local/lake --start-date 2026-10-08 --end-date 2026-10-08
```

입력은 운영 리뷰 `reviews/`만 읽고, 평가용 `reviews_truth/`는 사용하지 않는다. 원천 `product_id`를 보존하며 실제 상품 키와의 대응을 확인한 뒤 거래 지표에 연결한다.

신규·기존 파티션을 함께 읽은 뒤 review_id로 중복 처리한다. KST 시작일의 전날 UTC부터 종료일 UTC까지 검색하고 KST 작성일로 행을 선택한다. 출력 경로는 기존 Gold A 호환성을 위해 KST `dt=`를 유지한다. 검색 범위에서 운영 JSONL 파일을 하나도 찾지 못하면 기존 출력을 덮어쓰지 않고 실패한다. 명시적으로 비어 있는 입력 파일이나 읽은 파일 중 대상 KST 리뷰가 없는 경우는 정상 0건 결과로 처리한다.

## 결정: 거래 Silver 계산 규칙

`transactions.py`의 `build_silver(orders, order_items, payments)`를 사용한다.

입력은 CDC의 변경 후 비즈니스 행 목록이다. 주문 상태 변경은 `updated_at` 순서로 복원한다. 결과는 `orders_current`, `order_status_history`, `silver_order_items`, `payment_attempts`다. 시각은 UTC와 KST를 함께 남긴다. 실제 CDC 변경 순서·삭제·재전송 처리와 Bronze 경로 연결은 원본 샘플 확인 후 추가한다.

### 거래 오류 처리와 반환값

`build_silver()`는 정상 상세 4개에 `quarantined_records`와 `dq_results`를 더한 딕셔너리를 반환한다. 아직 파일을 저장하거나 이전 실행의 격리 상태를 갱신하지 않는다.

| 결과 | 내용 |
|---|---|
| `quarantined_records` | 데이터셋, 입력 목록의 행 번호(1부터), 업무 키, 주문 키, 오류 필드·사유·구분, `check_version` |
| `dq_results` | 원천 데이터셋별 입력·정상 채택·격리·중복·충돌·대기 건수, 출력별 행 수, 영향 주문·입력 행, PASS/INCOMPLETE |

- 잘못된 행은 분리하고 다른 정상 행을 처리한다. 일반 프로그램 오류까지 잡아서 숨기지 않는다.
- 같은 결제·주문상품 키에 다른 업무 내용이 있으면 그 키의 모든 행을 분리한다. 같은 키의 한 행이 형식 오류인 경우도 다른 행만 임의로 채택하지 않는다.
- 주문의 일부 변경에 오류·동시각 충돌이 있으면 해당 주문 전체를 보류해 이전 상태를 최신 상태로 잘못 내보내지 않는다. 관련 주문상품·결제는 `DEPENDENCY_BLOCKED`로 남긴다.
- 현재 입력에 주문이 없는 항목은 `PENDING_REFERENCE`다. 잘못된 결제라고 확정하거나 실제 주문 저장소를 자동 조회하지 않는다. 주문을 포함한 입력으로 재실행해야 한다.
- 실패 코드 누락·성공 결제의 실패 코드, 0 이하 금액·단가를 분리한다. 현재 DB의 필수 정보·양수 제약을 반영했다. 미등록 실패 코드의 분류나 YAML의 전체 검사기는 이 함수에서 실행하지 않는다.
- `input_count = accepted_count + duplicate_count + quarantined_count`다. accepted_count는 중복 제거 후 채택한 입력 기록 수이며 주문 현재 상태 출력 수와 다를 수 있다. 오류는 행당 첫 사유를 기록하고, conflict_count/pending_count는 격리 행 수의 부분집합이다.
- 오류·대기 정보가 있는 데이터셋은 INCOMPLETE다. 후속 Gold A/저장 코드는 **모든 dq_results를 확인**해 영향 범위를 완전한 결과로 표시하지 않아야 한다. 정상 출력이 존재한다는 것만으로 전체 처리 완료로 판단하지 않는다.
- `check_version=transactions.v1`은 이 계산 코드의 검사 버전이다. 공통 YAML 규칙 버전을 적용했다고 표시하지 않는다. 원본 파일/Kafka 위치·실행 ID는 실제 입력 연결 단계에서 추가한다. 현재 행 번호는 지속적인 원본 식별 키가 아니다.

이 함수는 제공된 입력 안에서만 중복·충돌을 확인한다. 이전 실행에서 이미 저장한 결제와의 충돌, 날짜·상품 부분 병합, Gold A의 품질 상태 사용은 후속 연결 작업에서 다룬다. 아래 로컬 실행기는 제공한 입력 전체의 결과 묶음을 저장한다.

### 문서 기준 거래 JSONL 실행

문서의 업무 컬럼으로 만든 로컬 JSONL을 읽어 결과를 저장한다. 입력은 CDC 봉투나 실제 S3 경로를 추측한 것이 아니다. 세 입력 모두 파일 또는 폴더를 직접 지정한다. 폴더는 하위 `.json`/`.jsonl` 전체를 읽으며, 파일은 한 줄에 업무 객체 하나다. 시각은 시간대가 있는 ISO 문자열을 사용한다.

```powershell
python -m pipelines.silver.transactions --orders-input <주문-JSONL-경로> --order-items-input <주문상품-JSONL-경로> --payments-input <결제-JSONL-경로> --output-root pipelines/silver/.local/transactions-output
```

- `orders`: `order_id`, `member_id`, `session_id`, `status`, `status_reason`, `total_amount`, `ordered_at`, `updated_at`.
- `order_items`: `order_item_id`, `order_id`, `article_id`, `quantity`, `unit_price`.
- `payments`: `payment_id`, `order_id`, `attempt_no`, `method`, `pg`, `amount`, `status`, `failure_code`, `requested_at`, `completed_at`.

정상 결과 4개와 격리·품질 결과 2개를 `<output-root>/silver/transactions/runs/run-.../`에 JSONL로 쓴다. 여섯 파일이 모두 저장된 뒤 `<output-root>/silver/transactions/current.json`을 교체한다. current.json에는 원본 파일 목록, 입력·출력 건수, PASS/INCOMPLETE 상태, 실제 결과 파일 경로가 있다. 오류 행에는 원본 파일과 줄 번호도 남긴다.

**후속 조회는 current.json이 가리키는 결과만 읽는다.** runs/ 전체를 합치면 과거 실행을 중복 집계하게 된다. 같은 입력을 다시 실행하면 새 결과 묶음을 만들지만 대표 결과는 한 묶음만 가리킨다. 이전 묶음은 보존한다. 이번 변경은 지정 입력 전체의 스냅샷 저장이며, 날짜·상품 부분 재처리와 기존 저장 데이터 병합은 포함하지 않는다.

잘못된 JSON 행은 원문을 복사하지 않고 PARSE_ERROR로 격리한다. 파일 없음·파일 읽기/인코딩 실패, CDC 봉투 입력, 결과 저장 실패는 실행 실패로 전달하고 기존 current.json을 유지한다. 명시적으로 비어 있는 파일은 정상 0건 입력이다. 출력과 입력 경로의 겹침은 금지한다.

실제 거래 Bronze가 생기면 CDC 변경 종류·시각 직렬화·메타데이터를 확인해 이 입력 앞의 변환을 연결한다. 이번 검증은 문서 기반 합성 데이터이며 실제 거래 Bronze 검증이 아니다. 공통 YAML 검사는 아직 실행하지 않는다.

## 클릭 Silver (`click_events`)

원천 `simulator/src/sim/behavior/model.py`의 ClickEvent와 `sink.py`의 click_record를 기준으로 한다. 입력은 로컬 업무 행 JSONL이며 필드는 `event_id`, `event_type`, `member_id`, `article_id`, `event_time`, `session_id`다. `view`/`cart_add`만 허용하고 시간대가 있는 event_time을 UTC·KST 시각 및 KST 날짜로 변환한다. 상품 ID의 앞자리 0을 보존한다.

`event_id`가 같은 동일 내용은 1건, 내용이 다르면 같은 ID 전체를 오류로 분리한다. 같은 방문의 반복 조회도 event_id가 다르면 별도 이벤트로 보존한다. 방문 수·전환율 집계는 Gold A의 역할이다.

```powershell
python -m pipelines.silver.clicks --input-root <클릭-JSONL-경로> --output-root pipelines/silver/.local/clicks-output
```

결과는 `click_events`, `quarantined_records`, `dq_results`다. 대표 결과 위치는 `<output-root>/silver/clicks/current.json`이며 event_time 대신 `event_time_utc`, `event_time_kst`, `event_date_kst`를 출력한다. 이번 범위에서는 상품·회원 저장소를 추가 조회하거나 존재 여부를 단정하지 않는다.

## 상품 기준정보 Silver

원천 `db/schema/003_product.sql`의 product_design·product_variant 스냅샷을 JSONL 업무 행으로 받는다. 두 테이블의 전체 원천 컬럼을 선택해 `silver_product_design`, `silver_product_variant`로 출력하며 임의의 사이즈·상품 속성을 추가하지 않는다.

- 디자인: product_code당 1행. 정수 필드와 상품 분류 명칭 검사.
- 상품: 문자열 article_id당 1행. product_code로 정상 디자인과 연결한다. 앞자리 0을 보존하고 가격·색상·그래픽 컬럼은 원천 타입을 따른다.
- 같은 키의 동일 내용은 중복 제거하고 다른 내용은 해당 키 전체를 격리한다. 한 입력 묶음은 하나의 스냅샷이며 서로 다른 시점의 기준정보를 함께 넣어 최신값을 임의 선택하지 않는다.
- 디자인이 현재 입력에 없으면 PENDING_REFERENCE, 디자인 오류로 연결할 수 없으면 DEPENDENCY_BLOCKED로 분리한다.
- 상품 기준가격을 주문상품의 실제 unit_price 대신 매출 계산에 사용하지 않는다. DDL에 없는 최솟값이나 article_id 길이를 추측해 검사하지 않는다. 필수 명칭은 비어 있지 않은 문자열로 검사한다.

```powershell
python -m pipelines.silver.products --designs-input <디자인-JSONL-경로> --variants-input <상품-JSONL-경로> --output-root pipelines/silver/.local/products-output
```

결과는 상품 기준정보 2개와 `quarantined_records`, `dq_results`다. 대표 위치는 `<output-root>/silver/products/current.json`이다. 실제 스냅샷 경로·Parquet 입력은 별도 연결하며 이번 버전에서 S3를 읽었다고 가정하지 않는다.

## 공용 로컬 처리

`common.py`에서 JSONL 읽기·기본 타입 검사·클릭/상품 중복 검사·결과 묶음 저장을 공유한다. 거래도 동일한 읽기·저장 함수를 사용하며 기존 CLI 옵션과 출력 경로는 유지한다. 각 검사는 코드 버전(`transactions.v1`, `clicks.v1`, `products.v1`)으로 기록하고 공통 YAML 적용 버전으로 표시하지 않는다.

모든 로컬 결과는 지정 입력 전체의 스냅샷이다. current.json이 가리키는 결과만 읽고, 과거 runs 전체를 합치지 않는다. 파일/저장 실패 시 이전 대표 결과를 보존하며 날짜·상품 부분 병합과 상시 실행 연결은 이번 범위에 포함하지 않는다.
