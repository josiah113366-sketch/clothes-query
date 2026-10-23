# 작업 지시서: pipelines/gold-b-ingest

> 상태: 완료 · 브랜치: `pipelines/gold-b-ingest` (`pipelines/gold-b-reprocess` 위에서 갈라짐, 2026-10-23 `pipelines/gold-b-format-check` 병합) · PR은 형식 검사·파일 합치기 브랜치가 머지된 뒤 · 다음 작업: Gold B 이미지(팀 기본 Spark 이미지 위)와 배포 (재영 님), EKS에서 Spark 실행 확인

## 목표

Kafka 토픽을 Spark Structured Streaming으로 1분마다 읽어 원장 ①`payment_events` ②`topic_messages` ④`malformed_events`에 쌓는 **적재 잡**(4단계)의 본체와 설정 파일을 만든다. 형식 검사(2단계)가 아직 없으므로 재처리 잡과 같은 형식 검사 자리(`ledger.Checker`)를 쓴다. 배포 설정은 만들지 않는다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「역할 경계와 전체 흐름」, 「처리 규칙」, 「신뢰성 점검」, 4단계 체크리스트
- `pipelines/gold_b/ledger.py` (`message_rows`, 저장소), `pipelines/gold_b/jobs/reprocess.py` (같은 형식 검사 자리)
- `simulator/src/sim/common/kafka.py` (Kafka 접속 환경변수 이름)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 원장 공통 도구(`ledger.py`)를 쓰므로 `pipelines/gold-b-reprocess` 위에서 갈라졌다. ~~push는 #36과 재처리 브랜치가 머지된 뒤, 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.~~ → 2026-10-23 바뀜: 형식 검사기를 쓰려고 `pipelines/gold-b-format-check`(재처리·최신 `main` 포함)를 병합했다. 커밋을 옮기지 않고, 재처리 → 형식 검사·파일 합치기가 머지된 뒤 PR을 올린다.
- 같은 곳에서 갈라진 `pipelines/gold-b-compact`와 `docs/BRANCHES.md`, `jobs/README.md` 첫 줄을 같이 고쳐서, 나중에 둘을 차례로 머지할 때 작은 충돌이 난다 (두 줄을 합치면 됨). → 2026-10-23에 파일 합치기 브랜치를 이 브랜치에 병합해 충돌을 미리 풀었다 (브랜치 대장, Gold B README, `jobs/README.md` 첫 줄). 그래서 이 PR은 형식 검사·파일 합치기가 머지된 뒤에 올린다.
- 2026-10-23 보완은 사용자 요청("6 7 8 9 차례대로")으로 했다: 형식 검사기 연결, 실행 입구, 배포에 필요한 것 정리. 배포 설정 파일은 여전히 만들지 않는다.
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

- ~~형식 검사 (2단계, 현지 님과 정한 뒤), 실행 진입점(`spark-submit`으로 부를 명령)~~ → 2026-10-23 보완에서 연결·추가 (형식 검사기 자체는 `pipelines/gold-b-format-check`)
- `deploy/gold_b_streaming.yaml`, EKS 실행, Spark 이미지·Kafka 연결 jar (재영 님 규칙 확인 후)

## 작업 순서

