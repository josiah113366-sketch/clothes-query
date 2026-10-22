# EKS 감사 로그 수집 재개

상태: 실제 복구 완료·최신 main 통합 및 무변경 plan 확인

## 요청과 범위

2026-10-21 사용자 요청으로 audit 로그 중단을 취소하고 다시 수집한다. #39는 이미 main에 머지됐으므로 최신 main의 후속 브랜치에서 enabled_cluster_log_types에 audit만 복구한다. #39에 포함된 관리자 신뢰와 기존 공개 API 범위·다른 로그·30일 보관·노드·업무 데이터는 유지한다. 감사 로그의 수집·보관 비용은 다시 발생하며 중단 기간 로그를 소급 복원하지 않는다.

## 완료 확인

- fmt/validate, 기존 EKS mock 검사를 실행한다.
- 실제 계획에서 EKS 로그 설정 1개 수정, audit 추가만 있는지 확인한다.
- 적용 후 EKS ACTIVE·5종 로그 활성과 후속 무변경 계획을 확인한다.
- 원격 PR 승인·머지는 팀원이 진행한다.

## 작업 결과

fmt/validate와 기존 EKS mock 8건을 통과했다. 실제 저장 계획은 생성0/수정1/삭제0이고 변경 필드가 enabled_cluster_log_types 하나이며 audit만 추가됨을 확인한 뒤 적용했다. 적용 후 EKS ACTIVE·로그 5종 활성·Kafka Pod 6개 모두 Ready를 확인했고 후속 Terraform plan은 변경 없음이다.

기존 로그 4종·30일 보관·관리자 신뢰·public/private endpoint·노드·업무 데이터는 유지했다. audit 로그 수집·보관 비용은 다시 발생한다. 이번에 실제 이벤트 본문이나 비용 데이터는 추가 조회하지 않았으며 중단 기간 감사 로그는 복구되지 않는다. 비공개 검증 요약은 gitignored .cache/eks-audit-restore-summary.json에 보관한다. 사용자 요청에 따라 복구 브랜치와 PR을 게시하고 승인·머지는 팀원에게 맡긴다.

## 2026-10-22 main과 AWS 설정 일치

사용자가 공통 tfvars를 다른 담당자도 사용할 수 있도록 audit 차이를 먼저 정리해 달라고 요청했다. 최신 main의 공유 입력·접근 권한·Airflow 및 데이터 역할 변경을 반영하고, 기존 audit 복구 코드만 유지한다. 이 단계는 이미 활성화된 AWS 설정을 코드에 맞추는 작업이며 추가 apply나 로그 수집 재시작은 하지 않는다. 기존 PR #51을 다시 열어 CI를 확인한 뒤 머지하며 자체 승인 리뷰는 제출하지 않는다.

완료 확인: 실제 EKS ACTIVE·관리 로그 5종 활성, 현재 공유 입력과 개인 IP override를 사용한 EKS 전체 plan 변경 없음, fmt/validate와 기존 EKS mock 및 GitHub CI 통과를 확인한다. 이번 정리로 실제 수집량·요금·30일 보관 기간이 달라지지는 않는다.

결과: 실제 ACTIVE와 api/audit/authenticator/controllerManager/scheduler 5종 활성을 재확인했다. 최신 공유 tfvars와 로컬 개인 입력을 사용한 전체 EKS plan은 생성·수정·삭제 모두 0이며 fmt/validate도 통과했다. 기존 main의 audit 제거 계획이 사라졌다. 결과는 Git 제외 .cache/audit-main-alignment.json에 저장했고 apply·state 조작·업무 Pod 재시작은 하지 않았다. 원격 CI 결과는 PR #51에서 확인한다.
