# 작업 지시서: pipelines/gold-b-image

> 상태: 완료 (#98, 2026-10-24 머지) · 브랜치: `pipelines/gold-b-image` (최신 `main` #92에서 만들고, #95 머지 뒤 최신 `main` 위로 옮김) · 남은 일: 팀 기본 Spark 이미지 ECR digest가 나오면 빌드·ECR, 적재 잡·수집기 배포 (재영 님)

## 목표

Gold B 잡 4개(적재 잡, 재처리 잡, 파일 합치기, Bronze 지연 수집기)를 돌릴 **Gold B 이미지**의 Dockerfile을 만든다. 팀 기본 Spark 이미지(Spark 4.2.0, Python 3.10.12, Kafka 연결·S3A 포함)에서 출발해 Gold B 코드와 패키지를 더한다. 이미지를 ECR에 올리고 배포하는 것은 재영 님과 한다.

## 먼저 읽을 것

- `infra/platform/spark/image/README.md`: 팀원은 기본 이미지 digest를 FROM으로 받아 업무 코드와 Python 패키지를 더한다
- `pipelines/Dockerfile`, `pipelines/Dockerfile.dockerignore`: Silver·Gold A 이미지 (같은 방식, Gold B 코드는 빠져 있음)
- `pipelines/README.md` 「실행 환경·이미지」, `pipelines/gold_b/jobs/README.md`의 배포 절

## 이번 작업의 특례

- 처음에는 첫 커밋(`8ca6a10`)에 머지된 #88·#91·#92의 정리(브랜치 대장, 작업 지시서 상태, 설계 문서 PR 표시)를 넣었다. 같은 커밋이 결제 UPDATE 처리 #95에 들어가 머지되어서, 아직 push 전인 이 브랜치를 #95 머지 뒤 최신 `main` 위로 옮겼다 (2026-10-23, 브랜치 대장 충돌만 정리).
- #91을 머지하기 전에 GitHub에서 main을 합친 커밋이 브랜치 대장 gold-b 표와 Gold B README 표 중간에 빈 줄을 넣어 표가 끊겼다. 그 빈 줄도 뺐다 (내용 차이는 빈 줄 3개뿐인 것을 확인).

## 정한 기본값 (설계에 없는 세부. 2026-10-23 제안, 2026-10-24 사용자가 적재 잡을 이어서 하라고 해서 이대로 만듦)

1. **위치:** `pipelines/gold_b/Dockerfile`, 넣을 파일 목록은 `pipelines/gold_b/Dockerfile.dockerignore`. 빌드는 저장소 루트에서 `docker build -f pipelines/gold_b/Dockerfile ...` (공통 모듈과 규칙표가 Gold B 폴더 밖에 있음).
2. **출발 이미지:** `SPARK_IMAGE` 빌드 인자로 팀 기본 이미지 digest를 반드시 받는다 (기본값 없음). 공식 `apache/spark` 이미지에는 Kafka 연결 jar가 없어 적재 잡이 돌지 않는다. Gold B는 jar를 따로 받지 않는다.
3. **넣을 것:** 공통 모듈 `pipelines/*.py`(시험 파일 제외, 앞으로 생길 공통 모듈도 빠지지 않게), `pipelines/gold_b/`의 코드와 `config/gold_b.yaml`, `docs/contracts/format_rules.yaml`. 시험·`.local`·캐시·`.env`는 넣지 않는다. 폴더(`!pipelines/`)를 통째로 다시 넣으면 Docker 규칙상 그 아래가 모두 들어가서, 파일 단위(`!pipelines/gold_b/jobs/*.py` 등)로만 다시 넣는다.
4. **패키지:** `pipelines/gold_b/requirements.txt` (Python 3.10은 pyarrow 25.0.1). 빌드 중 Python이 3.10인지 확인한다.
5. **이미지 안:** 코드 위치 `/opt/gold_b`(`PYTHONPATH`). 빌드 인자 `CODE_REF`(머지된 main 커밋)를 환경변수로 남긴다. 실행 사용자 185, 기본 이미지의 Spark 진입점을 그대로 쓴다 (Silver 이미지와 같음).
6. **잡 실행 명령:** 적재 잡 `spark-submit local:///opt/gold_b/pipelines/gold_b/jobs/streaming_ingest.py`, 재처리 `python3 -m pipelines.gold_b.jobs.reprocess`, 합치기 `python3 -m pipelines.gold_b.jobs.compact`, 수집기 `python3 -m pipelines.gold_b.collector.bronze_lag_collector`.
7. **시험:** 빌드 없이, 넣을 파일 목록이 Gold B 잡이 부르는 모듈(공통 모듈 포함)을 모두 담고 시험 파일은 빼는지 확인한다. Docker(moby patternmatcher)의 `.dockerignore` 규칙을 시험 안에 그대로 옮겨 저장소 파일을 거른다. 빌드할 때는 Kafka 연결·S3A jar가 있는지, 잡 4개가 import되는지 Dockerfile이 확인한다.
8. **실제 빌드:** 팀 기본 이미지가 ECR에 올라온 뒤에 한다. 그 전에 로컬에서 기본 이미지를 받아 빌드하려면 그때 사용자에게 묻는다.

## 만드는 것

- `pipelines/gold_b/Dockerfile`, `pipelines/gold_b/Dockerfile.dockerignore`
- 시험 `pipelines/gold_b/tests/test_image.py`
- `pipelines/gold_b/README.md` 이미지 절, `jobs/README.md` 배포 절의 이미지 설명, 설계 문서 폴더 구조에 Dockerfile, `docs/BRANCHES.md` 한 줄

## 만들지 않는 것

- ECR 저장소와 push, Airflow DAG, 적재 잡·수집기 배포 설정, Pod 권한 (재영 님)
- 결제 UPDATE 처리 (`pipelines/gold-b-payment-update`), Bronze 재처리 (다른 브랜치)

## 작업 순서

1. 머지 정리와 계획 제시 (2026-10-23)
2. 작업 지시서·브랜치 대장 커밋 (2026-10-23, #95 머지 뒤 최신 `main` 위로 옮김)
3. Dockerfile·넣을 파일 목록·시험·README 커밋 (2026-10-24, 사용자: 적재 잡을 이어서)
4. "완료 확인" 실행과 작업 결과 기록 (2026-10-24)

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (198개, 로컬 Python 3.12)
- [x] 넣을 파일 목록이 잡이 부르는 모듈을 모두 담는지 (시험)
- [ ] (팀 기본 이미지가 생기면) 빌드, 이미지 안에서 Gold B 모듈 import와 잡마다 `--help`

## 작업 결과 (머지 전에 작성한다)

### 무엇을 만들었나

- `pipelines/gold_b/Dockerfile`: 팀 기본 Spark 이미지(`SPARK_IMAGE`, 기본값 없음)에서 출발. Kafka 연결·S3A jar와 Python 3.10 확인 → `requirements.txt` 설치 → 코드·형식 규칙표 복사 → `CODE_REF` 확인과 잡 4개 import → 사용자 185, Spark 진입점.
- `pipelines/gold_b/Dockerfile.dockerignore`: 넣는 파일 17개 (공통 모듈 `pipelines/*.py` 5개, Gold B 코드 10개, `config/gold_b.yaml`, `requirements.txt`, 형식 규칙표). 시험·문서·Athena SQL·Silver·Gold A 코드·로컬 파일은 뺀다.
- `pipelines/gold_b/tests/test_image.py`: Docker의 `.dockerignore` 규칙으로 저장소 파일을 걸러, 잡 4개의 import를 따라간 모듈이 모두 들어가고 정해 둔 파일만 들어가는지, 로컬 가상환경·캐시·`.env`·작업 폴더가 빠지는지, Dockerfile의 약속(출발 이미지, jar 확인, 코드 위치, 사용자, 진입점)을 본다.
- 문서: Gold B README 「이미지」(빌드 명령, 잡마다 실행 명령), `jobs/README.md` 「적재 잡 배포에 필요한 것」(제출 명령, 상시 실행, 자원 제안, S3 권한과 체크포인트 위치 제안, Kafka 사용자·ACL·인증서), 설계 문서 파일 구조·4단계 체크리스트·팀원 확인 표.
- 수집기 기본 커넥터를 `bronze-s3-sink-v2`로 바꿈 (2026-10-24 주현 님 요청, 성철 님 확인: S3 Sink 정지 사건이 v2를 멈춤). 배포 때 `GOLD_B_SINK_CONNECTOR`를 따로 넣지 않아도 된다. 소비자 그룹은 `connect-bronze-s3-sink-v2`로 따라간다. 배포 준비라 이 브랜치에 같이 넣었다.

### 왜

판정 잡이 R1·R4·R5를 읽으려면 원장 ①②④에 데이터가 쌓여야 한다. 적재 잡을 EKS에서 돌리려면 이미지가 먼저 있어야 하고, 배포(재영 님)에 필요한 값을 한곳에 모았다.

### 확인한 결과 (2026-10-24)

- `python -m pytest -q pipelines/gold_b/tests`: 198개 통과 (Python 3.12). 새 시험 `test_image.py` 17개.
- `docker build --check -f pipelines/gold_b/Dockerfile`(로컬에 있는 Spark 이미지로 메타데이터만 읽음): 경고 없음. `SPARK_IMAGE`에 일부러 기본값을 두지 않아 생기는 경고는 Dockerfile 맨 위 `check=skip`으로 끔.
- 실제 빌드는 하지 않았다. 팀 기본 Spark 이미지가 아직 ECR에 없고, 로컬에서 만들려면 Spark·Maven 이미지와 jar·패키지를 받아야 한다.

### 다음 할 일

- 재영 님: 팀 기본 Spark 이미지 ECR digest, Gold B 이미지 ECR 저장소, 적재 잡 배포(namespace·Pod Identity·S3 권한·체크포인트, Kafka `KafkaUser`·ACL·인증서·클라이언트 리스너 허용, 늘 켜 둔 Spark 스트리밍). 필요한 값은 `pipelines/gold_b/jobs/README.md` 「적재 잡 배포에 필요한 것」.
- 머지 뒤 main 커밋으로 빌드해 ECR에 올리고, 원장 세 표에 줄이 쌓이는지 Athena로 확인한다 (시뮬레이터 메시지가 1~2분 안에 보이는지).
- 수집기 배포는 따로 한다 (CronJob `--once` 또는 상시 `--interval 60`, 재영 님과).
- `pipelines/gold-b-reprocess-by-message`와 브랜치 대장 gold-b 표 끝에서 충돌한다. 나중에 올리는 PR 전에 먼저 머지된 쪽을 받아 정리한다.