1. 계획 제시 (2026-10-21, 사용자가 남은 브랜치를 모두 만들어 달라고 요청)
2. 작업 지시서·브랜치 대장 커밋
3. 적재 잡, 설정, 시험, README 커밋
4. "완료 확인" 실행과 작업 결과 기록
5. (2026-10-23 보완) 형식 검사 브랜치 병합, 형식 검사기 연결과 실행 입구, 배포에 필요한 것 정리, 다시 확인

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경, 40개 통과, 설정 파일 시험 1개는 PyYAML이 없어 건너뜀)
- [x] 묶음 하나의 줄이 이벤트 시각의 시간 폴더로 가고, 같은 묶음을 다시 써도 두 번 쌓이지 않는지
- [x] 설정 파일을 읽는 시험 (PyYAML이 있는 PC 기본 Python으로 `test_ingest.py` 4개 통과)
- [x] Spark로 실제 실행: Docker의 Spark 4.1.3 + 로컬 Kafka 3.7로 확인 (형식 검사 대신 샘플 기대 결과로 판정)
- [x] 같은 체크포인트로 다시 켜도 빠지거나 두 번 쌓이지 않는지
- [x] (보완) 실제 형식 검사기로 샘플 묶음을 쓰면 원장 ② 31줄, ① 9줄, ④는 샘플 기대 오류 수와 같은지
- [x] (보완) 실행 입구가 형식 검사기(규칙 0.2.0)를 끼워 쿼리를 시작하고, 환경변수가 없으면 Spark를 띄우지 않고 1로 끝나는지 (가짜 쿼리)
- [x] (보완) `python -m pytest -q pipelines/gold_b/tests`, `python -m pytest -q pipelines` 통과 (형식 검사·파일 합치기 병합 뒤 136개, 221개)
- [x] (보완) Python 3.10 수정이 든 형식 검사 브랜치를 다시 병합한 뒤 `pipelines/gold_b/tests` 139개 통과 (Python 3.12, 그리고 같은 코드로 Python 3.10.12 컨테이너)

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
  - **로컬 Spark 실제 확인 (2026-10-22, Docker):** `spark:4.1.3-scala2.13-java17-python3-ubuntu` 컨테이너에서 `spark-submit --packages org.apache.spark:spark-sql-kafka-0-10_2.13:4.1.3`로 `build_query`를 실행했다. Kafka는 `apache/kafka:3.7.0`, 샘플 메시지를 원래 Kafka 시각과 키(샘플 이름)로 넣고, 형식 검사 대신 키로 샘플 기대 결과를 돌려주는 가짜 판정을 썼다. 설정 파일은 그대로 읽고 주기만 5초로 줄였다.
    - 1차: 06:08 전 메시지 23건 → 묶음 0번, 파일 4개(메시지 05·06시, 결제 06시, 오류 06시). 메시지 23·결제 7·오류 14줄이 기대와 같음 (Kafka 시각 포함).
    - 나머지 6건을 넣고 **같은 체크포인트로 다시 실행** → 묶음 1번이 새 6건만 읽음. 합계 메시지 29·결제 10·오류 16줄이 기대와 같고, 같은 위치가 두 번 쌓인 메시지 없음.
    - 처음 실행에서 **구독 목록에 Kafka에 없는 토픽(`reviews.raw`)이 있으면 쿼리가 `UnknownTopicOrPartitionException`으로 멈추는 것**을 찾았다. 토픽 이름 목록(`subscribe`) 대신 이름과 정확히 같은 패턴(`subscribePattern`, `^(payments|…|reviews\.raw)$`)으로 받게 고쳤다. 있는 토픽만 읽고, 나중에 생긴 토픽은 그때부터 읽는다. 시험 1개를 더했다 (가상환경 41개 통과·1개 건너뜀, PC Python `test_ingest.py` 5개 통과).
    - 받은 것: Kafka 연결 jar와 의존 jar 125MB(Maven Central), 컨테이너 안 `pyarrow` 25.0.1(컨테이너가 Python 3.10이라 26.0.0이 없음)·`PyYAML` 6.0.3. 시험 컨테이너는 지웠다.
