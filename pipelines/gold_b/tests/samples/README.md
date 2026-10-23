# Gold B 샘플 메시지

Kafka에서 읽은 메시지 한 개 = 배열의 원소 하나다. 2단계(형식 검사)·3단계(뷰)·4단계(적재 잡) 확인에 같이 쓴다.

| 파일 | 내용 |
|---|---|
| `payments.json` | 결제 토픽. 정상·PG 원인 실패·고객 원인 실패·재시도·중복·내용이 바뀐 두 쌍(상태가 다름, 금액만 다름)·모르는 실패 코드·필드 누락·이름 변경·`PG_C`·오류 여러 개·파싱 실패·`op u` |
| `other_topics.json` | `clickstream`, `orders`, `order-items`, `members-events`, `reviews.raw` 각각 정상 1개 이상 + 오류 예. `reviews.raw`는 형식 검사를 하지 않아서(2026-10-23 결정) 오류 예도 기대 오류가 없다 |
| `payment_updates.json` | 결제 수정(`op u`) 시나리오 (2026-10-23). 정상 c→u, 같은 변경 시각, 잘못된 최신 u, 재처리 복구, 잘못된 u 뒤 새 정상 u, 순서 이상, 두 파티션, `completed_at` 시간 폴더 이동, 잘못된 `__source_ts_ms`, 재검사 실패, 두 번 쌓기, 같은 `loaded_at`. 형식 검사·정리 뷰 시험만 쓰고 적재·재처리 시험의 건수에는 넣지 않는다 |
| `payment_states.json` | 결제 정리 뷰의 기대 결과. 재검사 줄(`rechecks`)과 결제마다 `payment_states` 한 줄(`states`) |

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
| `expected.note` | 설계에 없어 아직 정하지 않은 점 |

모든 메시지는 형식과 상관없이 `topic_messages`에 한 줄씩 쌓인다. 결제마다의 뷰 결과는 메시지가 아니라 결제 단위라 `payment_states.json`에 따로 적는다 (2026-10-23 전에는 메시지마다 `payment_attempts`, `failure_cause`, `payment_conflicts`를 적었다).

## `payment_states.json` 모양

`tests/test_payment_states.py`가 결제 샘플 전부를 평소 적재 잡처럼 Kafka 시각 30초 뒤에 쌓고, `rechecks`의 줄을 더한 뒤 뷰 SQL을 돌려 비교한다.

| 키 | 뜻 |
|---|---|
| `rechecks[]` | 같은 Kafka 위치를 나중에 다시 검사한 결과 (재처리, 적재 잡이 다시 쌓음). `sample`(메시지 이름), `rule_version`(새 규칙 버전. `null`이면 지금 규칙표로 다시 검사), `loaded_at`, `errors`(새 규칙이 내는 오류. 비어 있으면 통과) |
| `states[]` | 결제마다 `payment_states` 한 줄. `latest`(마지막 이벤트인 메시지 이름), `event_count`(Kafka 위치 수), `hold_reason`(`null`, `MULTI_PARTITION`, `ORDER_ANOMALY`, `INVALID_LATEST`), 보류되지 않으면 `failure_cause`(`payment_attempts`의 실패 원인), 필요하면 `rule_version` |
| `unlinked` | 키(`payment_id`)를 몰라 결제와 잇지 않는 오류 메시지 |

## 지킬 것

- 개인정보 값은 넣지 않는다. 회원 PII 오류 샘플은 값 대신 `<redacted>`, 리뷰 본문은 `<본문 생략>`이다.
- ID는 `00000000-4000-8000-0000-…` 꼴의 가짜 UUID다.
- 기대 결과의 `reason`이 `null`인 것은 설계에 사유가 없는 경우다 (`note` 참고).
