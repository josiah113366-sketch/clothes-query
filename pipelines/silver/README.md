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
| 입력 | 리뷰 시뮬레이터 `--sink lake`의 `reviews/dt=YYYY-MM-DD/*.jsonl` (`dt`는 UTC 작성일) |
| 출력 | `silver/reviews/dt=YYYY-MM-DD/part-00000.jsonl` (`dt`는 KST 작성일) |
| 한 행의 기준 | `review_id`당 현재 `review_created` 1건 |
| 재처리 | 지정한 KST 날짜별 결과 파일 교체. 같은 범위를 두 번 실행해도 행 수 증가 없음 |
| 중복 | 같은 `review_id`의 재전송/재생성은 `emitted_at`이 가장 늦은 행을 선택. 동시간 충돌은 실패 |
| 보존 | 원문, 별점, 임시 `product_id`, `order_id`, 작성 시각, 전송 시각 |
| 제외 | `member_id`와 `reviews_truth/` 평가 라벨은 운영 분석 출력에 넣지 않음 |

## 미정: 다른 Silver 입력 연결

| 데이터 | 현재 연결 상태 | 구현 전 확인할 것 |
|---|---|---|
| 주문·주문상품·결제 CDC | 가상 입력용 계산 규칙 구현, 실제 Bronze 미연결 | 실제 Bronze 컬럼, CDC 순서·삭제 처리, 중복 식별값 |
| 클릭 이벤트 | `main`에 실제 Bronze 출력 없음 | 세션·상품 키, 이벤트 시각과 중복 기준 |
| 상품 기준정보 | 리뷰의 `product_id`가 아직 임시 값 | `article_id`·`product_code` 연결 방식과 스냅샷 위치 |
| 리뷰 AI 분석 결과 | 전달 스키마 없음 | `review_id`, 속성, 감성, 모델 버전, 분석 시각 |

이 표는 구현 상태를 기록한다. 미정 항목의 키나 집계 기준을 임의로 확정하지 않는다.

## 실행

저장소 루트에서 실행한다. `--input-root`와 `--output-root`는 로컬 폴더 또는 `s3://버킷/접두사`다. S3를 쓸 때만 `boto3`와 읽기·쓰기 권한이 필요하다.

```powershell
python -m pipelines.silver.reviews --input-root review-simulator/.local/lake --output-root pipelines/silver/.local/lake --start-date 2026-10-08 --end-date 2026-10-08
```

입력은 운영 리뷰 `reviews/`만 읽고, 평가용 `reviews_truth/`는 사용하지 않는다. `product_id`는 임시 ID여서 주문·상품 지표와 연결하지 않는다.

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

이 함수는 제공된 입력 안에서만 중복·충돌을 확인한다. 이전 실행에서 이미 저장한 결제와의 충돌, 저장 결과 교체·대상 외 결과 보존, Gold A의 품질 상태 사용은 실제 입출력 연결 작업에서 구현한다.
