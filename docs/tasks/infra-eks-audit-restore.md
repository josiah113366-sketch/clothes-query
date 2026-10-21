# EKS 감사 로그 수집 재개

상태: 실제 적용 완료·검토 대기

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
