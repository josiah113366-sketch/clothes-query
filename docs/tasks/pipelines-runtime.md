상태: 완료 · Spark 거래·리뷰 로컬 검증 완료, 실제 배포 대기 · 브랜치: `pipelines/runtime`

# Silver·Gold A 운영 실행 연결

## 승인 범위

- 사용자 승인: 기존 계산 코드를 호출하는 처리 이미지·S3 실행기·수동 Airflow DAG 구현.
- 최신 main에서 브랜치를 만들고 선행 Gold A #67 코드를 로컬에 포함했다. #67 main 반영 후 이 브랜치도 main과 동기화한다.
- 공통 입력 규약·계산 규칙은 변경하지 않는다. 처음 일반 Python 시제품으로 구현했으나 사용자가 Spark 실행 엔진을 정정하고 PySpark 전환부터 진행하도록 승인했다. Spark 전환은 현재 승인 범위다. Kafka 소비·인프라 apply·이미지 push·운영 실행은 포함하지 않는다.
- namespace·ServiceAccount·ECR 이미지 digest·노드 배치는 인프라가 공급한다. 기존 agent 신원을 재사용하지 않는다.

## 구현 파일 · 현재 구조

- pipelines/spark_batch.py: 공통 Spark 진입점·S3 URI/입력 목록·ETag 확인·Parquet 저장·거래 처리.
- pipelines/silver/reviews.py: 공통 리뷰 정제와 Spark 리뷰 정제.
- pipelines/gold_a/reviews.py: 리뷰 규칙·검색·부분 재처리와 Spark 리뷰 상품 연결/집계/실행.
- pipelines/Dockerfile·Dockerfile.dockerignore·requirements.txt: Spark 업무 이미지·의존성·원문/시험/캐시 제외.
- infra/platform/airflow/dags/silver_gold_a.py: 수동 Spark cluster 제출·최종 완료 대기·단일 실행.
- pipelines/tests/test_spark_batch.py·test_spark_reviews.py: 실제 Spark 엔진에서 계산/Parquet/실패 경계 검증.
- 기존 README와 브랜치 대장에 실행·설정·후속 연결을 기록한다.

## 완료 확인

- 가짜 S3로 실제 Silver → Gold A 판매·퍼널·리뷰 점수 실행. 모든 출력 참조가 존재하고 로컬 임시 경로가 남지 않는지 확인.
- 금액 MISMATCH도 Silver 완료 기록과 R6 상세에 보존하며 Gold A 최신 결과를 유지.
- 다운로드 누락·입력 변경·크기 초과·업로드 실패가 정상 완료로 공개되지 않는지 확인.
- 전체 pipelines 회귀·Ruff·DAG 구문 검사·가능하면 이미지 빌드. 운영 검증과 로컬 검증을 구분한다.

## 작업 결과

### Spark 거래 전환 · 사용자 정정 후 현재 작업

