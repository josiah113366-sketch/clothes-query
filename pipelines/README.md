# 데이터 파이프라인

## 운영 실행 연결 · 수동 배치

`pipelines.batch`는 S3 입력을 임시 폴더에 내려받아 기존 Silver·Gold A를 실행하고 결과의 로컬 파일 참조를 S3로 바꿔 저장한다. 계산 기준·형식 규약은 그대로다. 선행 Gold A #67의 main 반영이 필요하다. 아직 운영에 배포한 것은 아니다.

### 실행 이미지와 DAG

저장소 루트에서 빌드한다. `CODE_REF`에는 배포할 실제 Git 커밋을 넣는다. Dockerfile 전용 ignore는 .local 원문·캐시·자격증명·테스트를 빌드 컨텍스트에서 제외한다.

```powershell
docker build -f pipelines/Dockerfile --build-arg CODE_REF=<Git-커밋> -t <ECR-이미지>:<태그> .
```

빌드 후 이미지 push·digest 확인을 하고, Airflow DAG processor와 scheduler에 아래 JSON 환경 변수 `AIRFLOW_PIPELINE_RUNTIME`을 공급한다. 실제 namespace·ServiceAccount·노드 배치는 인프라 담당자와 확정한다. AWS 정적 키는 넣지 않고 Pod Identity를 사용한다.

```json
{
  "image": "<ECR-이미지>@sha256:<64자리-digest>",
  "namespace": "pipelines",
  "service_account": "silver-gold-a",
  "node_selector": {"kubernetes.io/hostname": "<승인된-공용-노드>"}
}
```

업무 DAG 파일은 `infra/platform/airflow/dags/silver_gold_a.py`다. 기존 infra 확인용 DAG를 교체하지 말고 같은 배포 방식으로 별도 마운트한다. 현재 ConfigMap/subPath 방식에서는 Helm 마운트 설정 추가와 관련 Pod 재시작도 필요하다. 파일을 Git에 넣는 것만으로 배포되지 않는다. 자세한 배포 구조는 [Airflow 안내](../infra/platform/airflow/README.md)를 따른다.

Airflow `silver_gold_a_batch`는 schedule 없음·초기 paused·동시 실행 1개·자동 재시도 0회다. 실행 한 번에 trade/reviews/funnels/members 중 하나를 선택한다. 서로 다른 작업의 품질 실패가 다른 실행을 막지는 않는다. 필요 시 DAG를 unpause한 뒤 수동 Trigger한다. 기존 agent 신원 사용이나 namespace/IAM 생성은 이 DAG가 하지 않는다.

### 수동 실행 입력

Airflow Trigger의 Configuration 예시다. URI는 실제 파일/접두사로 교체한다. 접두사는 반드시 `/`로 끝내며 JSON/JSONL 전체 하위 객체를 읽는다. 거래·퍼널은 하루치 주문만 잘라 최신 상태를 추측하지 않는다. 필요한 변경 이력과 참조를 준비한 뒤에만 `input_complete: true`를 선언한다. 이는 Kafka 완료 범위 검증이 아니다.

```json
{
  "batch": {
    "job": "trade",
    "output_root": "s3://<데이터-버킷>/",
    "input_complete": true,
    "inputs": {
      "orders": ["s3://<데이터-버킷>/bronze/orders/"],
      "order_items": ["s3://<데이터-버킷>/bronze/order-items/"],
      "payments": ["s3://<데이터-버킷>/bronze/payments/"],
      "designs": ["s3://<데이터-버킷>/<상품스냅샷>/designs.jsonl"],
      "variants": ["s3://<데이터-버킷>/<상품스냅샷>/variants.jsonl"]
    }
  }
}
```

| job | 필수 입력 | 날짜·선택 입력 |
|---|---|---|
| trade | orders/order_items/payments/designs/variants | input_complete=true, 날짜 부분 필터 없음 |
| funnels | 위 5개 + clicks | input_complete=true. 전체 세션 이력을 준비 |
| reviews | reviews/designs/variants | start_date/end_date: KST 작성일. mapping: 선택 고정 JSONL 파일, analysis: 선택 고정 JSONL/CSV 파일 + model_version |
| members | members | through_date: UTC 수집일까지 전체 이력 |

reviews 입력은 `s3://<버킷>/bronze/reviews/`, members 입력은 `s3://<버킷>/bronze/members-events/`처럼 year/month/day를 포함하는 접두사 하나다. 리뷰는 KST 시작일 전날 UTC부터 종료일 UTC까지 읽는다. 분석 파일이 없으면 별점 집계만 생성하며 점수 집계를 완료했다고 표시하지 않는다. 이 실행기는 SageMaker 모델을 호출하지 않는다.

분석을 포함한 리뷰 요청은 다음과 같다. `model_version`은 실제 생성한 모델 버전과 맞춘다.

```json
{
  "batch": {
    "job": "reviews", "output_root": "s3://<데이터-버킷>/",
    "start_date": "2026-10-21", "end_date": "2026-10-21", "model_version": "<모델-버전>",
    "inputs": {
      "reviews": ["s3://<데이터-버킷>/bronze/reviews/"],
      "designs": ["s3://<데이터-버킷>/<상품스냅샷>/designs.jsonl"],
      "variants": ["s3://<데이터-버킷>/<상품스냅샷>/variants.jsonl"],
      "analysis": ["s3://<데이터-버킷>/silver/review-score/output/<완료된-모델-작업>/scores.csv"]
    }
  }
}
```

