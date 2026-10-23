상태: 구현·로컬 검증 완료 · main 대상 PR #82 리뷰 요청 완료 · 운영 연결 전 · 브랜치: `pipelines/runtime`

# Silver·Gold A 운영 실행 연결

## 작업 범위

- 거래·클릭·리뷰 정제와 Gold A 판매·퍼널·리뷰 집계를 Spark 실행으로 연결한다.
- 상품 기준정보는 JSONL과 Parquet 입력을 지원하며 기존 계산·품질 기준을 유지한다.
- 처리 이미지·고정 S3 입력·실행별 결과 및 완료 기록·수동 Airflow DAG를 제공한다.
- S3A magic committer의 정상·실패 저장 경로와 정리 권한을 로컬에서 검증한다.
- namespace·ServiceAccount·ECR 기본 이미지·노드 배치는 인프라 명세에 맞춘다.
- 실제 EKS 실행, 최종 ECR 발행, Glue·Athena 공개, 정기 실행·재처리 DAG는 후속 작업이다.

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

### 상품 Parquet 입력 보완 (2026-10-23) · 검수 및 커밋 승인

- 실제 Glue hm_seed_v2의 상품 위치를 확인했다. hm-ecommerce-data/seed_v2/product_design/product_design.parquet(515,600바이트), product_variant/product_variant.parquet(2,043,237바이트)이며 별도 상품 버킷 읽기 권한이 필요하다.
- spark_batch.py의 resolve_inputs는 designs/variants에 한해 .parquet 객체를 고정하고 read_source는 Spark Parquet reader로 Executor에서 읽는다. JSONL과 공통 정제·타입·중복·내용 충돌·디자인 참조 검사를 재사용한다. 거래·퍼널·리뷰 모두 같은 reader를 사용한다. 원본 파일·ETag를 보존하며 Parquet 논리 순번은 물리 행 번호로 주장하지 않는다.
- 실제 Spark 4.2.0/Python 3.10.12: 상품 Parquet 거래·퍼널 실행, JSONL/Parquet 동일 내용 중복, 선행 0, 문자열 금액·내용 충돌·디자인 참조 누락 거부, 기존 JSONL 회귀 등 3개 시험 통과(47.989초). 리뷰 3개 시험도 통과(66.281초): JSONL 상품 최초 실행과 Parquet 상품 재실행의 지표 동일, CSV 점수·매핑·정상 0건·오류 시 이전 결과 유지 검증.
- S3에서 상품 두 파일만 읽기 전용으로 내려받아 외부 통신 없는 로컬 Spark에서 기존 catalog 검사를 통과했다. 디자인 44,623행·상품 101,452행·총 2,558,837바이트. 이는 실제 EKS/S3A/Pod Identity 검증은 아니다. 실제 데이터는 Git 제외 .local 시험 폴더에만 두었다.
- 첫 시험은 fixture 마운트 경로가 잘못되어 0개 실행, 리뷰 단독 시험은 클래스명 오타로 0개 실행 후 정정해 위 실제 시험을 통과했다. Ruff Python 3.10·git diff --check 통과.
- 커밋 전 변경 5개 파일의 전체 diff·호출 경로를 검수했고 Ruff Python 3.10·git diff --check를 다시 통과했다. 기존 Spark 6개 시험 및 실제 상품 시드 검증 이후 계산 코드는 바뀌지 않았다. 원격 908c252에는 이번 Parquet 보완이 아직 없으며 추가 push·새 배포 이미지 발행은 별도다.

## 작업 결과

### 고정 입력·기대 결과 S3 업로드 (2026-10-23) · 로컬 검증 기록

