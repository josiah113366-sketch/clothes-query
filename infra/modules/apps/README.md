# apps module

Namespace·Pod Identity·ConfigMap 및 선택적 WEB/WAS·HTTPS ALB Ingress를 관리한다.

## 입력과 출력

- 용량 조정: `workload_settings`의 WEB replicas 및 WEB/WAS CPU·메모리 요청/한도. 최소 2 replica. `node_pool_name`으로 승인된 compute 풀만 사용한다. [운영 가이드](../../SCALING.md) 참고.

- 배포 사양: `s3_prefix` 필수. `deploy_workloads=false`가 기본. 활성화하려면 web/was `images` digest, `hostname`, `certificate_arn`, `alb_inbound_cidrs`가 필요하다.
- 연결 입력: `name`, `cluster_name`, `bucket_name`, `bucket_arn`, `database_address`, `database_name`, `region`. [호출 스택](../../stacks/apps/main.tf)에서 연결한다.
- 출력: `namespace`, `database_secret_name`, `workloads_enabled`.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[apps 스택](../../stacks/apps/README.md)에서 실행한다. 반드시 EKS 이후 별도 state에서 실행한다. Kubernetes API/Auto Mode CRD에 접근해야 plan이 가능하다. 배포 시 WEB/WAS 2 replica와 AZ 분산·노드 anti-affinity·PDB를 사용한다. Ingress가 AWS ALB를 생성하므로 실제 변경이다.
