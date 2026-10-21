# 작업 지시서: pipelines/gold-b-collector

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-collector` (`pipelines/gold-b` 위에서 갈라짐) · 다음 작업: 형식 검사 또는 정리 뷰 (팀원 답에 따라)

## 목표

S3 Sink 커넥터가 Kafka 메시지를 얼마나 밀려서 처리하는지 1분마다 재서 `gold_b.bronze_lag_snapshots` 형식으로 쌓는 **Bronze 지연 수집기**를 만든다. 배포 설정(EKS)과 실제 커넥터 연결은 만들지 않는다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「입력」의 Bronze 지연 정보, 「③ `bronze_lag_snapshots`」
- `pipelines/gold_b/ddl/bronze_lag_snapshots.sql` (컬럼 8개, `collected_at` 시간 폴더)
- `connectors/bronze-s3-sink.yaml`, `connectors/README.md` (파일 전환 15분, 처리 위치는 파일을 쓸 때 기록)
- `simulator/src/sim/common/kafka.py` (Kafka 접속 환경변수 이름, 로그에 브로커 주소를 남기지 않는 방식)
- `agent/detect/rules.py` (`main`): R3가 `lag_sec` 1200초 이상 또는 측정 줄 3분 없음으로 판정

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- #36이 머지 전이라 `pipelines/gold-b` 위에서 갈라졌다. push는 #36 머지 뒤 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 정한 규칙 (2026-10-21 사용자 승인)

1. 처리 기록이 없으면(커넥터가 한 번도 처리 위치를 기록하지 않음) `committed_offset`, `lag_msgs`, `lag_sec`를 모두 NULL로 둔다.
2. 처리할 메시지가 보관 기간으로 지워졌으면 `lag_msgs`는 그대로 적고, `lag_sec`는 남아 있는 가장 오래된 메시지로 계산한다 (실제보다 작게 나온다).
3. `connector_state`: 커넥터 상태. 태스크가 RUNNING이 아니면 그 태스크 상태(예: FAILED), Connect에 접속하지 못하면 `UNREACHABLE`. Kafka에 접속하지 못하면 그 회차는 줄을 쓰지 않고 오류로 끝낸다 (탐지가 "측정 줄 없음"으로 잡는다).

## 시작 전 확인 (Claude가 한다)

- 브랜치 `pipelines/gold-b-collector`가 `e1eddea`(#36 최신) 위인지
- Gold B 가상환경 `pipelines/gold_b/.venv`에 `confluent-kafka` 설치 (사용자 허락)
- 로컬 Kafka 확인용 Docker Desktop

## 만드는 것

- `pipelines/gold_b/collector/bronze_lag_collector.py`: 수집기 (한 번 실행 `--once`, 반복 `--interval 60`)
- `pipelines/gold_b/collector/README.md`, `.env.example`: 실행 방법, 환경변수(더미 값), 값의 뜻
- `pipelines/gold_b/requirements.txt`: Gold B 패키지 (Silver의 `pipelines/requirements.txt`는 건드리지 않음)
- `pipelines/gold_b/tests/test_lag_collector.py`: 가짜 Kafka·Connect 응답으로 계산과 파일 쓰기 시험
- `pipelines/gold_b/README.md`, 설계 문서 ③: 수집기 한 줄과 수집 규칙

## 만들지 않는 것

- `deploy/` 배포 설정, 이미지, EKS 실행 (재영 님과 정한 뒤)
- 실제 `bronze-s3-sink` 연결, Athena 테이블 생성
- 파일 합치기 (6단계)

## 작업 순서

1. 계획 제시와 승인 (2026-10-21 완료)
2. 작업 지시서·브랜치 대장 커밋
3. 수집기 본체·README·패키지 목록 커밋
4. 단위 시험 커밋
5. 로컬 Kafka로 실제 확인 (Docker)
6. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경)
- [ ] 로컬 Kafka에 한 번 실행해 실제 위치·시각을 읽고 시간 폴더에 Parquet 파일이 생기는지
- [ ] 코드·README·`.env.example`에 비밀값·실제 주소·버킷 이름이 없는지 (`git grep`)

## README 갱신

- `pipelines/gold_b/collector/README.md` 새로 만듦
- `pipelines/gold_b/README.md`에 수집기 줄 추가

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:**
- **무엇을 만들었나:**
- **왜 그렇게 했나:**
- **입력과 출력:**
- **확인한 결과:**
- **알려진 한계·남은 일:**