- pipelines/input-manifests/와 pipelines/requests/에 검증 자료를 신규 업로드했다. 정상 원문 복사본 3개, 두 사례 manifest/expected/validation, 실행 요청 2개로 총 11객체/14,408바이트다. 상품 Parquet·참조 대기 Bronze는 원본을 참조하고 복사·덮어쓰지 않았다.
- IfNoneMatch=*로 기존 객체 덮어쓰기를 방지하고, 각 객체를 GET해 SHA-256·크기를 대조했다. 모든 입력 참조는 HEAD로 존재 확인했고 원본 6객체의 ETag·크기를 준비 시 값과 재확인했다. S3 manifest에서 로컬 사용자 경로는 제거했다.
- 정상 요청: s3://clothes-query-datalake/pipelines/requests/trade-fixed-normal-20261023.json. 정상 manifest/expected/validation은 pipelines/input-manifests/trade-fixed-normal-20261023/에 있다. 참조 대기 요청은 pipelines/requests/trade-fixed-reference-wait-20261023.json, 해당 자료는 pipelines/input-manifests/trade-fixed-reference-wait-20261023/에 있다.
- 준비·검증용 업로드일 뿐 실제 Spark 실행·Airflow Trigger·운영 current 변경은 하지 않았다. 출력_root 초안은 기존 거래 런타임 경로를 사용하므로 실행 권한·이전 결과·동시성 확인은 여전히 필요하다. 외부 manifest의 준비 ETag 자동 소비·VersionId 고정·Kafka 완전성은 아직 별도다.
- 업로드 기록 및 실제 전달 초안은 Git 제외 .local/trade-fixed-20261023/upload_receipt.json 및 message-to-infra.md에 있다. 커미터 true 명시와 관련 명세를 이번 변경에 포함한다.

### 커미터 true·정리 권한 검증 (2026-10-23) · 로컬 검증 기록

- configure_storage에 fs.s3a.committer.abort.pending.uploads=true를 명시했다. 고유 run_id·동일 데이터셋 단일 작성자 전제를 코드/README에 남겼다.
- 외부 통신 없는 Docker 내부망과 Moto 5.1.15 감사 WSGI를 사용했다. 실제 Java S3A 요청의 메서드·키·prefix·상태 코드만 기록했고, 정상 저장·UploadPart 403·첫 파일 완료 후 다음 CompleteMultipartUpload 403을 검증했다. 권한/장애 주입은 로컬 서버에만 적용했다.
- 정상 업무 잡은 Silver/Gold PASS·승인 금액 30,000원이었다. 별도 저장 세 사례의 미완료 업로드는 0개, 다른 실행의 파일·미완료 업로드는 보존됐다. 실제 업무 잡의 Gold 업로드 실패에서는 이전 Gold current 보존·완료 Silver 유지도 확인했다.
- 중요 보완: 부분 커밋 실패 시 magic 밖의 현재 실행 최종 part-*.parquet를 롤백 삭제한다. 따라서 magic 하위 전용 DeleteObject 안을 수정했다. ListMultipartUploads는 실행 데이터셋 prefix로 실제 호출됐고 AbortMultipartUpload도 관측됐다. Java ListParts는 이번 세 경로에 없으므로 ListMultipartUploadParts를 무조건 필수로 요청하지 않는다.
- 실제 호출 기록은 .local/s3-committer-20261023/results/{baseline,success,upload-failure,commit-failure,failed-business}-events.json 및 report.json에 있다. 시험용 스레드 수 1로 커밋을 직렬화해 부분 커밋을 재현했으며 운영 CPU/자원 값으로 확정한 것은 아니다. 임시 컨테이너·내부망은 정리했다.
- 로컬 검증 소스는 427afdf에 true 명시를 더한 미커밋 상태다. 실제 AWS IAM·Pod Identity·EKS 검증과 구분한다. 기존 이미지에는 명시 설정이 아직 없으며 최종 커밋으로 재빌드해야 한다.
- 개념 설명을 SK database의 'Spark 커미터·S3 멀티파트·삭제 권한 — 지금 왜 필요한가'에 저장했다. 정상/실패 실측과 필요한 권한·담당 구분을 추가하며, 재영님 전달 초안에도 반영한다. Ruff Python 3.10·git diff --check 통과. 실제 AWS 변경·추가 커밋/push는 하지 않았다.

### 최신 업무 이미지 재빌드 (2026-10-23) · 로컬 검증 기록

