# 데이터 파이프라인

## 운영 실행 연결 · Spark 거래 배치

최종 실행 엔진은 **Spark**다. 운영 진입점은 `spark_batch.py` 하나다. 이전 단일 Python S3 실행기 `batch.py`는 제거했다. Spark 실행 범위는 거래 Silver·판매 Gold A와 리뷰 Silver·리뷰 Gold A다. 클릭·퍼널·회원 Spark 전환과 실제 운영 배포는 별도다.

### 실행 환경·이미지

인프라가 확인한 Spark 4.2.0 / Python 3.10.12 / Java 21 / Scala 2.13을 사용한다. 운영 이미지는 발행 예정인 팀 기본 ECR 이미지 digest를 SPARK_IMAGE 빌드 인자로 지정해 확장한다. 공식 apache/spark:4.2.0 기본값은 로컬 검증용이다. Hadoop 3.5.0에 맞춰 hadoop-aws 3.5.0, AWS SDK v2 bundle 2.35.4, analyticsaccelerator-s3 1.3.1, wildfly-openssl 2.2.5.Final, spark-hadoop-cloud_2.13 4.2.0을 포함한다. 버전은 공식 이미지 및 Hadoop POM으로 확인했다. Driver·Executor는 같은 이미지 digest·코드·YAML·지문 함수를 사용한다. Python 3.10은 PyArrow 25.0.1, Python 3.11 이상 참조 실행은 26.0.0을 설치한다. Spark Parquet 저장은 Spark 자체 writer를 사용한다.

```powershell
docker build -f pipelines/Dockerfile --build-arg SPARK_IMAGE=<팀-기본이미지>@sha256:<digest> --build-arg CODE_REF=<Git-커밋> -t <업무-ECR-이미지>:<태그> .
```

이미지는 Spark 공식 Kubernetes entrypoint를 사용한다. 코드 위치는 `/opt/pipelines`, 진입점은 `local:///opt/pipelines/pipelines/spark_batch.py`다. 원문·.local·캐시·시험 파일은 이미지에서 제외한다.

### 실행 요청 JSON

```json
{
  "job": "trade", "run_id": "trade-20261022-001",
  "output_root": "s3://<데이터-버킷>/", "input_complete": true,
  "inputs": {
    "orders": ["s3://<데이터-버킷>/bronze/orders/"],
    "order_items": ["s3://<데이터-버킷>/bronze/order-items/"],
    "payments": ["s3://<데이터-버킷>/bronze/payments/"],
    "designs": ["s3://<데이터-버킷>/<상품스냅샷>/designs.jsonl"],
    "variants": ["s3://<데이터-버킷>/<상품스냅샷>/variants.jsonl"]
  }
}
```

접두사는 `/`로 끝낸다. Driver는 파일 목록·ETag·크기만 고정하고 Executor가 JSON Lines 본문을 읽는다. 확장자는 .json/.jsonl을 지원한다. 기본 제한은 최대 10,000개 파일, 파일당 64MiB, 주문당 10,000행이다. 주문당 한도는 max_order_rows(1~100,000)로 조정 가능하다. 초과 시 임의로 자르지 않고 실행 실패다.

거래는 필요한 변경 이력·주문상품·결제를 함께 준비한다. UTC 수집 날짜 폴더를 KST 일별 매출로 바로 취급하지 않는다. input_complete는 실행자의 준비 확인이며 원천 완전성을 증명하지 않는다. 입력 객체 ETag를 공개 전 다시 확인하지만 이는 특정 버전 직접 읽기·Kafka watermark 검증을 대신하지 않는다. 상품 JSONL 스냅샷의 실제 S3 위치는 아직 확인이 필요하다.

### 코드 구성

- spark_batch.py: 공통 운영 진입점·S3 입력/출력과 거래 Spark 처리
- silver/reviews.py: 공통 리뷰 정제 규칙과 Spark 리뷰 정제
- gold_a/reviews.py: 리뷰 지표·점수 규칙과 Spark 상품 연결/집계/실행
- 별도 spark_reviews.py와 이전 batch.py는 두지 않는다. 기존 데이터셋의 순수 Python 계산은 비교 검증 및 아직 필요한 검색·부분 재처리에 사용하며 운영 DAG는 Spark만 호출한다.

