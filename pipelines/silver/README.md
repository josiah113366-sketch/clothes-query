# Silver 입력·출력 현황

## 결정: 회원 현재 상태 (`members_current`)

| 항목 | 기준 |
|---|---|
| 입력 | `bronze/members-events/year=YYYY/month=MM/day=DD/*.json` 전체 이력. 폴더 날짜는 UTC Kafka 수집일 |
| 출력 | 로컬 `silver/members_current/as_of=YYYY-MM-DD/current.json`이 가리키는 정상·격리·품질 결과 묶음 |
| 한 행의 기준 | 해당 UTC 수집일까지의 `member_id`당 최신 상태 1행 |
| 중복·순서 | 동일 내용·원천 시각은 중복 제거. 오류 없는 회원만 더 큰 `__source_ts_ms` 선택. 오류·동시각 충돌이 있는 회원은 전체 보류 |
| 재처리 | 지정 날짜까지 전체 이력을 다시 읽어 결과 묶음 저장 후 해당 `as_of`의 current.json 교체 |
| 제외 | 이름·이메일·전화번호 등 PII. Source 커넥터가 입수에서 제외하며 Silver도 필요한 필드만 선택 |

```powershell
python -m pipelines.silver.members --input-root <로컬 또는 s3://버킷/bronze/members-events> --output-root pipelines/silver/.local/lake --through-date 2026-10-14
```

`as_of`는 실행 시각이 아니라 **어느 UTC 수집 날짜까지 읽었는지**를 뜻한다. 이전 날짜 결과를 다시 만들더라도 최신 날짜 결과를 덮어쓰지 않는다. 현재 확인한 실제 파일은 초기 스냅샷(`__op=r`)뿐이다. `c/u` 선택 규칙은 합성 입력으로만 검증했으며 실제 변경 이벤트가 오면 다시 확인해야 한다. 첫 버전은 로컬 Silver 출력만 지원한다.

## 결정: 현재 구현된 리뷰 입력

| 항목 | 기준 |
|---|---|
| 입력 | 리뷰 시뮬레이터 `--sink lake`의 `reviews/year=YYYY/month=MM/day=DD/*.jsonl` (UTC 작성일) |
| 출력 | `silver/reviews/scopes/<시작일>_<종료일>/current.json`이 가리키는 정상·격리·품질 묶음. 정상 파일은 실행 폴더 안의 `year/month/day/part-00000.jsonl` (KST 작성일) |
| 한 행의 기준 | `review_id`당 현재 `review_created` 1건 |
| 재처리 | 같은 KST 요청 범위를 다시 계산해 해당 범위의 current.json 교체. 과거 실행을 합치지 않음 |
| 중복 | 오류 없는 review_id만 최신 emitted_at 선택. 오류·동시간 충돌은 해당 리뷰 전체 보류 |
| 보존 | 원문, 별점, 원천 `product_id`, `order_id`, 작성 시각, 전송 시각 |
| 제외 | `member_id`와 `reviews_truth/` 평가 라벨은 운영 분석 출력에 넣지 않음 |

## 미정: 다른 Silver 입력 연결

| 데이터 | 현재 연결 상태 | 구현 전 확인할 것 |
|---|---|---|
| 주문·주문상품·결제 CDC | `origin/sim/cdc-orders` 설정의 펼쳐진 JSONL 형식 지원. 로컬 합성 CDC로 검증 | 실제 S3 다운로드 입력 검증, LSN 및 행별 Kafka 위치, 동시각 변경 순서 |
| 클릭 이벤트 | 6개 필드・UTC Z 시각 수용. 원격 CDC 브랜치에 Bronze 설정 있음 | 실제 출력과 입력 완전성 확인 |
| 상품 기준정보 | 생성기는 H&M article_id를 product_id로 읽을 수 있고, 대체 임시 상품 모드도 있음 | 실제 입력의 상품 키 출처·상품 스냅샷 위치 확인 |
| 리뷰 AI 분석 결과 | Gold A는 review_id/aspect/score CSV와 모델 버전을 지원 | 실제 모델 출력・완료/실패 목록 연결 |

이 표는 구현 상태를 기록한다. 미정 항목의 키나 집계 기준을 임의로 확정하지 않는다.