- 427afdf 전체 커밋을 CODE_REF로 지정해 clothes-query-pipelines:runtime-427afdf를 로컬 빌드했다. 기본 apache/spark digest는 fc64959c04bd87b0ac686be9aaa9008b69cdb1afc695400528279c8b01f43d89로 고정했다. 팀 기본 ECR 이미지는 현재 목록에 없어 해당 이미지 기반 최종 빌드와 ECR 발행은 아직이다.
- Python 3.10.12/Spark 4.2.0/PyArrow 25.0.1/boto3 1.43.71/PyYAML 6.0.3, UID 185, 소스 SHA-256 일치 및 .local·원본 자료·캐시 미포함을 확인했다.
- 새 이미지에 별도 업무 소스 마운트 없이 실제 원본 기반 정상 입력을 처리했다. Silver/Gold PASS, 금액 검사 PASS 1건, 시간별/상품별 집계 각각 1행, refresh_holds 0행이며 주문 1건/7,900원/판매 수량 1개의 독립 기대값과 일치했다. 상세는 .local/trade-fixed-20261023/image-427-result/에 있다.
- 로컬 이미지 ID는 sha256:f1d7810a82b50f7ed77395bf5b6b7a50c0bfa892702cb30250b50d6f554dacb9이며 ECR 배포 digest가 아니다. 최신 검증의 manifest code_ref도 실제 427afdf로 확인한다. 앞선 908c252 마운트 시험은 이력으로 보존한다.
- 재영님 전달 초안을 .local/trade-fixed-20261023/message-to-infra.md에 준비했다. namespace 공유·세 ServiceAccount·요청 prefix·원격 코드·이미지·실제 입력 기대값·상품 버킷 권한 및 미완료 커미터/Glue 항목을 구분했다. 외부 메시지·ECR push·S3 업로드·EKS 실행·추가 커밋은 하지 않았다.

### 실제 거래 고정 입력·독립 기대값 준비 (2026-10-23) · 로컬 검증 기록

- 실제 S3 읽기·로컬 입력 고정·독립 기대 결과·Spark 검증을 수행했다. 정상/상품 없는 주문이 같은 파일에 섞여 있어 정상 주문 원문만 복사한 검증 묶음을 구성했다. S3 원본·업무 값은 수정하지 않았다.
- 정상 사례: 주문 이력 3줄·주문상품 1줄·결제 1줄·상품 Parquet 2개, 5파일/2,560,522바이트. 독립 계산 기대는 주문/성공 주문 각 1건·승인 금액 7,900원, KST 2026-10-20 17시, 상품 판매 수량 1개·금액 7,900원이다. Spark에서 Silver/Gold PASS·격리 0건·refresh_holds 0건 및 전체 집계 일치를 확인했다.
- 전체 UTC 10/20 원본은 6파일/2,560,889바이트, 주문 변경 4줄(주문 2건)·상품 1줄·결제 1줄이다. 독립 기대 PASS 1건/PENDING_REFERENCE 1건과 Spark 검사가 일치했다. Silver INCOMPLETE, Gold PARTIAL, 판매 범위 2개 전체 보류·이전 결과 없음도 확인했다. 정상 매출 0으로 해석하지 않는다.
- 실제 디자인 44,623행/상품 101,452행을 사용했고 원본 6객체 ETag·크기를 HEAD로 재확인했다. 기대값은 원본 CDC 순서·Python 정수·독립 SQLite로 계산했으며 공통 허용 기준만 FormatRules 0.2.0을 사용했다.
- 자료는 Git 제외 pipelines/gold_a/.local/trade-fixed-20261023/HANDOFF.md, 원본/파생 manifest, 요청 초안, expected/validation JSON에 있다. 준비 당시에는 미업로드였으며 이후 업로드 완료 내용은 위 S3 업로드 절을 따른다. 데이터·주문 ID가 있는 로컬 자료는 공개 저장소에 올리지 않는다.
- runtime-908c252 이미지에 427afdf spark_batch.py를 읽기 전용 마운트해 검증했다. 기반 이미지 환경의 code_ref와 검증 소스를 HANDOFF에 구분했다. 운영 이미지는 최종 코드로 빌드해야 한다. 실제 EKS/S3A/Pod Identity 검증이 아니다.
- 별도 상품 버킷 읽기, 고정 입력/요청 업로드와 실제 출력 승인, 커미터 상세·Glue 공개는 후속이다. input_complete 선언·시작 시 ETag 고정은 외부 준비 manifest/VersionId/Kafka 범위 완전성 증명이 아니다.

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

### 클릭 Silver·퍼널 Spark · 사용자 검수 대기

