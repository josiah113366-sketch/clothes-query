# 작업 지시서: infra/eks-audit-cost

상태: 실제 적용 완료·검토 대기

후속 결정: PR #39는 main에 머지됐다. 사용자가 2026-10-21 감사 로그 중단을 취소하고 수집 재개를 요청해 [audit 복구 작업](infra-eks-audit-restore.md)에서 되돌린다. 아래는 당시 중단 이력이며, 동료 관리자 신뢰 등 나머지 변경은 유지한다.

2026-10-21 최신 main/접근 권한 기반 반영 및 Terraform 12 roots/55 mock plan 통과 후 [PR #39](https://github.com/josiah113366-sketch/clothes-query/pull/39)을 생성했다. base는 infra/generator-was-access이며 PR #38이 main에 머지되면 main으로 바꾼다. 이번 Git 정리에서 AWS 재적용·PR 승인·머지는 하지 않았다. 아래 로컬 보관 표현은 실제 적용 당시의 기록이다.

## 사용자 결정과 범위

2026-10-21 사용자가 누적 비용 확인과 감사 로그 중지를 요청했다. 개발 EKS의 audit 수집만 중단하고 다른 로그 4종과 기존 30일 보관은 유지한다. 이 요청은 해당 Terraform 변경의 실제 적용까지 승인한 것으로 처리한다. 기존 접근 권한 작업 브랜치를 반영해 현재 AWS의 공개 API/관리자 신뢰 설정을 보존한다. 다른 인프라·데이터 변경이나 보류 중인 알림·CI/CD 작업은 적용하지 않는다. PR 승인·머지는 팀원이 한다.

## 완료 확인

- Terraform fmt/validate 및 기존 EKS mock 검사.
- 실제 plan이 EKS enabled_cluster_log_types에서 audit 제거 1건인지 확인.
- 적용 후 클러스터 로그 설정, Kafka/Connect/Connector 상태와 사후 no-change plan 확인.
- 이번 달 도쿄 CloudWatch 누적 청구 추정치와 audit-only 추정 한계를 구분.

## 작업 결과

- **변경:** 기존 EKS의 enabled_cluster_log_types에서 audit만 제거했다. 다른 로그 4종·30일 보관·네트워크·관리자 신뢰·노드·Kafka 설정은 보존했다. 기존 감사 로그는 삭제하지 않았다.
- **검증:** 모듈/스택 fmt, 스택 validate, 기존 eks-access mock 8개 통과. 실제 plan 생성0·수정1·삭제0에서 변경 필드가 enabled_cluster_log_types 하나이고 audit만 빠짐을 확인한 뒤 적용했다. 실제 EKS ACTIVE·audit 비활성·다른 4종 활성, Kafka namespace Pod 전체 Ready, cdc-source와 bronze-s3-sink의 connector/task RUNNING을 확인했다. 사후 EKS plan 변경 없음이다.
- **비용 확인:** 2026-10-01~21(UTC, end exclusive 22) 도쿄 CloudWatch 조회에서 반영된 누적 UnblendedCost는 $2.695171, 그중 VendedLog-Bytes $2.695169였다. 실제 비영(非零) 사용량은 10월 16일부터, 유료 금액은 18~20일에 반영돼 있었다. 21일은 아직 반영되지 않은 상태였다. 비용은 잠정치이며 지연·추후 정산이 가능하다.
- **귀속 한계:** 앞선 10월 19일 Logs Insights 집계에서 감사 로그가 메시지 문자량의 99.49%를 차지했다. 청구는 로그 종류별로 나뉘지 않으므로 $2.70을 감사 로그만의 확정 비용이라고 단정하지 않는다. 전체 누적 감사 로그량을 추가 스캔하지 않았다. 당시 $1.51/일이 유지된다는 가정의 월 약 $45는 미래 절감 규모의 참고치이며 보장하지 않는다.
- **후속:** 수집 중단 전에 발생한 비용·기존 보관 비용은 사라지지 않는다. 청구 지연을 감안해 후속 완료 일자의 수집량과 비용 감소를 확인한다. 적용 코드·기록은 로컬 브랜치에 남기며 push/PR/승인/머지는 수행하지 않는다.

## 후속: 기존 EKS 설정을 보존한 관리자 신뢰 추가

2026-10-21 사용자가 요청한 동료 IAM 사용자 4명을 기존 EKS 관리자 역할의 신뢰 대상으로 추가 적용했다. 기존 2명은 유지해 총 6명이다. 실제 사용자 ARN은 gitignored EKS deployment 입력에만 보관한다. 최신 main 반영·fmt/validate 후 전체 plan에서 기존 관리자 역할 assume_role_policy 수정1개·생성/삭제0개만 확인하고 해당 저장 plan을 적용했다. 현재 이 브랜치의 audit 비활성·공개 API IPv4 범위·private endpoint를 보존하기 위해 이 EKS 구성을 사용했다.

적용 후 실제 역할 신뢰 대상과 cluster 범위 AmazonEKSClusterAdminPolicy를 확인하고 사후 plan 변경 없음을 검증했다. 다른 서비스·공유 IAM 그룹·클러스터/노드/Pod는 변경하지 않았다. 기존 비공개 deployment 입력에도 새 신뢰 목록을 저장했다. 동료별 실제 자격 증명으로 로그인하는 검사는 하지 않았으므로 각자 관리자 role-arn을 지정한 kubeconfig를 사용해 확인한다. PR 승인·머지는 수행하지 않는다. 선행 PR #38이 main에 머지돼 본 PR #39의 base를 main으로 갱신한다.