- 처음에는 Python 3.12를 결합해 검증했으나 인프라 확정 환경에 맞춰 팀 기본 Spark 이미지 확장 방식으로 변경했다. Spark 4.2.0·Python 3.10.12·Java 21·Scala 2.13·Hadoop/S3A 3.5.0·SDK bundle 2.35.4를 기준으로 한다. 공통 코드의 datetime.UTC를 timezone.utc로 바꾸고 ISO Z 시각을 +00:00으로 파싱해 Python 3.10에서도 동일한 업무 값과 지문을 계산하도록 호환성을 보완했다. 규칙 버전·업무 정책은 변경하지 않는다.
- pipelines/spark_batch.py: 원천 파일 메타데이터만 Driver에서 고정하고 원문은 Executor에서 읽는다. DataFrame 전역 키 검사 후 주문별 복원/검사를 Executor에 분산하고 Gold A는 Spark SQL 집계로 계산한다. 전체 업무 행 collect는 사용하지 않고 파일/주문 크기 한도 초과를 실패 처리한다.
- 기존 거래 함수에 주문 경계 외부 오류 전달용 비공개 인자를 추가했다. 기본 동작은 유지하며 Spark의 주문 간 동일 payment_id 충돌과 연결 불명 상품 오류까지 Python 기준 결과와 비교한다.
- Silver·R6 Parquet 저장 및 완료 공개 → 저장된 Silver Parquet 재조회 → Gold A 판매 Parquet 저장을 구현했다. UTC는 TIMESTAMP_MICROS, KST 오프셋 시각은 STRING, 판매 날짜는 DATE, 금액/수량은 BIGINT다. manifest에 실제 물리 schema·건수·원본 참조·Spark application ID·규약 버전을 기록한다.
- 실제 Spark 4.2.0 local[2] Linux 엔진에서 정상/동일 결제 중복·UTC/KST 동시각, 주문 간 내용 충돌, 연결 불명 상품 오류, 금액 불일치, Parquet 재조회 및 실패 시 이전 Gold 유지의 3개 비교 시험을 통과했다(51.479초, 저장 재조회 보완 후 54.953초). 실제 EKS Driver/Executor Pod 분산 실행 검증과는 구분한다.
- Python 기존 회귀 115개 통과(18.18초), Windows에 PySpark를 설치하지 않아 Spark 전용 시험 모듈 1개는 host pytest에서 건너뛰고 위 Linux spark-submit으로 별도 실행했다.
- DAG는 일반 Python 명령 대신 spark-submit cluster mode·최종 완료 대기·동적 Executor 1~2개·별도 세 ServiceAccount를 사용하도록 바꿨다. 실제 노드 자원·권한·이미지 digest 공급은 인프라와 맞춘다.
- 실제 S3 SDK·파일시스템 경로 검증은 외부 통신 없는 Docker 내부 네트워크의 Moto 5.1.15에서 수행했다. Spark 4.2.0 S3A magic committer → Silver Parquet → 저장 결과 재조회 → Gold A Parquet → 완료 manifest까지 통과했다. 정상 승인 금액 30,000원, 객체 63개, 성공 후 __magic/_temporary 작업 객체 0개를 확인했다. AWS 실제 접근·IAM·Pod Identity 검증은 아니다.
- 커미터 로그에서 데이터셋 폴더 안의 __magic_job-*/ 작업 객체와 멀티파트 시작·완료·목록 조회·정리를 확인했다. 임시 S3 권한은 이 동작에 맞춰 인프라와 제한한다. 별도 S3 tmp prefix를 근거 없이 확정하지 않는다.
- README를 실제 Spark 진입점·명령·설정 키·파티션/물리 스키마·완료 공개·원본 메타데이터로 교체했다. 이전 batch.py는 이 단계에서 시제품으로 보존했으나 아래 사용자 요청 정리 단계에서 제거했다.
- 거래 단계 완료 범위는 거래 Silver/판매 Gold A다. 리뷰는 아래 후속 절에서 전환했으며 클릭·퍼널·회원 Spark 전환, Glue/Athena 공개 대상 선택, 운영 S3 권한·Pod Identity·DAG 배포·실제 검증 데이터 범위는 아직 완료하지 않았다.

- 확정 환경 재검증: Python 3.10.12 / Spark 4.2.0 이미지 빌드 성공, 실제 Spark 비교 시험 3개 통과(46.088초), Z 시각 파싱·PyArrow 25.0.1 import·pip check 통과. 같은 Python 3.10 이미지로 S3A magic → Silver/Gold A 저장도 재검증해 승인 금액 30,000원·객체 63개·잔여 작업 객체 0개를 확인했고 임시 컨테이너/네트워크를 정리했다. 호스트 회귀 115개 통과·Spark 전용 모듈 1개 별도 실행, Ruff는 Python 3.10 대상으로 검사했다. 로컬 검증 이미지의 CODE_REF는 작업 중임을 표시한 값이며 배포 시 최종 커밋으로 재빌드한다.
- Airflow가 main의 infra/platform/airflow/dags/를 약 60초마다 동기화한다는 인프라 확인을 반영했다. 신규 DAG paused와 수동 단일 실행을 유지하며 이전 ConfigMap/subPath 별도 마운트 안내를 제거했다. 팀 ECR 주소·digest는 발행 대기다.

