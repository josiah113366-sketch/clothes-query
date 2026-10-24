# Gold B 이미지와 체크포인트 연결

상태: 2026-10-24 이미지 존재 확인·체크포인트 권한 적용 완료. 상시 적재 실행과 실제 체크포인트 재시작 검증은 미실행.

## 확정 항목

- 업무 이미지: `827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/gold-b@sha256:2a8acd10a157171c0663dcb7bce95b0947c446bbca2219392fcef83c55e308e3`
- 기준 커밋: `7d5ebd16c98ddb53eb2df30c2ac651c71f5bcaf4`. 도쿄 ECR에 이미지 존재와 동일 커밋 태그를 확인했다. 이미지 내부 CODE_REF나 실행 호환성을 확인한 결과로 간주하지 않는다.
- 체크포인트: `s3a://clothes-query-datalake/gold_b/_checkpoints/streaming_ingest/`. 사용자가 제안 경로를 확정했다.

## 적용 범위

공유 `workload-access/deployment.auto.tfvars.json`의 `gold-b-ingest-driver`·`gold-b-ingest-executor` 두 binding에 체크포인트 prefix를 추가했다. 해당 객체 범위의 GetObject·PutObject·DeleteObject·AbortMultipartUpload·ListMultipartUploadParts와 prefix 조건의 ListBucket을 허용한다. 기존 원장 접근을 유지하고 다른 체크포인트·정답표·원장 삭제 권한은 넓히지 않는다. 재처리 역할은 이 체크포인트 권한을 받지 않는다.

최신 origin/main 포함을 확인한 뒤 Terraform fmt·validate·plan을 실행했다. 계획은 IAM inline policy 2개 update뿐이며 create/delete/노드/역할/Pod Identity 변경은 없었다. 같은 저장 계획을 적용했고 후속 plan 변경 0을 확인했다.

실제 두 역할에 대한 IAM 시뮬레이션에서 객체 권한 40개와 checkpoint ListBucket 2개를 확인했다. checkpoint 하위 객체 접근은 허용, 다른 checkpoint와 ground_truth 접근은 거부, 기존 원장 Get/Put은 허용하고 Delete·multipart 정리는 거부됐다. S3 객체를 생성·삭제한 시험은 아니다.

준비 도구는 명시한 checkpoint prefix를 권한 입력과 `GOLD_B_CHECKPOINT` 양쪽에 반영하도록 보완했다. 미지정 기본값은 계속 null이며 허용되지 않는 경로는 거부한다. 기존 Gold B 준비 테스트 7개가 통과했다. 확정 image digest와 checkpoint를 넣은 runtime 초안은 Git 제외 로컬 파일로 생성했다. 실행용 ConfigMap 설치나 DAG 활성화는 하지 않았다.

## 후속

상시 적재를 실제 EKS/S3에서 실행하고 Kafka TLS·Pod Identity·원장 생성·체크포인트 쓰기 및 재시작을 검증해야 한다. Silver·Gold A와의 공유 자원 후보는 별도 실측 전이며 기존 배치 자원 설정을 임의로 줄이지 않았다. 이번 권한 적용은 Spark Pod·Job·노드를 시작하지 않으며 S3 시험 객체도 만들거나 지우지 않는다.
