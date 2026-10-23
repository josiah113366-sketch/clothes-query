# Silver·Gold A 첫 거래 검증 연결

main #82를 반영했고 적용 전 최신 main 083931f까지 확인했다. 팀 입력 두 개는 S3에 존재함을 읽기 확인했다. 2026-10-23 사용자 승인으로 ECR·기본 이미지 발행·S3 endpoint·Spark 실행 계정/권한·RBAC/template까지 적용했다. **업무 이미지 digest와 Airflow 업무 설정 연결은 대기이며 Spark 노드·업무 잡은 실행하지 않았다.**

- 적용 namespace: pipelines, SA: silver-gold-a-submitter / silver-gold-a-driver / silver-gold-a-executor
- 적용 runtime ConfigMap: pipelines/silver-gold-a-runtime
- 미적용 업무 설정: airflow/airflow-silver-gold-a-runtime, key config → AIRFLOW_PIPELINE_RUNTIME
- 기존 main GitDagBundle가 infra/platform/airflow/dags를 읽으므로 새 bundle은 추가하지 않는다. silver_gold_a_batch는 수동/paused로 유지한다.
- 업무 ECR: clothes-query-dev/silver-gold-a, 기본 ECR: clothes-query-dev/spark-base. 두 저장소와 de-ai-18 push 정책은 적용했다. 기본 이미지는 발행·검증 완료했고 업무 이미지 digest는 동료 전달 대기다. [발행 안내](spark-ecr-publish.md)를 따른다. push 담당 de-ai-18과 Pod 실행 역할은 다르다.

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
5. Spark NodePool 활성화는 별도 비용 승인 범위다. 지금 비활성 상태를 바꾸지 않는다.
6. 실행 전 요청/원본 ETag·예상 결과·run 폴더가 비어 있는지·기존 current와 동시 작성자가 없는지 확인한다. 그 뒤에만 두 고정 입력을 순차 수동 실행한다.
7. 종료 후 남은 Driver/Executor/제출기 Pod와 S3 magic/MPU 상태를 확인한다. 업무 데이터를 임의 일괄 삭제하지 않는다. 시간 초과 시 Driver가 남을 수 있어 재실행 전에 상태를 확인한다.

현재 1번의 기본 이미지까지, 2·3번의 실행 기반 적용까지 완료했다. 남은 것은 업무 이미지 digest → 4번 Airflow 업무 설정 → 별도 노드 활성화/수동 검증이다. 적용 후 pipelines Pod/Job 0개·Spark NodePool 0개이며 기존 노드 3개의 UID는 변하지 않았다. 실제 Pod Identity 자격증명 발급과 S3 입출력은 첫 업무 검증에서 확인한다.

고정 요청: pipelines/requests/trade-fixed-normal-20261023.json 및 trade-fixed-reference-wait-20261023.json. run_id는 파일명과 동일하다. 출력 루트는 s3://clothes-query-datalake/다. 정상 7,900원 및 참조 대기 기대 결과는 PR 본문과 input-manifests 자료로 실행 직전 다시 대조한다.
