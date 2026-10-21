# 작업 지시서: pipelines/gold-b-ingest

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-ingest` (`pipelines/gold-b-reprocess` 위에서 갈라짐) · 다음 작업: 형식 검사(2단계) 연결, Spark 실행 확인, 배포 (재영 님)

## 목표

Kafka 토픽을 Spark Structured Streaming으로 1분마다 읽어 원장 ①`payment_events` ②`topic_messages` ④`malformed_events`에 쌓는 **적재 잡**(4단계)의 본체와 설정 파일을 만든다. 형식 검사(2단계)가 아직 없으므로 재처리 잡과 같은 형식 검사 자리(`ledger.Checker`)를 쓴다. 배포 설정은 만들지 않는다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「역할 경계와 전체 흐름」, 「처리 규칙」, 「신뢰성 점검」, 4단계 체크리스트
- `pipelines/gold_b/ledger.py` (`message_rows`, 저장소), `pipelines/gold_b/jobs/reprocess.py` (같은 형식 검사 자리)
- `simulator/src/sim/common/kafka.py` (Kafka 접속 환경변수 이름)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 원장 공통 도구(`ledger.py`)를 쓰므로 `pipelines/gold-b-reprocess` 위에서 갈라졌다. push는 #36과 재처리 브랜치가 머지된 뒤, 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
- 같은 곳에서 갈라진 `pipelines/gold-b-compact`와 `docs/BRANCHES.md`, `jobs/README.md` 첫 줄을 같이 고쳐서, 나중에 둘을 차례로 머지할 때 작은 충돌이 난다 (두 줄을 합치면 됨).
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 정한 기본값 (설계에 없는 세부, 2026-10-21 사용자에게 알리고 진행)

1. **처음 시작:** 체크포인트가 없으면 Kafka에 남은 가장 오래된 메시지부터 읽는다 (`starting_offsets: earliest`).
2. **묶음 크기:** 묶음 하나에 최대 20,000건 (`max_offsets_per_trigger`). 밀린 메시지를 한 번에 읽어 메모리가 넘치지 않게 한다.
3. **파일 이름:** (표, 시간 폴더)마다 파일 하나, 이름은 그 파일에 든 메시지 위치로 만든 값(`part-ingest-<16자리>.parquet`). Spark가 끝내지 못한 묶음을 다시 처리하면 덮어써서 두 번 쌓이지 않는다.
4. **지워진 메시지:** 보관 기간(3일)보다 오래 멈춰 메시지가 지워졌어도 멈추지 않고 남은 것부터 읽는다 (`failOnDataLoss=false`). 빠진 구간은 `topic_messages` 오프셋 빈틈으로 보이고 Bronze 재처리로 채운다 (설계 「신뢰성 점검」).
5. **설정 나누기:** 토픽 목록·주기·시작 위치·묶음 크기는 `config/gold_b.yaml`, 원장 저장 위치·체크포인트·Kafka 주소는 환경변수 (버킷 이름·주소를 커밋하지 않음). 설계의 "PG 목록"은 공통 규칙표에 있어 여기 두지 않는다.
6. **시각:** Kafka 시각은 1970년부터의 밀리초로 받아 UTC로 바꾼다 (Spark에서 파이썬으로 옮길 때 서버 시간대가 섞이지 않게).

## 만드는 것

- `pipelines/gold_b/jobs/streaming_ingest.py`: `write_batch`(묶음 하나 → 원장 파일, Spark 없이 시험), `kafka_options`, `build_query`(Spark 연결), `Settings`(환경변수), `load_config`
- `pipelines/gold_b/config/gold_b.yaml`
- `pipelines/gold_b/tests/test_ingest.py`
- `pipelines/gold_b/requirements.txt`에 `PyYAML` (Silver와 같은 6.0.3), `jobs/README.md` 적재 잡 절, `pipelines/gold_b/README.md`, 설계 문서 4단계 체크, `docs/BRANCHES.md` 한 줄

## 만들지 않는 것

- 형식 검사 (2단계, 현지 님과 정한 뒤), 실행 진입점(`spark-submit`으로 부를 명령)
- `deploy/gold_b_streaming.yaml`, EKS 실행, Spark 이미지·Kafka 연결 jar (재영 님 규칙 확인 후)

## 작업 순서

1. 계획 제시 (2026-10-21, 사용자가 남은 브랜치를 모두 만들어 달라고 요청)
2. 작업 지시서·브랜치 대장 커밋
3. 적재 잡, 설정, 시험, README 커밋
4. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경, 40개 통과, 설정 파일 시험 1개는 PyYAML이 없어 건너뜀)
- [x] 묶음 하나의 줄이 이벤트 시각의 시간 폴더로 가고, 같은 묶음을 다시 써도 두 번 쌓이지 않는지
- [x] 설정 파일을 읽는 시험 (PyYAML이 있는 PC 기본 Python으로 `test_ingest.py` 4개 통과)
- [ ] Spark로 실제 실행 → **대기** (이 PC에서 Spark가 뜨지 않음, 형식 검사 없음)

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** Kafka를 Spark Structured Streaming으로 1분마다 읽어 원장 ①②④에 쌓는 적재 잡 본체와 설정 파일을 만들었다. 묶음 처리는 시험으로 확인했고, Spark 연결은 이 PC에서 돌려 보지 못했다. 형식 검사(2단계)가 생겨야 실제로 돌 수 있다.
- **무엇을 만들었나:**
  - `pipelines/gold_b/jobs/streaming_ingest.py`: `write_batch`, `kafka_options`, `build_query`, `Settings.from_env`, `load_config`
  - `pipelines/gold_b/config/gold_b.yaml`: 토픽 6개, 1분, `earliest`, 묶음 최대 20,000건
  - `pipelines/gold_b/tests/test_ingest.py`(4개), `requirements.txt`에 `PyYAML==6.0.3`, `jobs/README.md` 적재 잡 절, `pipelines/gold_b/README.md`, 설계 문서 4단계 체크, `docs/BRANCHES.md` 한 줄
- **왜 그렇게 했나:**
  - 묶음 처리를 Spark와 떼어 순수 파이썬 함수(`write_batch`)로 만들었다. 이 PC에서 Spark가 뜨지 않아도 핵심을 시험할 수 있고, 재처리 잡과 같은 `message_rows`를 써서 평소 경로와 재처리 경로의 결과가 같다.
  - 파일 이름을 메시지 위치로 정해서 Spark가 묶음을 다시 처리해도 같은 파일을 덮어쓴다. Spark의 foreachBatch는 실패하면 같은 묶음을 다시 부르기 때문이다.
  - Kafka 시각을 밀리초 숫자로 받는다. PySpark가 시각을 파이썬으로 옮길 때 서버 시간대를 쓰는 문제를 피한다.
  - 주소·버킷 이름은 환경변수로만 받고 로그에는 묶음 번호와 건수만 쓴다.
- **확인한 결과:**
  - Gold B 가상환경에서 `pipelines/gold_b/tests` 40개 통과, 1개 건너뜀 (테이블 정의 22 + 재처리 15 + 적재 3, 설정 파일 시험은 PyYAML이 없어 건너뜀).
  - PC 기본 Python(PyYAML 있음)으로 `test_ingest.py` 4개 통과: 샘플 31건을 한 묶음으로 쓰면 원장 세 표가 샘플 기대 결과와 같고 파일은 4개(메시지 05·06시, 결제 06시, 오류 06시), 같은 묶음을 다시 쓰면 파일이 늘지 않고, 다음 묶음은 새 파일로 쌓여 전체가 기대 결과와 같음, 설정 파일과 환경변수 확인.
  - `git diff --check` 통과.
- **알려진 한계·남은 일:**
  - 형식 검사(2단계)가 없어서 실행 진입점을 만들지 않았다. 현지 님과 형식 검사를 정한 뒤 연결한다.
  - Spark 연결(`build_query`)은 이 PC에서 Spark가 뜨지 않아(Java 소켓 오류) 돌려 보지 않았다. Docker의 Spark나 EKS에서 확인해야 한다.
  - Spark 런타임(이미지, `spark-sql-kafka` jar, S3 체크포인트용 `hadoop-aws`), 클라이언트 인증서 형식(Java Kafka 클라이언트는 암호 없는 PKCS#8 키를 PEM 값으로 받음), `deploy/gold_b_streaming.yaml`은 재영 님과 정한다.
  - Gold B 가상환경에 `PyYAML`을 아직 설치하지 않았다 (`pip install -r pipelines/gold_b/requirements.txt`로 설치).
  - push는 #36과 재처리 브랜치가 머지된 뒤 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
