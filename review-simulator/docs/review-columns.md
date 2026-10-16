# 리뷰 생성 컬럼 (초안 v0, 2026-10-13)

**확정 (2026-10-13, lemin):** product_id, product_name, category, member_id 는 나중에 order 테이블이 생기면 거기서 가져온다. 그 전까지는 시뮬레이터가 만든 **임시 값**을 쓴다(아래 🕒 표시).

**확정 (2026-10-13, lemin):** title(제목) 컬럼은 뺀다. 국내 쇼핑몰 리뷰에는 보통 제목 칸이 없다.

표시: ✅ 지금 코드에 있음 / ➕ 추가 제안 / ❓ 결정 필요

**확정 (2026-10-14, lemin):** 제안했던 emitted_at, option_size, option_color, purchased_at, has_photo 를 모두 넣는다. 스키마 `review.v2`.

## 1. 식별·메타

| 컬럼 | 타입 | 예 | 상태 | 설명 |
|---|---|---|---|---|
| schema_version | string | review.v2 | ✅ | 메시지 구조 버전 (v2: 아래 2026-10-14 컬럼 추가) |
| event_id | uuid | … | ✅ | 전송 단위 ID (중복 제거용) |
| event_type | string | review_created | ✅ | 작성만 (수정·삭제는 추후 고려사항) |
| review_id | string | R-0a39da943300 | ✅ | 리뷰 ID |

## 2. 시간

| 컬럼 | 타입 | 예 | 상태 | 설명 |
|---|---|---|---|---|
| created_at | timestamp(ISO, +09:00) | 2026-10-13T16:02:05+09:00 | ✅ | 리뷰 작성 시각 (가상 시계) |
| emitted_at | timestamp(ISO, UTC) | 2026-10-14T07:16:44+00:00 | ✅ | 실제로 내보낸 시각. 과거 날짜를 만들면 created_at 과 달라짐 (2026-10-14 확정) |

## 3. 상품

| 컬럼 | 타입 | 예 | 상태 | 설명 |
|---|---|---|---|---|
| product_id | string | W-0006 | ✅🕒 | Kafka 메시지 키. 임시 값, 추후 order 테이블에서 |
| product_name | string | OO 니트 | ✅🕒 | 임시 값(AI Hub 상품명), 추후 order 테이블에서 |
| category | string | 여성의류 | ✅🕒 | 임시: 여성의류/남성의류/패션슈즈/잡화. 실제 상품 데이터에서는 받지 않으므로 null(2026-10-16, 상품 분류는 상품 테이블 조인으로) |
| option_size | string | M | ✅🕒 | 구매 옵션 사이즈. 의류 XS~XXL, 신발 225~280(mm), 잡화 FREE. 임시 값, 추후 주문 데이터에서 (2026-10-14 확정) |
| option_color | string | 블랙 | ✅🕒 | 구매 옵션 색상. 임시 값, 추후 주문 데이터에서 (2026-10-14 확정) |

## 4. 회원·주문 (결제/회원 시뮬레이터와 연결 지점)

| 컬럼 | 타입 | 예 | 상태 | 설명 |
|---|---|---|---|---|
| member_id | string | C-9ba27683d5 | ✅🕒 | 임시 무작위 값, 추후 order 테이블에서 |
| order_id | string | O-1a2b3c4d5e6f | ✅ | 어떤 주문의 리뷰인지. 주문 모드(`--source orders`)에서만 값이 있고 무작위 모드는 null. 정답 이벤트에도 같이 넣는다 (2026-10-14) |
| purchased_at | timestamp(ISO) | 2026-10-05T02:58:08+09:00 | ✅ | 구매(결제) 시각 = 주문의 paid_at. 주문 모드에서만 값이 있고 무작위 모드는 null (2026-10-14 확정) |
| age_group | string | 30대 | ✅🕒 | 작성자 연령대. 임시 값, 추후 member 테이블에서 member_id 와 같이 |

## 5. 리뷰 내용

| 컬럼 | 타입 | 예 | 상태 | 설명 |
|---|---|---|---|---|
| rating | int 1~5 | 2 | ✅ | |
| text | string | … | ✅ | Bedrock 생성 본문 |
| has_photo | bool | true | ✅ | 포토 리뷰 여부. 이미지는 만들지 않고 표시만, 약 30% (2026-10-14 확정) |
| source | string | simulator | ✅ | 실제 데이터와 구분. `rsim inject` 로 직접 넣은 리뷰는 `manual`(review_id 도 `M-` 로 시작, 2026-10-16) |

## 6. 정답 (레이크 `reviews_truth/`, Kafka `reviews.truth`. 실제 데이터에는 없음, 학습·채점용)

**확정 (2026-10-13, lemin):** 정답은 리뷰 메시지에 넣지 않고 별도 토픽으로 보낸다. 학습용은 운영 흐름과 다른 방향으로 소비한다.
키 = review_id. review_id, created_at, product_id, category, rating, text 를 함께 담아 이 토픽만으로 학습 데이터가 된다.


| 컬럼 | 타입 | 예 | 상태 | 설명 |
|---|---|---|---|---|
| aspects | array | [{aspect, sentiment, source}] | ✅ | 정답 라벨 = 명세 속성(source=spec) + 검수 모델이 찾은 추가 속성(source=verifier). 2026-10-14 p5.4 |
| spec_aspects | array | [{aspect, sentiment}] | ✅ | 명세에서 의도한 속성·감성만 (p5.4 추가) |
| order_id | string | O-1a2b3c4d5e6f | ✅ | 리뷰와 같은 값 (2026-10-14, review_truth.v2) |
| incident_id | string | INC-001 | ✅ | 이상 상황으로 만든 리뷰면 ID |
| generator.model_id / prompt_version / style / length | | | ✅ | 생성 조건 기록 (재처리·품질 비교용) |

## 결정 내역 (2026-10-13~14, lemin)

- 정답 라벨 → 별도 토픽 `reviews.truth` (학습용은 운영 흐름과 다른 방향으로 소비)
- title 컬럼 → 뺌 (국내 쇼핑몰 리뷰에는 제목 칸이 없음)
- product_id, product_name, category, member_id → 임시 값, 나중에 order 테이블에서
- 체형 정보(키·몸무게·평소 사이즈) → 넣지 않음
- 작성 채널(platform: 앱/웹) → 넣지 않음
- age_group → 넣음. 임시 값으로 채우고, 나중에 member 테이블에서 member_id 와 같이 가져옴
- (2026-10-14) order_id 추가, emitted_at·option_size·option_color·purchased_at·has_photo 확정 → review.v2 / review_truth.v2(order_id)
- (2026-10-14) 리뷰 저장: S3 날짜별 경로(`reviews/year=YYYY/month=MM/day=DD/`, UTC. 2026-10-16 `dt=` 에서 변경). RDS 에는 넣지 않음

## 남은 결정

- 없음 (2026-10-14: 제안 컬럼 모두 확정)

## 추후 고려사항

- 리뷰 수정·삭제 이벤트 (`review_updated` / `review_deleted`): 지금은 작성(`review_created`)만 보낸다.
  넣게 되면 같은 review_id 로 이벤트를 보내고, 컨슈머는 최신 상태로 덮어쓰는 방식(upsert)을 검토.
