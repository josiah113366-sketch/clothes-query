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
