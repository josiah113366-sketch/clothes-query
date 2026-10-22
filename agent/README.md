# agent/

탐지 규칙, 이상 이력, 조사 에이전트, 승인 흐름을 담는 영역이다(`docs/BRANCHES.md`의 `agent`).
조사 에이전트는 읽기 전용이고, 재처리는 사람이 승인한 뒤 Airflow가 실행한다.

## 지금 있는 것 (초안)

| 폴더 | 내용 | 상태 |
|---|---|---|
| `reliability/` | 장부를 믿어도 되는지 보는 쿼리 3개(누락·중복·멈춤)와 시험 코드 | 초안. Athena에서는 아직 실행하지 않음 |
| `prototype/` | 탐지 규칙을 가짜 데이터로 시험한 프로토타입 | 초안. 실제 데이터로 측정하지 않음 |

## 의존하는 것

- Gold B 원장(`gold_b.payment_events`, `topic_messages`, `bronze_lag_snapshots`, `malformed_events`)과 정리 뷰. 설계는 Gold B 담당자의 문서를 따른다.
- 정답표(`ground_truth/incident_log/`, JSON)는 조사 에이전트가 읽지 못하는 별도 위치다.

## 아직 없는 것

탐지 잡, 조사 에이전트, 승인 화면은 아직 만들지 않았다(→ `agent/skeleton` 브랜치 이후).
