# agent/detect

**판정 잡 틀**이다. 5분마다 한 번 실행되어 원장을 읽고, 이상이 있으면 이상 이력(`gold_b.anomaly`)에 새 줄로 쌓는다.

## 쉬운 설명: 경비원의 순찰

건물 경비원이 5분마다 한 바퀴 순찰한다고 생각하면 된다. `run_once()`가 그 한 바퀴다.

1. **번호 붙이기**: 지금 시각을 5분 단위로 내려 순찰 번호(`run_id`, 예: `20261020T1510Z`)를 정한다. 이미 돈 번호면 건너뛴다.
2. **장부 확인**: 원장과 정리 뷰를 읽는다.
3. **규칙과 비교**: R1(PG 결제 실패), R3(Bronze 지연), R4(깨진 메시지), R5(한 주문에 성공 결제 2건), R6(Silver 주문 총액 불일치)로 이상 여부를 본다.
4. **일지에 쓰기**: 이상이 있으면 이상 이력에 **새 줄로 쌓는다**(지우거나 덮지 않는다). 순찰을 돌았다는 기록(`detection_runs`)도 남긴다.
5. **재처리 쪽지 확인**: 재처리 기록(`reprocess_events`)에 "교체 끝났는데 아직 재판정 안 한" 줄이 있으면 그 시간대를 다시 훑고, `REDETECTED`와 `VERIFIED`(해결됐나)를 적는다.

## 어느 부분이 어느 코드인가

| 하는 일 | 코드 |
|---|---|
| 순찰 한 바퀴 전체 | `job.py`의 `run_once()` |
| 5분 단위 번호, 같은 번호 두 번 안 돌기 | `floor_tick()`, `regular_run()` |
| 원장 읽고 규칙으로 판정 | `job.py`의 `judge()`, 규칙은 `rules.py`의 `r1_pg_failures`, `r3_bronze_lag`, `r4_malformed` |
| 이상 줄 만들기, `anomaly_id` | `rules.py`의 `make_row()`, `anomaly_id()` |
| 교체 끝났는데 재판정 안 한 줄 찾기 | `job.py`의 `pending_replacements()` |
| 교체된 시간대 다시 판정, 해결 여부 확인 | `job.py`의 `redetect()` |
| 임계값(3건, 20%, 1200초 등) | `rules.py`의 `Config` |

## 규칙 (임계값은 모두 임시값)

| 규칙 | 이상으로 보는 조건 |
|---|---|
| R1 PG 결제 실패 | 한 PG의 PG 원인 실패가 최근 15분에 3건 이상이고, 그 PG 결제 시도 중 20% 이상 |
| R3 Bronze 지연 | 지연이 1200초 이상(**임시**: Bronze S3 Sink가 15분=900초마다 파일을 써서 정상일 때도 0~900초를 오간다)이거나, 측정 줄이 3분 동안 하나도 없음. 유입량(R2)은 증거로만 붙임 |
| R4 깨진 메시지 | 한 토픽의 깨진 메시지가 5분에 5개 이상이고 5% 이상 (현재 형식 규칙 버전만 셈) |
| R5 한 주문에 성공 결제 2건 | `payment_attempts`에서 SUCCESS 결제가 2건 이상인 주문이 최근 5분 사이 적재된 줄에 1개 이상. 평소에는 0이어야 하는 값이라 비율 조건이 없다. 실패 뒤 재시도 성공은 SUCCESS가 1건이라 안 센다 |