## 실행

저장소 루트에서 실행한다. `--input-root`와 `--output-root`는 로컬 폴더 또는 `s3://버킷/접두사`다. S3를 쓸 때만 `boto3`와 읽기·쓰기 권한이 필요하다.

```powershell
python -m pipelines.silver.reviews --input-root review-simulator/.local/lake --output-root pipelines/silver/.local/lake --start-date 2026-10-08 --end-date 2026-10-08
```

입력은 운영 리뷰 `reviews/`만 읽고, 평가용 `reviews_truth/`는 사용하지 않는다. 원천 `product_id`를 보존하며 실제 상품 키와의 대응을 확인한 뒤 거래 지표에 연결한다.

입력과 출력의 날짜 폴더 모양을 year/month/day로 통일한다. Bronze는 UTC 작성일, Silver는 KST 작성일 기준이다. KST 시작일의 전날 UTC부터 종료일 UTC까지 검색하고 KST 작성일로 행을 선택한 뒤 review_id로 중복 처리한다. 검색 범위에서 운영 JSONL 파일을 하나도 찾지 못하면 기존 출력을 덮어쓰지 않고 실패한다. 명시적으로 비어 있는 입력 파일이나 읽은 파일 중 대상 KST 리뷰가 없는 경우는 정상 0건 결과로 처리한다.

Gold A는 요청 범위의 current.json을 읽고 status·dq_results와 정상 파일 경로를 함께 사용하도록 수정해야 한다. 기존 dt 입력이나 고정 날짜 파일 경로와는 바로 연결되지 않는다. Gold A 수정과 기존 결과 파일 이동은 이번 범위에 포함하지 않는다.

## 결정: 거래 Silver 계산 규칙

`transactions.py`의 `build_silver(orders, order_items, payments)`를 사용한다.

입력은 업무 행 또는 `sim/cdc-orders`의 펼쳐진 CDC JSONL이다. CDC 주문은 `__source_ts_ms`, 기존 업무 행은 `updated_at` 순서로 복원한다. CDC 시각이 같은데 업무 내용이 다르면 해당 주문 전체를 보류하며, 같은 주문에 두 입력 방식을 섞어 정렬하지 않는다. 결과는 `orders_current`, `order_status_history`, `silver_order_items`, `payment_attempts`다. 시각은 UTC와 KST를 함께 남긴다. source.ts_ms는 총순서 식별자가 아니므로 동일 시각 상충을 해소하는 LSN 연결은 남아 있다.

### 거래 오류 처리와 반환값

`build_silver()`는 정상 상세 4개에 `quarantined_records`, `dq_results`, `impact_candidates`를 더한 딕셔너리를 반환한다. 함수 자체는 파일을 저장하거나 이전 실행의 격리 상태를 갱신하지 않는다.

| 결과 | 내용 |
|---|---|
| `quarantined_records` | 데이터셋, 입력 목록의 행 번호(1부터), 업무 키, 주문 키, 오류 필드·사유·구분, `check_version` |
| `dq_results` | 원천 데이터셋별 입력·정상 채택·격리·중복·충돌·대기 건수, 출력별 행 수, 영향 주문·입력 행, PASS/INCOMPLETE |
| `impact_candidates` | 정상·오류 후보 전체의 데이터셋・업무 키・주문/상품/세션・관련 업무 시각・원본 파일/줄 참조. 회원 식별값・리뷰 원문은 복사하지 않음. Gold A 영향 범위 계산용이며 정상 업무 행 수에 더하지 않음 |