- 승인 범위: 기존 clicks.py/funnels.py/spark_batch.py와 기존 Spark 시험·README/이 작업 기록만 수정. 새 코드·DAG·설계 문서는 추가하지 않았다. 작업 폴더가 main으로 변경돼 있어 기존 pipelines/runtime으로 돌아와 작업했으며 main은 수정하지 않았다.
- clicks.py: Executor에서 파일/줄 참조를 유지해 공통 규칙 검사·event_id별 중복/내용 충돌·오류 키 보류를 기존 build_clicks로 처리한다. 키당 최대 행 한도와 분산 DQ 집계를 사용한다.
- funnels.py: Spark SQL로 세션×상품 첫 조회·담기·주문·성공 결제와 일별 전환율을 계산한다. 기존 Python 기준과 수치·KST 시각 표현·NULL 비율을 비교했다. first-view KST 코호트, 조회 전 단계 제외, 장바구니 생략 구매, 결제 재시도, 자정 경계 기준을 유지한다.
- spark_batch.py: job=funnels에 clicks 입력을 추가한다. 거래 Silver/R6 → 클릭 Silver → 상품 기준정보 → 저장 Parquet 재조회 → 퍼널 Gold 순서다. 거래 Silver 완료 목록은 trade 채널에 남기고 클릭은 clicks 채널, 퍼널은 funnels 채널로 공개한다. 판매 Gold 공개 참조는 갱신하지 않는다.
- 품질 오류는 이전 퍼널 Gold를 유지한다. 거래 오류는 클릭 실행 전에 중단하고, 클릭 오류는 클릭 격리/DQ 완료 기록을 남긴다. 상품·주문 참조 누락, 성공 결제 중복/시각 역전은 Gold 계산 실패다. 이 단계의 전체 보류는 아래 Spark 부분 공개 보완에서 대체했다. 정기 실행은 연결하지 않았다.
- 검증: Spark 4.2.0 / Python 3.10.12 local[2] 실제 엔진 6개 시험 통과(127.533초). 기존 거래 3개와 새 클릭/퍼널 3개로, 기준 Python 비교·동일 시각 UTC/KST·중복/충돌·상품/결제 오류·빈 클릭·재실행 Parquet 동일·클릭 오류 시 이전 Gold 유지·Silver/R6 완료 기록 보존을 확인했다. 기존 회귀 107개 통과(22.17초), Spark 모듈 2개는 host에서 건너뛰고 실제 엔진 별도 실행. Ruff Python 3.10·diff 검사 통과.
- 실제 AWS 데이터·IAM·EKS 실행·Athena 조회는 검증하지 않았다. local 이미지의 커밋 코드는 기존 3f4d8dc이고 새 소스는 읽기 전용 마운트로 검증했다. 검수 전 신규 이미지 발행/코드 커밋은 하지 않는다.
- 검수할 기준: 첫 조회일 귀속, 장바구니 없는 구매 포함, 조회 없는 세션×상품은 분모에서 제외, 입력 전체 스냅샷 방식, 오류 시 전체 실행 Gold 보류, trade/clicks/funnels 완료 채널 분리. input_complete는 준비 선언이며 실제 원천 누락이 없다는 증거는 아니다.
- 인프라 추가 권한: bronze/clickstream/ 읽기, silver/runtime/clicks/·gold_a/runtime/funnels/ 읽기·쓰기 및 해당 magic 작업 키 정리/멀티파트 처리. 기존 거래 권한에 포함된 것으로 가정하지 않는다.
- 당시 수정 파일 7개와 아래 부분 공개 보완까지 전체 사용자 검수 후에만 커밋한다. 회원 Spark 전환은 이번 범위에 포함하지 않는다.

### 사용자 요청: 거래·퍼널 Spark 부분 공개 보완 · 로컬 검증 기록

