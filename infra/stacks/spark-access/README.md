# Spark 실행용 AWS 접근

eks/storage/network state 이후 독립 key로 준비한다. 기본 enabled=false·namespace=null이며 실행 역할·Pod Identity를 생성하지 않는다. ECR 개발자 push 권한은 ecr 스택, Kubernetes 계정/RBAC는 platform/spark runtime으로 분리한다.

namespace 공유 확인과 network S3 endpoint의 DeleteObject·ListMultipartUploadParts 허용이 먼저다. enabled=true 전 최종 업무 코드·magic 작업 경로·bucket multipart listing 필요성을 확인한다. 기존 workload-access binding은 변경하지 않는다. 노드풀 활성화·업무 Job·Glue 표 생성은 이 스택에 포함하지 않는다.
