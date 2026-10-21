# agent/tools

조사 에이전트가 쓰는 **읽기 전용 도구** 초안이다. 에이전트는 SQL을 직접 쓰지 않고, 아래 도구 중 하나를 골라 부른다.
도구는 SQL을 만들고, **울타리(`guard.py`)를 통과한 SELECT만** 실행한다.

## 쉬운 설명

에이전트에게 데이터 창고 열쇠를 통째로 주는 대신, **질문 11개짜리 조회 창구**를 준다.
- 창구에 없는 질문은 못 한다.
- 창구는 정해진 표(원장 4개, 정리 뷰 2개, 이상 이력, 재처리 기록)만 읽는다.
- 정답표 폴더(`ground_truth/`)와 원문 일부(`raw_sample`)는 읽지 못한다.
- 한 번에 6시간 범위, 200줄까지만 돌려준다.

## 도구 11개

| 도구 | 묻는 것 | 읽는 곳 | 어느 시나리오 |
|---|---|---|---|
| `payment_summary` | PG별 결제 시도·실패·원인별 실패 수 | `payment_attempts` 뷰 | 1 PG 장애 |
| `payment_failure_codes` | 실패 코드가 어디로 쏠렸나 | `payment_attempts` | 1 |
| `payment_retry_impact` | 장애를 겪은 주문 수, 재시도 수 | `payment_attempts` | 1 |
| `ingest_volume` | 토픽별 유입 메시지 수 | `topic_messages` | 2 트래픽 폭주 |
| `bronze_lag` | Bronze 지연, 처리 위치 멈춤, 커넥터 상태 | `bronze_lag_snapshots` | 2 |
| `malformed_summary` | 토픽·사유별 깨진 메시지 수(현재 규칙 버전만) | `malformed_messages` 뷰 | 3 스키마 오염 |
| `malformed_fields` | 어느 필드가 왜, 언제부터, 가장 이른 offset | `malformed_events` | 3 |
| `ledger_reliability` | 원장을 믿어도 되나(누락·중복·멈춤) | `topic_messages` 등 | 모두 |
| `duplicate_success_orders` | 성공 결제가 2건 이상인 주문 (적재 시각 기준, 결제 시각 기준으로도 가능) | `payment_attempts` | 3 데이터 오염 |
| `list_anomalies` | 탐지가 기록한 이상 이력(회차별) | `anomaly` | 모두 |
| `reprocess_status` | 재처리 요청의 진행 상태 | `reprocess_events` | 재처리 |

어느 도구가 어느 코드인지: 도구 본체는 `ledger_tools.py`의 같은 이름 함수, 도구 목록(Bedrock 정의 모양)은 `TOOL_SPECS`, 실행은 `run_tool()`이다.

## 실행

```
cd agent/tools
python3 test_tools.py     # sqlite 가짜 원장으로 도구 11개와 울타리를 시험 (표준 라이브러리만 사용)
```

## 파일

| 파일 | 역할 |
|---|---|
| `guard.py` | SQL 울타리: SELECT만, 허용된 표만, `LIMIT` 필수, 정답표·원문 차단, 시간 범위 6시간 한도 |
| `ledger_tools.py` | 도구 11개, 도구 목록(`TOOL_SPECS`), 실행 함수(`run_tool`) |
| `test_tools.py` | 도구가 맞는 숫자를 돌려주는지, 울타리가 위험한 요청을 막는지 시험 |

## 알아야 할 것 (한계)

- **Athena에서는 아직 실행하지 않았다.** sqlite 가짜 원장으로만 시험했다. SQL은 두 곳에서 모두 돌아가는 기본 문법만 썼고, 다른 점은 시각 표기(`TIMESTAMP '...'`)뿐이다.
- 표 이름과 컬럼은 Gold B 문서(2026-10-18)와 `docs/design/agent/anomaly-answer-key.md`의 제안을 보고 **가정한 것**이다. `anomaly` 표의 컬럼은 제안 단계다.
- **`raw_sample`(깨진 메시지 원문 일부)은 에이전트가 읽지 못하게 막았다.** Gold B 문서가 조회 권한을 데이터 부서로 제한한다고 적어서 정한 것이며, 에이전트가 원문이 필요한지는 **미정**이다.
- 한도 값(6시간, 200줄)은 임의로 정했다.
- **"현재 보기" 문제**: `list_anomalies`는 회차(`run_id`)가 큰 줄이 최신이라고 알려 줄 뿐이다. 어떤 회차가 어느 시간대를 판정했는지 기록한 표가 없어서, 다시 판정했더니 이상이 사라진 경우(옛 줄만 남음)를 구별하지 못한다. 판정 회차 기록 표(`detection_runs`)가 필요한지는 **미정**이다.
- 아직 Bedrock을 부르는 에이전트 본체는 없다. 이 폴더는 에이전트가 쓸 도구만 만든다.
