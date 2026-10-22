# Agent 개발 접근

기존 EKS에 별도 IAM 역할·access entry를 추가하고 판정/조사 ECR 저장소를 만든다. 클러스터·기존 관리자 권한·Pod Identity는 변경하지 않는다. Kubernetes 권한은 별도 namespace RoleBinding으로 연결하며 EKS 관리 정책을 연결하지 않는다.

역할은 지정 클러스터 Describe와 두 저장소의 push/pull만 허용한다. ECR 인증 토큰 API는 리소스 범위를 지원하지 않아 `Resource = "*"`를 사용한다. S3·Athena·Bedrock 권한은 이 개발자 역할에 주지 않고 실행 Pod의 기존 역할로 분리한다.

저장소는 immutable tag·scan-on-push·AES256, force_delete=false다. 실제 ARN은 비공개 입력으로 공급한다. 삭제 전 이미지 보관과 access entry 사용 여부를 확인한다.