- **알려진 한계·남은 일:**
  - ~~형식 검사(2단계)가 없어서 실행 진입점을 만들지 않았다. 현지 님과 형식 검사를 정한 뒤 연결한다.~~ → 2026-10-23 보완에서 해결
  - Spark는 로컬 Docker에서만 돌려 봤다. EKS 실행, S3 체크포인트(`s3a://`, `hadoop-aws`), SSL·mTLS 연결은 확인하지 않았다.
  - Spark 런타임(이미지, `spark-sql-kafka` jar, S3 체크포인트용 `hadoop-aws`), 클라이언트 인증서 형식(Java Kafka 클라이언트는 암호 없는 PKCS#8 키를 PEM 값으로 받음), `deploy/gold_b_streaming.yaml`은 재영 님과 정한다.
  - Gold B 가상환경에 `PyYAML`을 아직 설치하지 않았다 (`pip install -r pipelines/gold_b/requirements.txt`로 설치).
  - ~~push는 #36과 재처리 브랜치가 머지된 뒤 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.~~ → 2026-10-23 바뀜 (위 특례: 병합으로 따라감)

### 보완 (2026-10-23): 형식 검사기 연결과 실행 입구

- **무엇을 했나:**
  - `pipelines/gold-b-format-check`(재처리 브랜치·최신 `main` 포함)를 병합했다. Gold B README와 브랜치 대장 충돌은 두 줄을 합쳐 풀었다.
  - `jobs/streaming_ingest.py`에 실행 입구 `main()`과 `spark_session()`(세션 시간대 UTC)을 더했다. 설정 파일·환경변수·형식 규칙표(`GOLD_B_RULES_PATH`, 생략하면 저장소 규칙표)를 먼저 읽고, 형식 검사기(`FormatChecker`, 공통 규칙 `gold_b`)를 끼워 `build_query`를 시작한 뒤 멈출 때까지 기다린다. `python -m pipelines.gold_b.jobs.streaming_ingest`로 부른다.
  - 시험 3개: 실제 형식 검사기로 샘플 묶음 쓰기, 실행 입구가 검사기를 끼워 쿼리를 시작하는지(가짜 쿼리), 환경변수가 없으면 Spark 없이 1로 끝나는지.
  - `jobs/README.md`에 부르는 방법과 배포에 필요한 것(재영 님께), 설계 문서 4단계 체크.
- **왜 그렇게 했나:**
  - 설정이 틀린 것은 Spark를 띄우기 전에 알 수 있어서 먼저 읽고 1로 끝낸다. 스트리밍 중 실패는 다시 띄우면 체크포인트에서 이어 읽으므로 그대로 오류로 끝낸다.
  - 재처리 잡과 같은 형식 검사기를 써서 평소 경로와 재처리 경로의 원장 줄이 같다.
- **확인한 결과:**
  - `python -m pytest -q pipelines/gold_b/tests/test_ingest.py`: 8개 통과. 실제 형식 검사기로 샘플 31건을 쓰면 ② 31줄, ① 9줄, ④는 샘플 기대 오류 수이고 `rule_version`은 모두 0.2.0.
  - `python -m pytest -q pipelines/gold_b/tests`: 108개 통과. `python -m pytest -q pipelines`: 193개 통과 (PC Python 3.12). `git diff --check` 통과.
  - 형식 검사 브랜치(최신 `main` #78 포함)와 파일 합치기 브랜치를 병합한 뒤 `pipelines/gold_b/tests` 136개, `pipelines` 221개 통과 (수집기 23개, 합치기 5개 포함).
  - 형식 검사기를 끼운 Spark 실행은 하지 않았다. ~~공용 Spark 이미지(`infra/platform/spark/image`, Spark 4.2.0)는 `spark-sql-kafka`·S3A가 들어 있지만 Python이 3.10이고, 결제 지문 함수는 3.11 기능(`datetime.UTC`)을 쓴다.~~ → 2026-10-23 바뀜: #82와 형식 검사 브랜치의 수정으로 Gold B 코드가 Python 3.10에서 돈다 (아래 보완).
- **다음 할 일:** ~~Python 3.11 이상 실행 이미지(또는 코드를 3.10에 맞출지) 정하기~~ (3.10에 맞춤), Gold B 이미지 Dockerfile, 배포 설정과 EKS 상시 실행 확인 (재영 님), 시뮬레이터 메시지가 1~2분 안에 원장에 보이는지 확인.

### 보완 (2026-10-23): Python 3.10 맞추기와 배포 설명

- **무엇을 했나:** Python 3.10 수정이 든 `pipelines/gold-b-format-check`(최신 `main` #82·#83·#84 포함)를 다시 병합했다. `jobs/README.md`의 「적재 잡 배포에 필요한 것」을 팀 기본 Spark 이미지(Spark 4.2.0, Python 3.10.12) 기준으로 고쳤다: 그 이미지에서 출발해 공통 모듈(`pipelines/*.py`), `pipelines/gold_b/`, 규칙표, Gold B 패키지(3.10은 pyarrow 25.0.1)를 넣는다. 설계 문서 4단계의 배포 항목도 같이 고쳤다.
- **왜:** #82가 팀 공용 실행 이미지를 Python 3.10.12로 고정했고, 형식 검사 브랜치에서 Gold B 코드를 3.10에 맞췄다. 적재 잡은 Spark 위에서 돌아서 팀 기본 Spark 이미지를 그대로 쓸 수 있다.
- **확인한 결과:** `pipelines/gold_b/tests` 139개 통과 (Python 3.12). 같은 코드(이 병합과 같은 시험용 병합)로 Python 3.10.12 컨테이너에서도 139개 통과했다 (형식 검사 작업 지시서 「보완: Python 3.10 맞추기」). `pipelines` 전체는 234개 통과, 오류 13개는 #82의 Silver·Gold A Spark 시험(로컬 Spark·`SPARK_TEST_INPUT` 필요)이다. `git diff --check` 통과.
- **다음 할 일:** Gold B 이미지 Dockerfile (팀 기본 Spark 이미지 FROM), 배포 (재영 님). main의 Kafka 보관 기간이 #86으로 7일이 되어, 재처리 잡의 보관 기준(72시간)과 문서의 "3일"을 맞출지 정해야 한다.