### 리뷰 실행 요청

같은 진입점과 DAG에서 job=reviews를 사용한다. 운영 리뷰 파일을 명시적으로 지정하며 정답표 입력은 거부한다. KST 날짜 선택은 파일 경로가 아니라 정제된 created_at 시각을 기준으로 수행한다. 필요한 UTC 날짜 파일을 빠짐없이 지정하는 책임은 실행 요청 생성 단계에 있다.

```json
{
  "job": "reviews", "run_id": "reviews-20261022-001",
  "output_root": "s3://<데이터-버킷>/", "input_complete": true,
  "start_date": "2026-10-19", "end_date": "2026-10-19",
  "model_version": "<모델-버전>",
  "inputs": {
    "reviews": ["s3://<데이터-버킷>/bronze/reviews/<대상-파일>.jsonl"],
    "designs": ["s3://<데이터-버킷>/<상품스냅샷>/designs.jsonl"],
    "variants": ["s3://<데이터-버킷>/<상품스냅샷>/variants.jsonl"],
    "analysis": ["s3://<데이터-버킷>/<모델-결과>/scores.csv"]
  }
}
```

analysis는 선택이다. 생략하면 review_product_daily만 생성하며 점수 집계를 임의로 만들지 않는다. 지정하면 model_version 필수, JSONL은 review_id/aspect/model_version/score를 검증하고 CSV는 review_id/aspect/score를 읽어 요청한 모델 버전을 붙인다. 점수는 -2~2 정수이며 중복 내용 충돌·범위 밖 리뷰 ID는 Gold 갱신을 중단한다. 미분석/속성 미언급을 0점으로 채우지 않고 분석 완료 상태는 UNVERIFIED로 기록한다.

리뷰 product_id는 상품 article_id와 직접 연결한다. 임시 키가 필요한 경우에만 inputs.mapping에 product_id/article_id JSONL을 지정하며, 매핑 중복·상품 누락을 거부한다. 속성은 기존 11개 범주를 사용하고 3분류 감성으로 변환하지 않는다.

리뷰는 silver/reviews.py의 build_reviews_spark가 Executor에서 review_id별로 공통 collect_latest/normalize_review를 호출해 최신 emitted_at·동시각 충돌·오류 키 보류를 처리한다. 그룹당 최대 10,000행(max_key_rows로 조정)이며 초과하면 실패한다. 상품 연결과 별점·속성 점수 집계는 Spark SQL로 수행한다. 평균·비율은 기존 Python의 HALF_UP 자리수와 맞춘다.

출력은 silver/runtime/reviews 및 gold_a/runtime/reviews 아래 동일한 runs/completed/current 구조다. Silver: silver_reviews/quarantined_records/dq_results, Gold: review_product_daily 및 선택적 review_aspect_daily다. 리뷰 검사는 reviews.v1이며 거래 공통 YAML을 적용했다고 기록하지 않는다. 각 manifest의 KST 범위를 확인해 사용하며 서로 다른 실행을 단순 합산하지 않는다. 현재 요청 범위 전체 스냅샷 방식이고 날짜·상품 부분 병합이나 자동 입력 창 계산은 아직 연결하지 않았다.

### Spark 처리 방식

- 행별 공통 YAML 검사·지문 계산은 Executor에서 수행한다.
- DataFrame groupBy/join으로 전체 ID 오류·주문 경계를 넘는 충돌을 검사한다.
- 주문별 데이터를 분산해 기존 복원·금액 검사 함수를 Executor에서 재사용한다. 전체 업무 데이터를 Driver로 collect하지 않는다. 주문 하나의 입력에는 위 행 수 한도를 적용한다.
- 연결 불명 주문상품 오류가 모든 주문 합계 검사에 미치는 영향도 전달한다. source_record_id·실제 원본 파일/줄로 추적하며 source_row_number는 주문 묶음 내 순번이다.
- Silver를 Parquet으로 저장하고 품질/완료 manifest를 공개한다. Gold A는 저장된 Silver Parquet을 다시 읽어 Spark SQL로 주문·매출·상품 판매를 집계한다.
- 품질 미완료면 Silver 검사·R6 근거는 보존하고 Gold A 갱신을 중단한다. 상품 기준정보 품질/연결 오류도 Gold A 공개를 중단한다.

