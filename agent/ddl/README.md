# agent/ddl

판정 잡과 조사 에이전트가 **쓰는 표**의 정의(Athena DDL)다. 읽기만 하는 원장·뷰(`payment_events` 등)는 Gold B 담당이 `pipelines/gold_b/ddl/`에 정의한다.

## 쉬운 설명

| 표 | 누가 쓰나 | 한 줄은 무엇인가 | 어디에 |
|---|---|---|---|
| `gold_b.anomaly` | 판정 잡 | 판정 회차마다 쌓는 이상 한 건 (지우거나 고치지 않음) | `gold_b/anomaly/` |
| `gold_b.detection_runs` | 판정 잡 | 순찰 한 바퀴 | `gold_b/detection_runs/` |
| `gold_b.reprocess_events` | 승인 화면, 재처리 잡, 판정 잡 | 재처리 단계 하나 | Gold B 담당 정의 (`pipelines/gold_b/ddl/reprocess_events.sql`), 여기서는 만들지 않는다 |
| `agent.investigation_reports` | 조사 에이전트 | 원인 리포트 한 건 | `agent/investigation_reports/` |
| `agent.investigation_runs` | 조사 에이전트 | 조사 한 번 (성공·실패·걸린 횟수·오류) | `agent/investigation_runs/` |
| `gold_b.anomaly_current` (뷰) | 읽기 전용 | 이상별 가장 최근 줄 | 뷰 |

- 리포트와 실행 기록을 `gold_b` 밖(`agent` 데이터베이스)에 둔 이유: 조사만 하고 재처리로 이어지지 않는 경우가 있어서다(Gold B 담당 권장). 재처리로 이어지면 `reprocess_events`의 `REQUESTED` 줄 `detail`에 `anomaly_id`와 `report_id`를 남겨 연결한다.
- **시간 폴더는 날짜(`dt`)만** 둔다. 양이 적어서(이상 이력은 5분마다 몇 줄) 시간까지 나눌 필요가 없다. 기준 시각은 `detected_at`, `started_at`, `created_at`(UTC). 은서 님의 원장은 `dt`와 `hour`를 쓰지만, 이 표들은 양이 달라 날짜만 쓰는 것을 **제안**한다. 바꾸려면 DDL과 `athena_io.py`의 `TABLE_SPECS`의 `partitions`만 고친다.
- 리포트의 `claims`, `trace`, `problems`는 **JSON 문자열**로 둔다. Athena `INSERT ... VALUES`로 중첩 구조를 쓰기가 번거롭고, 화면은 문자열을 읽어 펼치면 된다.

## 만드는 순서 (Athena 쿼리 편집기 또는 스크립트, 한 번에 하나씩)

1. `database_agent.sql` (이미 만들어져 있으면 그대로 두어도 된다)
2. `anomaly.sql`, `detection_runs.sql`, `investigation_reports.sql`, `investigation_runs.sql`
3. `views/anomaly_current.sql`

파일 맨 위의 `--` 설명 줄과 끝의 `;`는 Athena API로 실행할 때 문제가 될 수 있으니, 콘솔이 아닌 스크립트로 돌릴 때는 빼고 보낸다(Gold B DDL과 같은 주의). **저장 위치의 버킷 이름은 Gold B DDL과 같은 값으로 적어 두었다.** 바뀌면 파일 전체에서 한 번에 바꾼다.

## 첫 쓰기 시험 (진짜 Athena에서 한 번 확인할 것)

시간 폴더 자동 인식(파티션 프로젝션)을 쓰는 표에 `INSERT INTO`가 잘 되는지는 **아직 확인하지 못했다.** 표를 만든 뒤 판정용 workgroup으로 이 순서로 확인한다.

```sql
INSERT INTO gold_b.detection_runs (run_id, kind, request_id, judged_from, judged_to, started_at, anomaly_count, dt)
VALUES ('TEST-0001', 'REGULAR', NULL, TIMESTAMP '2026-10-21 09:00:00', TIMESTAMP '2026-10-21 09:05:00',
        TIMESTAMP '2026-10-21 09:05:07', 0, '2026-10-21');

SELECT * FROM gold_b.detection_runs WHERE dt = '2026-10-21' AND run_id = 'TEST-0001';
```

- 행이 읽히고 S3에 `gold_b/detection_runs/dt=2026-10-21/` 파일이 생기면 성공이다. 시험 줄은 지울 수 없으니 `TEST-` 번호로 쓰고 조회에서 걸러 낸다(표는 쌓기만 한다).
- 실패하면 대안: ① 파티션 프로젝션을 빼고 `ALTER TABLE ... ADD PARTITION`으로 그날 파티션을 등록한 뒤 쓴다, ② S3에 Parquet를 직접 쓴다(타입과 압축을 맞춰야 해서 더 번거롭다). 어느 쪽이든 쓰는 코드는 `athena_io.py`의 `write()`만 바꾸면 된다.

## 필요한 권한 (인프라 담당 확인용)

- 판정 잡 역할: 판정용 workgroup 실행, Glue `gold_b`(`anomaly`, `detection_runs`, `reprocess_events`) 표 정보 읽기, S3 `gold_b/anomaly/`, `gold_b/detection_runs/`, `gold_b/reprocess_events/` 쓰기, 조회 결과 폴더 쓰기
- 조사 에이전트 역할: 조사용 workgroup 실행, Glue `agent` 표 정보 읽기, S3 `agent/investigation_reports/`, `agent/investigation_runs/` 읽기·쓰기

## 실행 (로컬 확인, Athena 접속 없음)

```
cd agent/ddl
python3 test_ddl.py
```

DDL의 컬럼 이름·타입·순서·파티션·저장 위치가 `athena_io.py`의 `TABLE_SPECS`와 같은지, `INSERT` 문의 컬럼 순서가 DDL과 같은지, 뷰가 이상별 최근 줄만 고르는지 확인한다.

## 알아야 할 것 (한계)

- **진짜 Athena에서는 아직 만들어 보지 않았다.** 위 첫 쓰기 시험이 첫 확인이다. `date` 파티션 프로젝션 문법은 Gold B DDL을 그대로 따랐다.
- `anomaly.status`의 `RESOLVED`는 R6 해소 줄에 쓰는 새 값이다(설계 문서의 목록에 추가가 필요하다).
- 조사 에이전트가 이 표 두 개에 쓰는 코드는 **아직 없다**(Bedrock 호출 코드와 함께 만든다). 표와 쓰기 정의(`TABLE_SPECS`)만 먼저 맞춰 둔 것이다.