상품 입력은 기존 products.py가 정의한 JSONL 스냅샷 2개다. 아직 실제 S3 상품 스냅샷 위치는 확인하지 않았다. DB를 자동 조회하거나 원천 CSV를 자동 변환하지 않는다. 모델 완료·실패 목록의 완전성도 자동 증명하지 않는다.

### S3 결과와 읽는 순서

예시 output_root가 버킷 루트일 때 다음에 쓴다. 하위 루트를 지정하면 그 아래에 생성한다.

```text
silver/runtime/<job>/
  runs/<runtime_run_id>/...     고정 Silver 결과·manifest·R6 검사
  completed/<runtime_run_id>.json   완료된 Silver 실행 목록
  current.json                 최신 Silver 실행 참조
gold_a/runtime/<job>/
  runs/<runtime_run_id>/...     고정 Gold A 결과·manifest
  completed/<runtime_run_id>.json   완료된 Gold A 실행 목록
  current.json                 최신 Gold A 실행 참조
```

1. 조회할 계층·작업의 current.json 또는 미처리 completed 기록을 읽는다.
2. silver_manifests/gold_manifests의 uri → 해당 고정 manifest의 outputs를 따라간다. `runs/` 전체를 합치지 않는다.
3. R6는 `silver/runtime/trade/completed/`의 미처리 실행을 순서대로 읽고 거래 manifest의 outputs.order_amount_checks로 이동한다. 내부 run_id/check_name/order_id를 중복 소비 키로 사용한다. runtime_run_id는 외부 실행과 연결하는 별도 식별자다. 목록 조회 권한·소비 체크포인트는 판정 담당자와 연결해야 한다.
4. Silver 품질 INCOMPLETE도 완료 목록에 남긴다. 이 경우 작업은 실패 처리하고 Gold A를 갱신하지 않는다. 회원은 Gold A 결과를 만들지 않는다.

다운로드 전 목록·ETag를 고정하고 IfMatch로 변경된 입력을 거부한다. 원본 URI·ETag·버전 ID(있는 경우)·SHA-256와 코드 커밋을 실행 기록에 남긴다. S3 목록은 원천 입수 완전성의 증명이 아니므로 coverage_status는 UNVERIFIED다. 기본 다운로드 한도는 128MiB, max_download_bytes로 최대 1GiB까지 명시 가능하다. 현재 계산은 메모리 배치이므로 실제 크기로 자원·시간을 측정해야 한다.

결과 객체 저장 후 계층별 완료 목록과 current를 공개한다. Gold A 실패 시 Silver 검사는 읽을 수 있고 이전 Gold A current를 유지한다. 파일 안의 원본 참조·R6 source_manifest도 S3 경로로 변환한다. 겹친 실행이 최신 참조를 조용히 덮지 않도록 current 쓰기는 ETag 조건을 사용하지만 분산 트랜잭션·실행 잠금은 아니다. 단일 DAG 외부에서 같은 작업을 병렬 실행하지 않는다. 실패한 미공개 객체 정리와 보관 기간은 운영 정책으로 별도 결정한다. 삭제 권한은 사용하지 않는다.

이번 버전은 매번 제공된 전체 입력으로 새 스냅샷을 만든다. 기존 Gold A의 부분 병합·scope-aware 복구, 시간대 재처리 승인 DAG, 정기 스케줄, 실제 A/B 대조 잡은 자동 연결하지 않는다. Parquet 라이브러리는 이미지에 포함하지만 기존 실행기의 JSONL 입력·출력 형식을 Parquet으로 바꾸지는 않는다.

이 브랜치는 `pipelines/silver/`의 정제 코드와 `pipelines/gold_a/`의 비즈니스 지표 코드를 담는다. Gold A는 선행 Silver 결과를 입력으로 쓴다.

## 공통 결제 지문

`pipelines/payment_fingerprint.py`의 payment_fingerprint(payment)가 결제 업무 필드 9개를 정규화해 payment_content_hash/fingerprint_version을 반환한다. 호출/입력/버전 계약은 [공통 계약](../docs/contracts/README.md#결제-내용-지문-규약--payment-contentv1)을 따른다. 순수 표준 라이브러리 함수이며 추가 패키지는 없다. Silver는 공통 입력 검사 후 원본 시각 문자열로 호출해 정상 결제 결과에 해시·버전을 저장한다. Gold B의 호출·적재 연결은 후속 작업이다.

- 입력과 실행 방법은 `pipelines/silver/README.md`를 따른다.
- 거래 Silver는 펼쳐진 CDC와 공통 YAML 업무 규칙을 지원한다. 실제 AWS 데이터 검증은 별도다.
- Gold A의 입력과 실행 방법은 `pipelines/gold_a/README.md`를 따른다.
- Gold B의 관제용 원장 DDL과 후속 구현 범위는 `pipelines/gold_b/README.md`를 따른다.

공통 YAML 검사기는 `pipelines/format_rules.py`, 규칙 원본은 `docs/contracts/format_rules.yaml`이다. 실행 의존성은 `python -m pip install -r pipelines/requirements.txt`로 설치한다. 거래·회원·클릭 Silver가 연결돼 있으며 실행별 규칙 버전·내용 해시와 격리 rule_id를 기록한다. 리뷰·상품은 자체 검사를 유지한다. Gold B 실행 연결은 별도 담당 범위다.
