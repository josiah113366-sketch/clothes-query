# Spark 실행용 AWS 접근

eks/storage/network state 이후 독립 key로 준비한다. 기본 enabled=false·namespace=null이며 실행 역할·Pod Identity를 생성하지 않는다. ECR 개발자 push 권한은 ecr 스택, Kubernetes 계정/RBAC는 platform/spark runtime으로 분리한다.

첫 거래 검증용 입력은 trade-test.tfvars.example에 준비했다. pipelines의 Silver·Gold A 계정만 연결하며 Gold B 권한은 추가하지 않는다. network S3 endpoint의 DeleteObject·ListMultipartUploadParts·ListBucketMultipartUploads 선행 적용을 확인해야 한다. 기존 workload-access binding은 변경하지 않는다. 노드풀 활성화·업무 Job·Glue 표 생성은 이 스택에 포함하지 않는다.

검토 명령은 terraform plan -var-file=trade-test.tfvars.example이다. 현재 endpoint 상태에서는 활성 역할의 사전조건이 실패하는 것이 맞다. 검사를 끄거나 가짜 remote output으로 우회하지 않는다. [최신 준비 결과](../../platform/spark/handoff/silver-gold-a-ready.md)를 따른다.