- 잘못된 행은 분리하고 다른 정상 행을 처리한다. 일반 프로그램 오류까지 잡아서 숨기지 않는다.
- 같은 결제·주문상품 키에 다른 업무 내용이 있으면 그 키의 모든 행을 분리한다. 같은 키의 한 행이 형식 오류인 경우도 다른 행만 임의로 채택하지 않는다.
- 주문의 일부 변경에 오류·동시각 충돌이 있으면 해당 주문 전체를 보류해 이전 상태를 최신 상태로 잘못 내보내지 않는다. 관련 주문상품·결제는 `DEPENDENCY_BLOCKED`로 남긴다.
- 현재 입력에 주문이 없는 항목은 `PENDING_REFERENCE`다. 잘못된 결제라고 확정하거나 실제 주문 저장소를 자동 조회하지 않는다. 주문을 포함한 입력으로 재실행해야 한다.
- 실패 코드 누락・미등록・성공 결제의 실패 코드, 0 이하 금액・단가를 분리한다. 실패 결제는 원천 DDL의 5개 코드만 허용한다. 미등록 코드 허용과 Gold B UNKNOWN 분류는 합의 전 제안이며 실행하지 않는다. YAML의 전체 검사기는 연결하지 않았다.
- `input_count = accepted_count + duplicate_count + quarantined_count`다. accepted_count는 중복 제거 후 채택한 입력 기록 수이며 주문 현재 상태 출력 수와 다를 수 있다. 오류는 행당 첫 사유를 기록하고, conflict_count/pending_count는 격리 행 수의 부분집합이다.
- 오류·대기 정보가 있는 데이터셋은 INCOMPLETE다. 후속 Gold A/저장 코드는 **모든 dq_results를 확인**해 영향 범위를 완전한 결과로 표시하지 않아야 한다. 정상 출력이 존재한다는 것만으로 전체 처리 완료로 판단하지 않는다.
- `check_version=transactions.v4`는 이 계산 코드의 검사 버전이다. 공통 YAML 규칙 버전을 적용했다고 표시하지 않는다. 원본 파일/줄・실행 ID를 남기지만 파일 이름의 시작 offset에 줄 번호를 더해 Kafka 행 offset을 추정하지 않는다.

### 실패 코드 검사: 현재 기준과 제안

현재 FAILED는 INSUFFICIENT_BALANCE・CARD_LIMIT_EXCEEDED・CARD_DECLINED・PG_TIMEOUT・PG_ERROR만 허용한다. 누락/빈 문자열/공백은 MISSING_FIELD, 비문자열은 TYPE_MISMATCH, 비어 있지 않은 미등록 문자열은 INVALID_VALUE다. SUCCESS의 코드는 NULL이어야 한다. 코드의 대소문자/공백을 임의로 보정하거나 UNKNOWN으로 채우지 않는다.

미등록 코드는 격리하고 결제 DQ를 INCOMPLETE로 남긴다. 정상 실패 코드는 정상 payment_attempts에 남으며 업무상 실패 자체를 데이터 오류로 취급하지 않는다. payments DQ에는 failure_code_policy=source-ddl-five-codes.v1을 기록한다. 영향 범위와 Gold A 처리에는 기존 품질/보류 규칙을 적용한다.

**제안・미적용:** 새 PG 코드가 도입될 때 실제 실패를 집계에서 누락하지 않도록 비어 있지 않은 미등록 문자열을 받아 원본 코드를 보존하고, Gold B의 원인 분류만 UNKNOWN으로 두는 안이다. 누락/비문자열까지 허용하는 안이 아니다. 오타/비정상 코드 포함 위험과 Gold B 정책을 공동 합의한 뒤 소비 규칙 버전을 함께 변경해야 한다. 원천 DDL 변경 여부는 별도이며 현재는 5개 허용 기준을 유지한다. 공통 계약 원본은 docs/data-contracts 브랜치의 docs/contracts/README.md와 format_rules.yaml에 있다.

### 주문상품 금액 합계 검사

`build_silver(..., input_complete=True)` 또는 CLI의 `--input-complete`로 전체 입력 준비를 확인한 실행에서 검사한다. 주문별로 중복 제거한 주문상품의 `quantity × unit_price`를 합산해 현재 주문의 total_amount와 비교한다. 현재 상품 기준정보 가격을 사용하지 않는다. 현재 원천 계약의 할인・배송비 없는 상품 금액 기준이며, 향후 별도 금액 항목 도입 시 계약부터 수정한다.

| 조건 | dq_results의 주문별 amount_checks 상태 | 처리 |
|---|---|---|
| 입력 완전성 미확인 | UNVERIFIED | 합계 판정 생략. 이 금액 검사를 통과한 것으로 표현하지 않음 |
| 주문상품 자체 오류・충돌 | ITEM_ERROR | 정상 상품만 부분 합산하지 않고 주문과 연결 결과를 보류 |
| 주문상품 없음 | PENDING_REFERENCE | 0원으로 비교하지 않고 MISSING_ORDER_ITEMS 기록・연결 보류 |
| 합계 일치 | PASS | 정상 결과 유지 |
| 합계 불일치 | MISMATCH | ORDER_TOTAL_MISMATCH 기록, 주문 현재 상태/이력과 관련 항목・결제를 정상 결과에서 보류 |