### Airflow 제출 설정

인프라 확인 기준 Airflow는 main의 `infra/platform/airflow/dags/`를 약 60초마다 동기화한다. DAG 파일은 main 반영 후 발견되며 신규 DAG는 기본 일시정지 상태다. 별도 DAG ConfigMap/subPath 마운트를 추가하는 방식으로 안내하지 않는다. DAG processor·scheduler에는 AIRFLOW_PIPELINE_RUNTIME JSON을 공급해야 한다. DAG 발견과 실행 권한·이미지 준비는 별개다.

```json
{
  "image": "<ECR-이미지>@sha256:<64자리-digest>",
  "namespace": "pipelines",
  "submitter_service_account": "<제출기-SA>",
  "driver_service_account": "<Driver-SA>",
  "executor_service_account": "<Executor-SA>",
  "node_selector": {"<전용노드-라벨>": "<값>"},
  "spark_conf": {"spark.sql.shuffle.partitions": "8"}
}
```

제출기→Driver→Executor의 RBAC·Pod Identity/S3 권한은 인프라가 연결한다. Driver는 Executor Pod·Service·ConfigMap을 관리할 권한이 필요하다. 실행 파일·공통 YAML은 이미지에 포함하므로 별도 업로드가 필요 없다. 요청 JSON 읽기와 manifest 저장은 Driver, S3 Parquet 입출력은 Driver/Executor에서 수행한다.

Airflow DAG ID는 `silver_gold_a_batch`, schedule 없음·초기 paused·max_active_runs=1·자동 재시도 0이다. Trigger conf는 다음과 같다.

```json
{"config_uri":"s3://<버킷>/<실행요청>/trade-20261022-001.json"}
```

제출기는 spark-submit --master k8s://https://kubernetes.default.svc --deploy-mode cluster로 제출한다. `spark.kubernetes.submission.waitAppCompletion=true`로 Driver의 최종 종료까지 기다린다. 제출 명령 접수만으로 성공 처리하지 않는다. Executor는 min/initial=1, max=2, shuffle tracking을 사용한다. 자원 기본값은 코드의 초기 제안이며 실제 노드 allocatable·인프라 설정으로 조정한다.

### S3 결과와 완료 공개

```text
silver/runtime/trade/runs/<run_id>/<데이터셋>/part-*.parquet
silver/runtime/trade/runs/<run_id>/manifest.json
silver/runtime/trade/runs/<run_id>/products/<상품데이터셋>/part-*.parquet
silver/runtime/trade/runs/<run_id>/products/manifest.json
silver/runtime/trade/completed/<run_id>.json
silver/runtime/trade/current.json

gold_a/runtime/trade/runs/<run_id>/<집계데이터셋>/part-*.parquet
gold_a/runtime/trade/runs/<run_id>/manifest.json
gold_a/runtime/trade/completed/<run_id>.json
gold_a/runtime/trade/current.json
```

데이터셋은 기존 orders_current/order_status_history/silver_order_items/payment_attempts/quarantined_records/dq_results/order_amount_checks/impact_candidates와 상품 기준정보 2개, Gold A 판매 집계 2개다. manifest.outputs로 정확한 데이터셋 폴더를 찾는다. 고정 part 파일명을 가정하거나 runs 전체를 합치지 않는다. schema와 output_counts, Spark application ID·버전, 규칙/코드 버전, 입력 메타데이터도 기록한다.

UTC 업무 시각과 R6 checked_at은 Parquet TIMESTAMP_MICROS(세션 UTC), KST 오프셋 시각은 STRING, 판매 날짜는 DATE, 금액·수량은 BIGINT다. 원본 참조·format_rules 등 중첩 메타데이터 일부는 JSON STRING이다. 정확한 물리 스키마는 manifest.schemas에 저장한다. 거대한 DQ 배열 대신 상세는 격리·R6·영향 후보 테이블의 행으로 보존한다.

