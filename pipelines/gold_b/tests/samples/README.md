# Gold B 샘플 메시지

Kafka에서 읽은 메시지 한 개 = 배열의 원소 하나다. 2단계(형식 검사)·3단계(뷰)·4단계(적재 잡) 확인에 같이 쓴다.

| 파일 | 내용 |
|---|---|
| `payments.json` | 결제 토픽. 정상·PG 원인 실패·고객 원인 실패·재시도·중복·충돌 두 쌍(상태가 다름, 금액만 다름)·모르는 실패 코드·필드 누락·이름 변경·`PG_C`·오류 여러 개·파싱 실패·`op u` |
| `other_topics.json` | `clickstream`, `orders`, `order-items`, `members-events`, `reviews.raw` 각각 정상 1개 이상 + 오류 예. `reviews.raw`는 형식 검사를 하지 않아서(2026-10-23 결정) 오류 예도 기대 오류가 없다 |

## 원소 모양

| 키 | 뜻 |
|---|---|
| `name` | 샘플 이름 (테스트에서 부를 때) |
| `description` | 무엇을 보여 주는 샘플인가 |
| `kafka` | 메시지와 같이 오는 Kafka 정보: `topic`, `partition`, `offset`, `timestamp`(UTC), 필요하면 `key` |
| `value` | 메시지 값 (JSON). CDC 토픽은 봉투가 풀린 평평한 모양 + `__op`, `__source_ts_ms`, `__source_snapshot` |
| `value_raw` | 값이 JSON이 아닐 때 원문 문자열 (`value` 대신) |
| `expected.payment_events` | `payment_events`에 쌓이는가 |
| `expected.malformed` | `malformed_events`에 쌓일 오류 목록 (`field`, `reason`). 비어 있으면 형식 정상 |
| `expected.payment_attempts` | (결제만) 정리 뷰 `payment_attempts`에 남는가 |
| `expected.failure_cause` | (결제만) 뷰의 실패 원인 분류 |
| `expected.payment_conflicts` | (충돌만) `payment_conflicts`의 `conflict_fields`. 원장에 없는 필드(`amount` 등)만 다르면 `[payment_content_hash]` |
| `expected.note` | 설계에 없어 아직 정하지 않은 점 |

모든 메시지는 형식과 상관없이 `topic_messages`에 한 줄씩 쌓인다.

## 지킬 것

- 개인정보 값은 넣지 않는다. 회원 PII 오류 샘플은 값 대신 `<redacted>`, 리뷰 본문은 `<본문 생략>`이다.
- ID는 `00000000-4000-8000-0000-…` 꼴의 가짜 UUID다.
- 기대 결과의 `reason`이 `null`인 것은 설계에 사유가 없는 경우다 (`note` 참고).