amount_checks는 orders 품질 결과 안에 남기며 새 데이터셋을 만들지 않는다. 합계 검사 시 order_total_amount・item_total_amount・amount_difference(상품 합계 - 주문 총액)를 남기고, 불일치 오류 기록에도 금액과 기존 파일/줄 참조를 보존한다. 기존에 발견한 행 오류는 다른 오류로 덮어쓰지 않는다. 입력 완전성 미확인은 금액 일치와 다르며 품질 PASS 자체도 원천 완전성을 증명하지 않는다.

주문당 성공 결제 1건 제한과 성공 결제 amount=주문 total_amount 검사는 기존대로 유지한다. 세 값이 맞는지 각각 검사하며 어느 금액도 임의로 수정하지 않는다. 오류 수정 후 전체 입력으로 Silver를 다시 실행하고 Gold A --scope-aware를 실행해 복구한다. 현재 Gold A는 주문 자체 오류이면 관련 거래/퍼널 묶음 전체를 보류한다. 별도 리뷰 작업까지 중단하지 않는다.

이 함수는 제공된 입력 안에서만 중복·충돌을 확인한다. 이전 실행에서 이미 저장한 결제와의 충돌, 날짜·상품 부분 병합, Gold A의 품질 상태 사용은 후속 연결 작업에서 다룬다. 아래 로컬 실행기는 제공한 입력 전체의 결과 묶음을 저장한다.

### 문서 기준 거래 JSONL 실행

문서의 업무 행 또는 내려받은 Bronze CDC JSONL을 읽어 결과를 저장한다. 세 입력 모두 파일 또는 폴더를 직접 지정한다. 폴더는 하위 `.json`/`.jsonl` 전체를 읽으며, 파일은 한 줄에 객체 하나다. 업무 시각은 시간대가 있는 ISO 문자열(UTC `Z` 포함)을 사용한다. S3 직접 읽기는 아직 지원하지 않는다.

펼쳐진 CDC는 `__op`, 정수 `__source_ts_ms`를 검사한다. 주문은 r/c/u, 결제・주문상품은 r/c를 허용한다. 실시간 `__source_snapshot=null`을 허용하고 snapshot은 `__op=r`로 판단한다. 삭제・결제 UPDATE・before/after 봉투는 추정해서 처리하지 않는다. source.ts_ms가 다른 주문 변경은 정렬하며, 현재 상태와 상태 이력에 해당 원천 시각을 남긴다.

```powershell
python -m pipelines.silver.transactions --orders-input <주문-JSONL-경로> --order-items-input <주문상품-JSONL-경로> --payments-input <결제-JSONL-경로> --output-root pipelines/silver/.local/transactions-output
```

- `orders`: `order_id`, `member_id`, `session_id`, `status`, `status_reason`, `total_amount`, `ordered_at`, `updated_at`.
- `order_items`: `order_item_id`, `order_id`, `article_id`, `quantity`, `unit_price`.
- `payments`: `payment_id`, `order_id`, `attempt_no`, `method`, `pg`, `amount`, `status`, `failure_code`, `requested_at`, `completed_at`.

정상 결과 4개와 격리・품질・영향 후보 결과 3개를 `<output-root>/silver/transactions/runs/run-.../`에 JSONL로 쓴다. 일곱 파일이 모두 저장된 뒤 `<output-root>/silver/transactions/current.json`을 교체한다. current.json에는 원본 파일 목록, 실행 ID, 입력・출력 건수, 품질 상태, 실제 결과 파일 경로가 있다.

거래와 클릭 CLI의 `--input-complete`는 필요한 전체 이력과 참조 입력을 준비했다는 **실행자의 명시적 확인**을 manifest의 `input_completeness=DECLARED_COMPLETE`로 남긴다. 생략하면 UNVERIFIED다. 이것은 Kafka watermark 자동 검증이나 원천 입수 완전성의 기술적 증명이 아니다. 토픽별 도착 범위 확인 후에만 사용한다. Gold A의 `--scope-aware` 실행은 이 확인을 요구한다. 기존 시험 주문・옛 회원 데이터의 포함 여부도 입력을 준비할 때 정하며 자동 삭제/제외하지 않는다.

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