모든 데이터셋 저장 후 해당 계층 완료 기록을 공개한다. 실패 시 이전 공개 참조를 유지한다. 재실행은 새 run_id로 수행하고 기존 run_id 폴더를 덮어쓰지 않는다. R6는 미처리 Silver completed를 순서대로 읽어 order_amount_checks를 소비한다. 행 부재·검사 대기는 해소로 보지 않는다. 동일 작업을 DAG 외부에서 병렬 실행하지 않는다.

S3 저장은 Hadoop S3A magic committer를 사용한다. Parquet·커미터 작업 객체를 위한 Put/Get/List, 미완료 업로드 Abort·multipart 관련 작업과 Spark 작업용 객체 정리 권한이 필요하다. Bronze는 읽기 전용이며 기존 정상 결과의 일괄 삭제를 구현하지 않는다. 로컬 S3 에뮬레이터 검증에서는 각 데이터셋 폴더 아래 __magic_job-*/ 작업 키가 생성되고 완료 후 정리됐다. DeleteObject는 silver/runtime/trade/runs/*/__magic_job-*/* 및 gold_a/runtime/trade/runs/*/__magic_job-*/* 작업 키로 제한하는 안을 인프라와 검증한다. 상품 하위 데이터셋도 이 실행 prefix 안에 포함된다. AbortMultipartUpload·ListMultipartUploadParts는 최종 Parquet 객체의 업로드에도 필요하므로 magic 임시 키에만 제한하면 안 된다. ListBucketMultipartUploads는 버킷 수준 권한이며 prefix 제한 지원 여부를 확인해 연결한다. 이 검증은 실제 AWS IAM 검증을 대신하지 않는다. 로컬 shuffle은 Pod 임시 디스크이며 S3 tmp 폴더가 아니다.

### 배포·조회 연결에서 남은 사항

Gold A #67 main 반영, ECR 업로드·digest 고정, namespace·세 실행 신원/RBAC·S3 권한·전용 노드 자원·main DAG 동기화/실행 설정·실제 입력 첫 실행이 필요하다. Glue/Athena 테이블 생성·파티션 등록·공개된 run_id 선택은 아직 연결하지 않았다. current.json 갱신만으로 Athena가 최신 결과를 고르는 것으로 간주하지 않는다. 업무 조회는 공개 실행, R6는 모든 완료 검사 실행을 읽도록 별도 조회 계약이 필요하다.

클릭·퍼널·회원 Spark 전환, 시간대 부분 재처리 승인 DAG, 실제 A/B 대조 잡·모델 호출은 이번 거래 Spark 검증의 완료 범위가 아니다.

## 공통 결제 지문

`pipelines/payment_fingerprint.py`의 payment_fingerprint(payment)가 결제 업무 필드 9개를 정규화해 payment_content_hash/fingerprint_version을 반환한다. 호출/입력/버전 계약은 [공통 계약](../docs/contracts/README.md#결제-내용-지문-규약--payment-contentv1)을 따른다. 순수 표준 라이브러리 함수이며 추가 패키지는 없다. Silver는 공통 입력 검사 후 원본 시각 문자열로 호출해 정상 결제 결과에 해시·버전을 저장한다. Gold B의 호출·적재 연결은 후속 작업이다.

- 입력과 실행 방법은 `pipelines/silver/README.md`를 따른다.
- 거래 Silver는 펼쳐진 CDC와 공통 YAML 업무 규칙을 지원한다. 실제 AWS 데이터 검증은 별도다.
- Gold A의 입력과 실행 방법은 `pipelines/gold_a/README.md`를 따른다.
- Gold B의 관제용 원장 DDL과 후속 구현 범위는 `pipelines/gold_b/README.md`를 따른다.

공통 YAML 검사기는 `pipelines/format_rules.py`, 규칙 원본은 `docs/contracts/format_rules.yaml`이다. 실행 의존성은 `python -m pip install -r pipelines/requirements.txt`로 설치한다. 거래·회원·클릭 Silver가 연결돼 있으며 실행별 규칙 버전·내용 해시와 격리 rule_id를 기록한다. 리뷰·상품은 자체 검사를 유지한다. Gold B 실행 연결은 별도 담당 범위다.