### 리뷰 Spark 전환

- 인프라 응답 대기와 병행해 기존 리뷰 Silver·Gold A 계산을 Spark 실행기로 연결했다. job=reviews로 같은 진입점·DAG를 사용한다. 처음 spark_reviews.py와 test_spark_reviews.py로 추가했으나 아래 사용자 요청에 따라 실행 코드는 기존 Silver/Gold 리뷰 파일에 통합했다. 별도 DAG·규약 문서는 늘리지 않았다.
- Executor에서 review_id별 기존 collect_latest/normalize_review를 호출해 오류 키·동시각 충돌·최신 emitted_at을 처리한다. 원본 참조는 파일/줄로 보존하며 KST 범위 선택은 전체 키 검사 후 수행한다. ID당 행 한도로 Executor 메모리의 무한 증가를 막는다.
- 상품 기준정보 직접 연결과 명시적 매핑, 별점 1~2점 저평점 집계, -2~2 속성 점수 분포·평균을 Spark SQL로 계산한다. JSONL/CSV 모델 입력과 모델 버전 선택을 지원하며 결과 없음은 0점으로 세지 않는다. 분석 완료 여부는 UNVERIFIED다.
- Silver Parquet을 저장한 뒤 재조회해 Gold A를 계산한다. 리뷰 품질 미완료는 Silver 근거를 공개하되 Gold A를 교체하지 않는다. 정상 빈 파일 입력은 0행 결과로 공개하며 파일 자체가 없는 경우와 구분한다. 평가 정답표 경로는 거부한다.
- Spark 4.2.0 / Python 3.10.12 local[2]에서 리뷰 시험 3개 통과(82.902초): KST 날짜 경계·최신 버전·동일 내용 중복·충돌·잘못된 별점·기존 Python 수치 비교·모델 중복/충돌/범위 밖 ID·미분석 제외·Parquet 재실행·오류 시 이전 Gold 유지·CSV·상품 매핑·정상 0건을 검증했다.
- 공통 실행기 변경 후 거래 Spark 시험도 3개 재검증 통과(64.154초). 기존 Python 회귀 115개 통과, Spark 모듈 2개는 host에서 건너뛰고 실제 Linux Spark로 별도 검증한다. 실제 AWS 리뷰/모델 파일·권한 검증은 아직이다. 입력 자동 창 계산·부분 범위 병합·Glue 공개·정기 실행 연결도 후속이다.

### 사용자 요청: 필요한 실행 코드만 유지

- 별도 spark_reviews.py를 제거하고 Spark 정제는 silver/reviews.py, 리뷰 Spark 집계/실행은 gold_a/reviews.py에 통합했다. 공통 정제·모델 규칙은 기존 함수/상수를 공유한다. Spark 의존성은 함수 호출 시 읽어 기존 단위 검사도 실행 가능하게 했다.
- 사용하지 않는 단일 Python S3 실행기 batch.py와 그 실행기에만 해당하는 test_batch.py를 제거했다. S3 URI 검사와 JSON 저장은 운영 공통 진입점 spark_batch.py로 옮겨 구 실행기 import를 없앴다.
- 검증: Python 회귀 107개 통과(구 실행기 전용 시험 8개 제거), Spark 전용 모듈 2개는 별도 실행. 통합 후 실제 리뷰 Spark 시험 3개 재통과(64.593초), Ruff Python 3.10 검사 통과. 구 batch.py 의존성 제거 후 S3A 에뮬레이터 검증도 통과해 승인 금액 30,000원·객체 57개·잔여 작업 객체 0개를 확인했고 임시 컨테이너/네트워크를 정리했다.
- 아직 사용되는 데이터셋별 정제/계산 함수·검색·부분 재처리를 무작정 삭제하지 않는다. 운영 DAG 진입점은 Spark 하나이며 기존 Python 집계는 기준 수치 비교에도 쓰인다. 아래 단일 Python 시제품의 실행 기록은 과거 기록이다.