## 회원·리뷰 오류 분리와 완료 결과 읽기 (최신 기준)

위 두 처리의 기존 고정 파일 직접 읽기는 다음 manifest 방식으로 대체한다. CLI 입력 옵션·반환 건수와 정상 행 컬럼은 유지하지만 **결과를 읽는 위치는 변경**된다. 예전 결과는 삭제하지 않는다.

| 대상 | 대표 결과 위치 | 결과 파일 |
|---|---|---|
| 회원 | `<output-root>/silver/members_current/as_of=YYYY-MM-DD/current.json` | members_current.jsonl, quarantined_records.jsonl, dq_results.jsonl |
| 리뷰 | `<output-root>/silver/reviews/scopes/YYYY-MM-DD_YYYY-MM-DD/current.json` | quarantined_records.jsonl, dq_results.jsonl, 실행 폴더 안의 KST year/month/day/part-00000.jsonl |

1. 필요한 as_of 또는 정확한 리뷰 요청 범위의 current.json을 읽는다.
2. status와 outputs의 dq_results.jsonl을 확인한다. PASS는 읽은 입력의 검사 통과이며 원천 입수의 완전성을 증명하지 않는다.
3. outputs가 가리키는 정상 파일만 읽는다. runs/ 또는 scopes/ 전체를 합치면 과거 실행·중첩 날짜가 중복된다.
4. INCOMPLETE이면 정상 데이터는 존재할 수 있지만 해당 범위를 완전한 결과로 표시하지 않는다. Gold A의 실제 차단·표시 처리는 후속 구현이다.

- 회원·리뷰의 필드 오류·JSON 파싱 오류를 행별로 격리한다. 키를 아는 오류는 같은 키의 모든 입력을 보류한다. 같은 원천/발행 시각 충돌은 과거 버전에서도 검사한다.
- 회원은 오류가 있는 회원의 과거 ACTIVE 상태를 최신으로 대체 출력하지 않는다. 리뷰도 오류 있는 최신 리뷰 대신 과거 리뷰를 조용히 선택하지 않는다.
- 식별 키를 읽을 수 없는 오류는 unknown_key_error_count로 남긴다. 파일·줄 번호로 원본을 찾으며 원문이나 회원 개인정보를 격리 결과에 복사하지 않는다.
- dq_results: input_count = accepted_count + duplicate_count + quarantined_count. accepted_count는 중복 제외 후 채택한 정상 버전 수이며 최신 상태 출력 수와 다르다. superseded_count는 최신이 아닌 정상 버전 수다.
- 리뷰는 읽은 모든 UTC 폴더에서 키를 검사한 뒤 KST 범위를 선택한다. outside_range_count는 범위 밖의 정상 최신 리뷰 수다. 날짜를 모르는 오류도 있으므로 오류가 있으면 요청 범위 전체를 affected_scope=REQUESTED_RANGE로 표시한다.
- 파일 없음·읽기/인코딩 실패·예상하지 못한 프로그램 오류는 계속 실행 실패다. 정상적인 빈 입력과 구분한다.
- 모든 결과 파일 저장 후 current.json 한 개를 교체한다. 로컬은 원자 교체, 리뷰 S3 출력은 단일 객체 PUT이다. 중간 실패 때 이전 manifest를 유지하며 미공개 파일은 소비하지 않는다.
- 동시 실행 잠금·과거 실행 정리·서로 다른 리뷰 범위 간 결과 병합·날짜/상품 부분 재처리는 제공하지 않는다. 서로 겹치는 범위를 여러 개 읽지 말고 소비할 범위를 명시한다.
- 회원 S3 출력은 기존처럼 지원하지 않는다. 리뷰 S3 입출력은 유지하지만 이번 검증에서 실제 AWS 요청은 실행하지 않는다.
- 검사 버전은 members.v1/reviews.v1이며 공통 format_rules.yaml 실행 연결은 포함하지 않는다.
