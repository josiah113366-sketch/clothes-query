# Silver·Gold A 첫 거래 검증 연결

2026-10-23 후속 검증까지 반영한 안내다. ECR·기본 이미지·S3 endpoint·Spark 실행 계정/권한·RBAC/template·전용 NodePool을 적용했다. 업무 이미지도 수신했고 첫 거래 실행의 Driver 1개·Executor 2개가 exit=0, Silver·Gold A manifest/completed는 PASS였다. coverage_status는 UNVERIFIED로 업무 범위·추가 사례 검증은 담당자가 확인한다. Spark 노드는 시험 후 자동 종료돼 현재 0대이며 풀은 활성 상태다.

업무 이미지: `827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/silver-gold-a@sha256:241d5b96ac42ec5aff3be1a65059a925e7af1a009fe6b6d698c4aae99a34ee39`. 최신 연결·대기 항목은 [작업 목록](../../../../docs/infra-work-queue.md)을 따른다. 아래 재실행 절차는 새 run_id와 허용 범위를 검토한 뒤 사용하며 이미 끝난 시험을 그대로 반복하지 않는다.

- 적용 namespace: pipelines, SA: silver-gold-a-submitter / silver-gold-a-driver / silver-gold-a-executor
- 적용 runtime ConfigMap: pipelines/silver-gold-a-runtime
- 업무 설정 연결 위치: airflow/airflow-silver-gold-a-runtime, key config → AIRFLOW_PIPELINE_RUNTIME
- 기존 main GitDagBundle가 infra/platform/airflow/dags를 읽으므로 새 bundle은 추가하지 않는다. silver_gold_a_batch는 수동/paused로 유지한다.
- 업무 ECR: clothes-query-dev/silver-gold-a, 기본 ECR: clothes-query-dev/spark-base. 두 저장소와 de-ai-18 push 정책은 적용했다. 기본·업무 이미지 digest는 수신·검증했다. [발행 안내](spark-ecr-publish.md)를 따른다. push 담당 de-ai-18과 Pod 실행 역할은 다르다.

## 이미지 없이 가능한 렌더

```powershell
python infra/platform/spark/prepare_trade_runtime.py --output .cache/trade-runtime.yaml
```

namespace·SA·제출/Driver/Executor template·RBAC만 렌더한다. Pod/Job/NodePool은 없다. 공유 namespace에 기존 ResourceQuota를 삭제하지 않고, 새 namespace 전체 4-Pod quota도 만들지 않는다. Gold B 상시 Pod까지 제한해 Spark가 뜨지 못하는 일을 피한다. 단일 Spark 노드 한도와 DAG max_active_runs=1은 별도로 유지한다. 같은 namespace의 Pod 생성자는 다른 SA를 선택할 수 있어 SA 분리가 강제된 보안 경계는 아니다.

최종 digest가 도착하면 --image 및 --existing-helm-values/--helm-overlay를 추가한다. actual Helm values를 Git 제외 파일로 받아 기존 env/Secret 참조와 DAG bundle을 보존하며 병합한다. digest가 없으면 Airflow ConfigMap을 생성하지 않아 placeholder로 DAG를 활성화하지 않는다. 생성된 YAML도 검토 전 자동 적용하지 않는다.

## S3/IAM 준비

Spark access 공통 deployment에 첫 거래 검증 설정을 적용했다(enabled=true, namespace=pipelines). trade-test.tfvars.example과 같은 범위다. 다음 기본 plan에서 실환경 역할을 삭제하지 않도록 공통 auto 설정도 맞췄다.

- Bronze orders/order-items/payments 및 pipelines/requests/, pipelines/input-manifests/ 읽기.
- silver/runtime/trade/, gold_a/runtime/trade/ 결과 읽기·쓰기·multipart.
- hm-ecommerce-data의 product_design.parquet 및 product_variant.parquet 두 객체만 읽기. 해당 버킷도 도쿄임을 확인했다. 쓰기·삭제는 없다.
- magic 작업 객체 삭제와, 두 고정 검증 run_id 안의 part-*.parquet 실패 롤백 삭제만 허용한다. manifest/current/completed 삭제나 과거 실행 전체 part 삭제 권한은 주지 않는다. 다음 run_id를 쓰면 검토용 허용 목록도 갱신해야 한다.
- ListBucketMultipartUploads는 버킷 수준 메타데이터 권한이다. object Delete처럼 prefix별 격리라고 설명하지 않는다. 첫 검증에서 명시적으로 활성화한다.
- 네트워크 S3 endpoint에 DeleteObject, ListMultipartUploadParts, ListBucketMultipartUploads 전달 권한을 추가 적용했다. 기존 AbortMultipartUpload 등은 보존했다. IAM prefix 제한은 별도다. endpoint 선행 적용을 확인하는 역할 plan 사전조건도 통과했다.
- funnels/reviews·ground_truth·Gold B 장부·재처리 완료 이벤트 쓰기·Glue 카탈로그 쓰기는 이 첫 거래 검증 권한에 포함하지 않는다. SILVER 재처리 이벤트의 실제 작성 태스크/SA는 별도로 받아 연결한다.

## 실행 전 순서

1. ECR 생성/발행 및 최종 기본·업무 이미지 digest 확인.
2. network endpoint 변경 계획 검토 후 반영. 기존 network 전체 drift를 되돌리지 않는다.
3. spark-access 첫 검증 계획 및 pipelines RBAC/template 검토/반영. 기존 shared namespace 자원은 대조한다.
4. Airflow actual values와 runtime ConfigMap 연결. 기존 agent/infra bundle·Secret을 보존한다.
5. Spark NodePool은 승인 후 활성화됐다. 새 수동 실행은 노드를 생성해 비용이 발생할 수 있으므로 대상·실행 범위를 확인한다. main의 오래된 enabled=false로 apply해 풀을 삭제하지 않는다.
6. 실행 전 요청/원본 ETag·예상 결과·run 폴더가 비어 있는지·기존 current와 동시 작성자가 없는지 확인한다. 그 뒤에만 두 고정 입력을 순차 수동 실행한다.
7. 종료 후 남은 Driver/Executor/제출기 Pod와 S3 magic/MPU 상태를 확인한다. 업무 데이터를 임의 일괄 삭제하지 않는다. 시간 초과 시 Driver가 남을 수 있어 재실행 전에 상태를 확인한다.

첫 실제 실행 trade-v2-eks-20261023-b0185ff가 성공했고 실제 S3 출력도 확인했다. 완료 Pod 로그는 airflow-logs/infra-spark-validation/<run_id>/에 보존하고 해당 완료 Pod만 정리했다. 이후 Spark 노드 자동 종료를 확인했으며 NodePool과 결과 데이터는 유지했다. Gold B 상시 Spark와의 동시 실행 용량, 추가 업무 사례, Glue 공개/R6 명세는 아직 검증·확정 전이다.

고정 요청: pipelines/requests/trade-fixed-normal-20261023.json 및 trade-fixed-reference-wait-20261023.json. run_id는 파일명과 동일하다. 출력 루트는 s3://clothes-query-datalake/다. 정상 7,900원 및 참조 대기 기대 결과는 PR 본문과 input-manifests 자료로 실행 직전 다시 대조한다.