- R5는 **적재 시각(`loaded_at`)** 으로 최근 5분을 본다. 시뮬레이터 컨트롤러의 오염은 기존 성공 결제의 +2초 시각으로 새 행을 넣기 때문에 `completed_at`은 과거일 수 있다. 재처리 뒤 재판정에서만 결제 완료 시각(`completed_at`)으로 본다(교체된 줄의 적재 시각은 재처리 시각이라서).
- **R6 주문 총액 불일치**는 Silver가 남기는 검사 결과(`status`가 `MISMATCH`)를 **최신 실행만** 읽는다(Silver 담당과 합의한 방식).
  - 새로 불일치가 된 주문 → 이상 줄(`OPEN`). 이미 열려 있는 주문이 계속 불일치 → **지속**(새 줄 없음). 열려 있던 주문이 `PASS` → **해소 줄**(`RESOLVED`).
  - 결과에서 주문이 사라졌거나 `UNVERIFIED`·`PENDING_REFERENCE`·`ITEM_ERROR`이면 **해소로 보지 않는다.**
  - 열려 있는 주문은 이전 R6 이상 줄의 `evidence_ref`(`new_orders`, `resolved_orders`)에서 되살린다. 근거에는 Silver 실행 번호, 검사 버전, 실행 참조, 주문 번호(최대 500), 금액 차이를 싣는다(에이전트가 이상 이력만 읽어도 근거를 볼 수 있게).
  - `Config.silver_checks_table`이 비어 있으면(기본) 돌리지 않는다. **표 위치와 이름은 Silver·인프라 담당과 확정 전**이다. 재판정(재처리 뒤 비교)에서는 R3처럼 뺀다(재처리와 무관한 값).
