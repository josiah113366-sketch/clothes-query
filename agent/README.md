# agent/

탐지 규칙, 이상 이력, 조사 에이전트, 승인 흐름을 담는 영역이다(`docs/BRANCHES.md`의 `agent`).
조사 에이전트는 읽기 전용이고, 수정은 제안만 한다. 재처리는 사람이 승인한 뒤에만 Airflow가 실행한다.

## 전체 흐름 (경비원과 수사관)

5분마다 울리는 알람 시계 두 개가 있다고 생각하면 된다.

1. **판정(`agent/detect`)**: 경비원이 5분마다 한 바퀴 순찰하며 Gold B 원장을 읽는다. 규칙 5개(R1·R3·R4·R5·R6)로 이상이 있으면 이상 이력(`gold_b.anomaly`)에 새 줄로 쌓는다. 지우거나 고치지 않는다.
2. **조사(`agent/investigator` + `agent/tools`)**: 이상 1건을 접수한 수사관이 읽기 전용 도구 11개(`ledger_tools.py`, `guard.py` 울타리 통과)로 근거를 모아 원인 층(PAYMENT/INGEST/DATA_QUALITY/UNKNOWN)과 근거를 담은 리포트를 쓴다(`agent/investigator/report.py`). 모델은 Bedrock Claude Haiku 4.5(`bedrock_io.py`).
3. **승인(`agent/approval`)**: 리포트를 본 사람이 승인하면(서류에 도장) 서버가 중복·만료·재시도 한도를 확인한 뒤 Airflow에 재처리를 맡긴다.
4. **재판정**: 재처리가 끝나면 같은 판정 규칙으로 구간을 다시 돌려 이상이 사라졌는지 확인한다(VERIFIED/재발).
5. **채점(`agent/eval`)**: 정답표(`incident_log`)와 이상 이력·리포트를 비교해 허용 지연 안에 맞혔는지 채점한다.

DAG 2개(`agent/dags`)가 1·2번을 5분마다 Airflow(EKS)에서 실행한다. 판정 DAG는 항상 켜져 있고, 조사 DAG는 평소 일시정지이며 실제 사건을 조사할 때만 켠다.

## 폴더

| 폴더 | 내용 | 상태 |
|---|---|---|
| `detect/` | 판정 잡(순찰). 규칙 5개(R1·R3·R4·R5·R6), Athena 읽기/쓰기 | 운영 중. 5분마다 실행, 실제 사건(R3·R6) 탐지 확인 |
| `tools/` | 조사 에이전트가 쓰는 읽기 전용 도구 11개 + SQL 울타리(`guard.py`) | 운영 중 |
| `investigator/` | 조사 에이전트 루프. Bedrock Claude Haiku 4.5 연결, 근거 검증 포함 | 운영 중. 실제 R3 사건 조사·리포트 생성 확인(10/25) |
| `approval/` | 재처리 승인 백엔드 규칙(요청·승인·중복 방어·경고) | 운영 중. 대시보드 승인 화면이 호출 |
| `dags/` | 판정·조사 DAG 2개(Airflow, KubernetesPodOperator) | 운영 중 |
| `ddl/` | 판정·조사가 쓰는 표 정의(`anomaly`, `detection_runs`, `investigation_reports`, `investigation_runs`) | 운영 중 |
| `eval/` | 정답표 대비 채점 스크립트(`score.py`) | 스크립트는 완성. 실제 Athena 데이터로 정식 채점은 아직(발표 전 실행 예정) |
| `reliability/` | 장부를 믿어도 되는지 보는 쿼리 3개(누락·중복·멈춤) | `ledger_tools.py`의 `ledger_reliability` 도구로 편입됨 |
| `prototype/` | 탐지 규칙을 가짜 데이터로 처음 시험한 프로토타입 | 완료, 참고용. 실제 코드는 `detect/`가 대체함 |

각 폴더의 자세한 설명·쉬운 비유는 폴더 안 `README.md`를 따른다.

## 의존하는 것

- Gold B 원장(`gold_b.payment_events`, `topic_messages`, `bronze_lag_snapshots`, `malformed_events`, `anomaly_current` 뷰)과 정리 뷰. 설계는 Gold B 담당자의 문서를 따른다.
- Silver의 주문상품 합계 검사 출력(`order_amount_checks`, R6용).
- 정답표(`ground_truth/incident_log/`, JSON)는 조사 에이전트가 읽지 못하는 별도 위치다. `agent/eval`만 채점용으로 읽는다.

## 대시보드 연결

"이상탐지"·"원인 리포트" 화면은 `gold_b.anomaly_current`, `agent.investigation_reports`를 실데이터로 읽는다(`dashboard/data.py`의 `_real_anomalies`·`_real_rca_reports`). 승인 화면은 `agent/approval`을 직접 호출한다.