- 기존 plan_trade_holds에 이전 후보/이전 퍼널 상세를 직접 받는 선택 인자를 추가해 기존 Python/JSONL 실행은 유지하고 Spark/Parquet에서도 같은 영향 규칙을 재사용한다.
- gold_a/__init__.py에 이전 Spark 공개 manifest 조회, 관련 오류·후보만 제한해 분석, Spark join 병합을 추가했다. 새 코드 파일은 만들지 않았다. 현재·이전 충돌 후보와 held_context를 함께 사용해 과거 시간대·주문 변경도 보류한다.
- 클릭 Silver에 click_impact_candidates를 추가해 event_id별 양쪽 세션·상품·시각을 남긴다. 클릭 충돌은 해당 상세 키·첫 조회 날짜/이전 반영 날짜를 보류한다. 복원 불가 후보·메타데이터 한도 초과는 전체 보류한다.
- 정상 범위는 현재 값, 보류 범위는 이전 값으로 병합한다. Gold 상태 PARTIAL과 refresh_holds Parquet/held_scopes를 결과와 함께 공개한다. 이전 값이 없으면 0점/0매출로 채우지 않고 previous_result_available=false와 보류 상태를 남긴다. 오류가 사라진 완전한 입력 재실행은 PASS로 복구한다.
- 오류/후보/이전 상세는 각 1,000행까지 Driver 메타데이터로 받고 후보 조합 수·보류 수에도 한도를 둔다. 초과 시 좁은 범위를 임의 선택하지 않는다. 원본 오류 전체는 Silver에 남긴다. 이전 결과 키 존재 여부는 범위별 개별 Spark 작업 대신 집계 키 join으로 확인한다.
- 품질 상태를 PASS로 덮어쓰지 않는다. 검증된 보류 범위의 주문/세션상품만 계산 입력에서 제외하고 기존 DQ는 그대로 보존한다. 상품 기준정보 자체 오류·집계 연결/시각 오류·저장 실패는 실행 실패로 이전 공개 참조를 유지한다.
- 검증 중: 실제 Spark 부분 공개 시험 4개 통과(173.733초), 기존 회귀 107개 통과(최종 13.55초). 전자는 전체 보류·클릭 충돌 부분 갱신·결제 양쪽 시각 보류·정상 상품 갱신·반복 오류의 마지막 정상 참조·복구·첫 실행 이전 결과 없음 처리를 검증했다. 최적화 후 S3A 에뮬레이터에서도 정상 → PARTIAL → PASS 복구를 확인했다. 결제 충돌의 보류 범위 4개·기존 상품 금액 20,000원 유지·정상 상품 5,900원 갱신·잔여 작업 객체 0개를 검증했고 임시 컨테이너/네트워크는 정리했다. 첫 실행 이전 값 없음·마지막 정상 참조 SQL NULL·1,000행 메타데이터 한도 초과·이전 전체 보류 시 오류가 남으면 전체 보류 유지 경계도 실제 Spark에서 추가 통과했다(최종 27.058초). 한 차례 검증 컨테이너에서 변경 의존 모듈 마운트가 빠져 import 실패했으며 모두 마운트해 재검증했다.
- 대시보드는 refresh_holds와 지표를 함께 읽어야 미갱신 상태가 표시된다. 화면 변경·Glue 테이블·실제 IAM/EKS 실행·시간대 전용 재처리 DAG는 이번 코드 보완으로 자동 완료되지 않는다. 리뷰 부분 공개·회원 Spark 전환도 이번 범위가 아니다.
- 기존 클릭·퍼널 미커밋 변경과 이번 보완을 포함한 전체 변경을 사용자에게 검수받은 뒤에만 커밋한다.
- Athena 공개 연결 고려사항을 pipelines/README.md에 추가했다. current.json과 Glue 위치 갱신을 구분하고, PARTIAL의 병합된 새 결과·동일 실행 refresh_holds 공개, 테이블/파티션 간 전환 일관성, 갱신 실패 복구, 프로젝션 예외, R6 완료 이력 소비를 명시했다. 카탈로그 변경 코드는 아직 구현하지 않았으며 AWS 변경도 하지 않았다.

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

### main 통합·인프라 리뷰 준비 (2026-10-23)

- origin/main fbc6108을 충돌 없이 통합했다. main에 이미 반영된 Gold A·형식 규칙·Gold B 코드를 유지하며 운영 실행 연결 변경만 비교한다.
- Python 회귀 135개 통과. Linux Spark 4.2 이미지에서 최신 통합 소스를 읽기 전용 마운트해 거래·퍼널 10개(213.696초), 리뷰 3개(74.579초)를 별도 실행하고 모두 통과했다. 처음 기본 Windows 임시 폴더에서 실행한 검사는 임시 폴더 권한 오류로 중단됐으며, 작업 폴더 내 basetemp를 지정한 재실행은 통과했다.
- 변경한 pipelines Python 파일의 Ruff(py310) 및 git diff --check 통과. 전체 pipelines Ruff는 main에서 추가된 Gold B·기존 시험 파일의 경고 12개가 있어 이번 작업 범위와 구분했다.
- 브랜치 대장 변경은 후속 취합으로 분리하고 이번 PR에서는 main과 동일하게 유지한다.
- 인프라 리뷰 범위는 이미지·Spark 제출·실행 계정·S3 권한·커미터·Airflow 연결이다. 실제 배포 이미지 확정·EKS 업무 실행·Glue 공개·R6 완료 시각 및 재처리 DAG는 미완료다.

- PR #82: pipelines/runtime → main, 일반 PR로 생성하고 jaeyan42에게 인프라 리뷰를 요청했다. 생성 시 충돌 없음. 머지·ECR 발행·EKS 실행은 하지 않았다.