- R1·R4는 비율 조건이 있어 **구간이 끝난 지 3분 지난 것만** 본다(Gold B 문서).
- 근거 시험은 `agent/prototype`(PR #14)에 있다.

## 실행

```
cd agent/detect
python3 test_job.py     # sqlite 가짜 원장으로 순찰을 직접 돌려 시험 (표준 라이브러리만 사용)
```

## 바깥 세상과 만나는 곳

`run_once(query, write, cfg, now)`는 함수 두 개로만 바깥과 만난다. 그래서 가짜 데이터로 시험할 수 있고, 나중에 Athena와 연결할 때 이 두 함수만 바꾸면 된다.

- `query(sql)`: SQL을 실행해 줄 목록(dict)을 돌려준다
- `write(표 이름, 줄 목록)`: 새 줄을 추가한다. **시각 컬럼은 문자열 `YYYY-MM-DD HH:MM:SS`(UTC)로 넘어온다.** Gold B가 이 컬럼을 TIMESTAMP로 정의하므로 실제 `write`는 시각 타입으로 바꿔서 써야 한다(시험이 문자열 형식을 확인한다)

## Athena 연결과 실행 (제안, 진짜 Athena에서는 아직 안 돌려 봤다)

| 하는 일 | 코드 |
|---|---|
| `query(sql)`: Athena에 쿼리를 보내고 끝날 때까지 기다려 결과를 타입에 맞게 돌려줌 | `athena_io.py`의 `AthenaIO.query()` |
| `write(표, 줄)`: Athena `INSERT INTO`로 새 줄 추가. 표 3개(`anomaly`, `detection_runs`, `reprocess_events`)만 허용 | `athena_io.py`의 `AthenaIO.write()`, 표 정의 `TABLE_SPECS` |
| 5분마다 한 번 실행하는 진입점 | `run_job.py` |
| 컨테이너 이미지 | `Dockerfile`, `requirements.txt` |

실행: `ATHENA_WORKGROUP=<판정용 workgroup> python run_job.py` (선택 `ATHENA_DATABASE`, 기본 `gold_b`). 비밀값은 없다. AWS 권한은 Pod의 ServiceAccount에 연결된 역할이 준다. 결과 저장 위치는 workgroup 설정이 정한다.

**판정 잡 역할에 필요한 권한** (인프라 담당 확인용, 계정 번호나 ARN은 이 문서에 적지 않는다)
- Athena: 판정용 workgroup에 쿼리 시작·상태 확인·결과 읽기·중지
- Glue: 데이터베이스 `gold_b`의 표 정보 읽기 (원장, 뷰, `anomaly`, `detection_runs`, `reprocess_events`)
- S3 읽기: `gold_b/` 전체. S3 쓰기: **`gold_b/anomaly/`, `gold_b/detection_runs/`, `gold_b/reprocess_events/`만**
- S3: 판정용 조회 결과 폴더(`athena-results/detection/`) 읽기·쓰기
- `ground_truth/`는 접근 금지(이미 차단됨)

**쓰기 방식은 아직 진짜 Athena에서 확인 전이다 (제안)**
- 쓰기는 `INSERT INTO ... VALUES`로 한다(시각을 `TIMESTAMP`로 안전하게 넣기 위해). 5분마다 작은 파일이 생기는 점이 단점이다. S3에 Parquet를 직접 쓰는 방법도 있다.
- 표 정의는 `agent/ddl/`에 있다. `anomaly`와 `detection_runs`는 **날짜(`dt`) 폴더**(기준 시각 `detected_at`, `started_at`)로 쌓고, `reprocess_events`는 은서 님 DDL대로 파티션 없이 쓴다. 코드와 DDL이 같은지는 `agent/ddl/test_ddl.py`가 확인한다. 정의가 바뀌면 `TABLE_SPECS`와 DDL을 같이 고친다.
- `reprocess_events`는 승인 화면(`REQUESTED`, `APPROVED`), 재처리 잡(`STARTED`, `LEDGER_REPLACED`, `FAILED`)과 이 잡(`REDETECTED`, `VERIFIED`)이 함께 쓴다. 이 잡은 자기 줄만 쓴다.
- **저장 도중 실패해서 다시 돌려도 이중 저장이 없다**(재영 님 리뷰). ① 이상 줄은 같은 순찰 번호·이상 번호로 이미 있으면 다시 쓰지 않는다. ② 순찰 기록은 이미 있으면 다시 쓰지 않는다. ③ 순찰 기록의 이상 개수는 처음 판정한 개수 그대로다. ④ 재판정의 순찰 번호는 요청과 교체 구간으로 정해서(`<구간 시작>-RD-<요청 번호>`) 몇 시간 뒤 재시도해도 같은 번호가 된다. ⑤ 재판정이 옛 이상을 찾을 때 자기 번호의 줄은 제외한다(이전 시도가 쓴 줄을 옛 이상으로 착각하지 않게).
- 정기 순찰의 번호는 시각으로 만들므로, **Airflow가 논리 시각(`data_interval_end`)을 환경 변수 `JUDGE_TICK`으로 넘기면** 몇 분 뒤 재시도해도 같은 번호가 된다. 안 넘기면 현재 시각을 5분 단위로 내려 쓴다(같은 5분 안의 재시도만 안전).

## 알아야 할 것 (한계)

- **R6**: Silver 결과는 아직 로컬 파일이고 Athena 표·정기 실행이 없다(현지 님 제공안). 표 이름과 컬럼은 제공안을 가정했고 시험은 가짜 표로만 했다. `MISMATCH` 줄이 많아 근거에 못 담는 주문(500개 초과)은 열려 있는 주문으로 추적되지 않아 다음 실행에서 다시 새 불일치로 셀 수 있다. 상태값 `RESOLVED`는 이 표의 `status`에 새로 쓰는 값이라 설계 문서의 `status` 값 목록(`OPEN`/`INVESTIGATING`/`REPORTED`)에 추가가 필요하다(제안). Silver가 수동 실행이라 채점(`agent/eval`)에서는 이 사건을 당분간 "규칙 없음"으로 둔다.

- **진짜 Athena에서는 아직 실행하지 않았다.** sqlite 가짜 원장과 가짜 Athena 클라이언트로만 시험했다. 연결 코드(`athena_io.py`)는 있지만, 표가 Athena에 올라온 뒤 실제 쿼리 문법(예: `"at"` 컬럼 인용, 시각 비교)과 `INSERT`를 확인해야 한다.
- **5분마다 실행하는 일**(Airflow 작업)은 만들지 않았다. 인프라 담당과 정해야 한다.
- **재처리 뒤 재판정 방식은 Gold B 담당과 정리됐다.** 재처리 작업은 판정을 직접 부르지 않고, 이 잡이 5분마다 `reprocess_events`의 `LEDGER_REPLACED` 줄을 읽어 재판정한다(Gold B 문서 2026-10-19). 이 코드의 `pending_replacements()`와 `redetect()`가 그 일이다. 재판정은 **교체 구간의 끝까지(비율 규칙의 3분 대기를 포함해 한 번 더) 훑고**, 재처리가 다시 만들지 않는 **R3(Bronze 지연)는 비교에서 뺀다**(`VERIFIED`의 `detail`에 `excluded_rules`로 적는다). 교체 때 다시 적재된 줄은 R5 순찰이 새 중복으로 세지 않는다(`_replaced_filter`).
- **`detection_runs`(순찰 기록 표)**는 Gold B 문서(2026-10-19)에 `anomaly`와 함께 `gold_b/` 안의 내 표로 적혀 있다. 컬럼 정의는 내가 한다(`job.py`의 `_run_record`).
- 이상이 이어지는 구간을 하나로 합치는 `episode_start`, `episode_end`는 아직 비어 있다.
- **R3 기준(1200초)은 임시다.** `lag_sec`은 S3 Sink가 아직 처리하지 않은 가장 오래된 메시지의 나이(초)이고, 파일을 쓸 때만 처리 위치를 갱신해서 정상일 때도 최대 약 900초까지 오간다(Gold B 담당 답변). 60초로 두면 늘 울린다. 처리할 메시지가 없으면 0, 시각을 모르면 NULL이며 NULL은 알리지 않는다. **폭주 모드로 이 기준 위까지 지연이 오를지는 미확인**이다(파일 전환 주기를 줄이는 안은 시뮬레이터·인프라 담당과 협의 필요).
- **R4는 형식 검사 규칙 버전(`format_rule_version`)이 `malformed_events.rule_version`과 같아야 센다.** 지금 기본값은 `0.2.0`이다(2026-10-22 `0.1.0`에서 올림, 은서 님 지적). Gold B는 공통 형식 규칙 YAML(`docs/contracts/format_rules.yaml`)의 `version` 값을 그대로 쓰므로 **YAML 버전이 바뀌면 이 값도 같이 바꾼다.** 다르면 0건으로 나온다. `test_job.py`가 YAML 버전과 이 기본값이 같은지 확인해서 어긋나면 시험이 실패한다.
- 임계값(3건, 20%, 1200초, 3분 등)은 프로토타입으로 고른 값이며, 팀 동의 전이다.
- 재판정은 교체된 1시간 폴더를 5분 간격으로 다시 훑는다. 여러 폴더(여러 줄)는 줄마다 따로 판정한다. 요청 중간에 실패한 경우(`FAILED`)는 아직 구별하지 않는다.
- **시나리오 3(데이터 오염)은 절반만 덮는다.** 컨트롤러의 데이터 오염은 **형식은 맞고 업무 규칙만 어기는 행**이라 R4(형식이 깨진 메시지)로는 못 잡는다. "한 주문에 성공 결제 2건"은 R5가 잡는다. **"주문 총액 ≠ 항목 합계"는 아직 못 잡는다**: Gold B에 주문 금액이 없어 Silver 쪽 검사가 필요하다(**미정**, 은서 님·현지 님과 정할 일). R4가 맞는 사건(형식이 깨진 메시지를 주입하는 사건)은 지금 컨트롤러에 없다.
- **R5는 재처리로 안 고쳐질 수 있다.** 재처리는 Kafka에서 원장을 다시 만든다. 오염은 원본 DB에 넣은 행이라 Kafka에도 같이 있어서, 재처리해도 중복 결제가 그대로 다시 나오면 재판정은 `STILL_OPEN`이다. 이건 규칙 오류가 아니라 원인이 데이터 원본에 있다는 뜻이다(조사 에이전트가 이 점을 설명할 수 있어야 한다).
- R5 조회는 `payment_attempts` 전체에서 해당 주문의 SUCCESS 줄을 세므로 Athena에서는 스캔량이 늘 수 있다(미측정).