### 이전 단일 Python 시제품 검증 기록

- 처리 이미지 정의·S3 실행기·수동 DAG를 구현했다. 거래/퍼널/리뷰/회원 작업 선택, ETag 입력 고정·기본 128MiB 제한, 실행별 S3 참조 치환, Silver 검사와 Gold A 완료 공개 분리, current의 조건부 쓰기를 제공한다. 원문·정적 AWS 키는 로그나 이미지에 포함하지 않는다.
- 운영 어댑터 시험 8개 통과: 실제 판매·퍼널·리뷰 점수·회원 실행, 금액 MISMATCH의 R6 보존, 이전 Gold A 유지, 원본 변경/누락/크기 초과, Gold 업로드 실패, UTC/KST 리뷰 범위와 Windows 긴 경로 참조. 가짜 S3를 사용했으며 실제 운영 데이터 처리 검증이 아니다.
- 전체 pipelines 115개 통과(17.19초), 변경 Python Ruff·구문 검사·git diff --check 통과, 로컬 pip check 통과.
- Windows 로컬 Airflow 실행은 os.register_at_fork 미지원으로 실패했다. 실행 중인 EKS Airflow 3.3.2 DAG processor에서 소스를 메모리로만 파싱해 DAG ID/두 태스크/선행 관계·수동 단일 실행·Pod 신원 설정·BATCH_CONFIG JSON 템플릿을 확인했다. DAG 파일 저장·배포·Trigger·업무 Pod 생성은 하지 않았다.
- 처음에는 Docker Linux 엔진이 꺼져 빌드하지 못했으나 설치된 Docker Desktop을 백그라운드로 시작해 로컬 이미지 빌드에 성공했다. 빌드 컨텍스트의 .local·캐시·테스트 제외를 명시적으로 보완하고 Git 커밋 없는 빌드를 거부한다.
- 최종 이미지 clothes-query-pipelines:runtime-local은 코드 커밋 95a32e76e4240d4cc2d9325488174a5d6b637325를 기록한다. 로컬 이미지 ID는 sha256:26396c6234c5203832bf795c0ff0d6f87267a3043372994739094804db7ac930다. ECR에 업로드한 digest가 아니다.
- Linux 이미지 검증: 비관리자 UID 10001, pyarrow import, Asia/Seoul 시간대, /app 안의 .local/.env/__pycache__ 비포함, 실제 CLI help 확인. 네트워크를 끄고 읽기 전용 합성 입력을 마운트해 거래·퍼널·리뷰 모델 점수까지 가짜 S3로 각각 PASS를 확인했다. 처음의 마운트된 시험 스크립트 직접 실행은 /app import 경로 부재로 실패했으며 실제 모듈과 동일한 작업 디렉터리의 import 경로에서 다시 검증했다.
- 마지막 경계 보완 후 운영 어댑터 8개 재검증 통과(3.66초), Ruff·diff 검사 통과. 이미지 push·namespace·ServiceAccount·Pod Identity/S3 권한·ECR 저장소·DAG 마운트는 아직 생성하지 않았다. 운영 데이터·S3 쓰기·Airflow Trigger는 실행하지 않았다.
- 상품 기준정보 JSONL 스냅샷의 실제 S3 위치, 실제 Bronze 크기·형식·완전성, 모델 결과 완료 범위, 실제 R6 판정 소비, 정기·부분 재처리·A/B 대조 연결은 후속이다. 현재 실행기는 전체 입력 스냅샷 방식이며 기존 범위별 보류·부분 병합을 자동 호출하지 않는다.
