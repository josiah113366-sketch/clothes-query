# Spark 실행용 AWS 접근

eks/storage/network state 이후 독립 key로 관리한다. 모듈 기본은 enabled=false·namespace=null이다. 2026-10-23 사용자 승인으로 공통 deployment.auto.tfvars.json의 첫 거래 검증 설정을 활성화해 pipelines의 Driver/Executor 역할·Pod Identity를 적용했다. ECR 개발자 push 권한은 ecr 스택, Kubernetes 계정/RBAC는 platform/spark runtime으로 분리한다.

첫 거래 검증용 입력은 trade-test.tfvars.example에 준비했다. pipelines의 Silver·Gold A 계정만 연결하며 Gold B 권한은 추가하지 않는다. network S3 endpoint의 DeleteObject·ListMultipartUploadParts·ListBucketMultipartUploads 선행 적용을 확인해야 한다. 기존 workload-access binding은 변경하지 않는다. 노드풀 활성화·업무 Job·Glue 표 생성은 이 스택에 포함하지 않는다.

기본 terraform plan은 적용된 공통 설정을 사용한다. 검토 예시는 terraform plan -var-file=trade-test.tfvars.example이다. 현재 endpoint 선행 적용을 확인하는 사전조건은 통과했고 적용 후 plan은 변경 없음이다. 검사를 끄거나 가짜 remote output으로 우회하지 않는다. [최신 준비 결과](../../platform/spark/handoff/silver-gold-a-ready.md)를 따른다.
