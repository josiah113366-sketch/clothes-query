> **현재 구성(2026-10-14):** 이전 HA 결정을 변경했다. 워커·앱·RDS는 ap-northeast-1a 한 AZ, NAT 1개, RDS Single-AZ다. AWS 서비스 요구사항 때문에 두 AZ의 서브넷은 유지한다. WEB 2개/WAS HPA 2~3개는 유지한다. 아래의 이전 HA 설명보다 infra/SINGLE_AZ.md의 최신 결정을 우선한다.

# apps stack

Namespace·Pod Identity·ConfigMap 및 선택적 WEB/WAS·HTTPS ALB Ingress.

- 선행: 기존 bootstrap 및 eks, compute, rds, storage.
- backend key: `clothes-query/dev/apps/terraform.tfstate`.
- 입력: `s3_prefix` 필수. `deploy_workloads=false`가 기본. 활성화하려면 web/was `images` digest, `hostname`, `certificate_arn`, `alb_inbound_cidrs`가 필요하다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다. 종속 state 읽기에는 `state_bucket`, 필요시 `state_region`도 입력한다.
- 출력: `namespace`, `database_secret_name`, `workloads_enabled`.

## 실행

`workload_settings`에서 WEB replicas와 WEB/WAS CPU·메모리 request/limit을 조정한다. 각각 최소 2 replica를 유지하고 compute 풀에 배치한다. WAS는 HPA로 조절하며 [증설·축소 가이드](../../SCALING.md)를 따른다.

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

반드시 EKS 이후 별도 state에서 실행한다. Kubernetes API/Auto Mode CRD에 접근해야 plan이 가능하다. 배포 시 WEB/WAS 2 replica와 AZ 분산·노드 anti-affinity·PDB를 사용한다. Ingress가 AWS ALB를 생성하므로 실제 변경이다.

앱 이미지 계약·DB Secret 공급·DNS 설정 및 두 단계 배포 순서는 전체 안내를 따른다. 초기 `deploy_workloads=false` 성공은 서비스 연결 검증 완료가 아니다.
