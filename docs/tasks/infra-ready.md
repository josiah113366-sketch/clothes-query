# infra/ready 통합 및 업로드

상태: 완료 (원격 업로드·브랜치 정리 범위) · 2026-10-14

사용자가 기존 `infra/analysis`와 `infra/local-ready`를 포함한 통합 결과를 `infra/ready` 하나로 올리고 두 원격 브랜치 이름을 정리하도록 승인했다. 코드는 커밋 이력에 보존하며 기존 두 브랜치의 최신 tip이 통합 HEAD의 ancestor인지 확인한다. 다른 브랜치와 main은 삭제하거나 변경하지 않는다.

## 포함 범위

- `infra/analysis@088ee05`의 작업 보존 이력과 `infra/local-ready@84080d8`의 추가 구현을 통합했다. 전체 단일 AZ 중간안은 후속 커밋에서 정정했다.
- 최신 main `dc15003`의 팀원 신규 가입 시뮬레이터 변경도 충돌 없이 반영했다. simulator는 해당 main과 동일하며 인프라 담당이 코드를 수정하지 않았다.
- 최종 구성: VPC/EKS 두 AZ·NAT 2개, RDS PostgreSQL 16.15 Single-AZ·크기 보류, WAS HPA 2~3개, 전용 EKS 관리자 역할·현재 사용자/PC 입력 준비.
- Kafka 기본 비활성, broker/controller 3개·RF=3·20 GiB×3·24시간 보관. 업무 토픽/CDC 명세는 팀원 입력 대기다.
- 업무 S3 `clothes-query-datalake`는 별도 승인으로 생성했고 내부는 비어 있다. ECR 두 저장소 외의 다른 AWS 스택은 미배포다.
- DB 크기/저장량, S3 내부 경로, 앱, 도메인/HTTPS는 보류한다. [팀원 입력](../design/infra/team-inputs.md), [현재 구성](../../infra/TOPOLOGY.md), [준비 상태](../../infra/READINESS.md)를 따른다.

## 검증과 업로드 원칙

최종 인프라 코드의 Terraform 10 roots·mock plan 44개, Helm/공식 CRD·잘못된 입력 거부 21개 검증이 통과했다. Docker 이미지·TLS/ACL·CDC·재시작·데이터/offset 보존 검사도 이전 통합 단계에서 통과했다. 이번 최신 main 병합은 simulator/docs에만 적용됐으며 인프라 실행 코드는 바뀌지 않았다. 원격 CI와 실제 AWS 배포 검증은 별도다. 이미지 report-only scan의 이전 High 35개 기록도 배포 승인을 뜻하지 않는다.

업로드 직전 추적 파일의 비공개 입력/state/plan 제외 및 infra/docs/workflow 신규 이력의 민감값 패턴 점검을 통과했다. 패턴 검사는 완전한 비밀 탐지 보장은 아니다.

새 브랜치의 원격 커밋 일치를 먼저 확인하고, 예전 두 원격 브랜치는 점검한 tip과 일치할 때만 lease를 걸어 삭제한다. 코드가 삭제되는 것이 아니라 원격 브랜치 참조 이름이 정리되는 것이다. PR 생성과 main 병합은 이번 요청에 포함하지 않는다.

## 실행 결과

`infra/ready@d9b0a76`를 업로드해 원격 tip 일치를 확인했다. `infra/analysis@7cdd4d5`와 `infra/local-ready@84080d8`가 HEAD의 ancestor이며 원격 tip이 점검 당시 그대로임을 재확인한 후, atomic push와 각 ref의 force-with-lease로 두 원격 이름만 삭제했다. 로컬 `infra/analysis@088ee05`도 통합 이력이 포함된 상태에서 `git branch -d`로 정리했다. 현재 로컬 인프라 브랜치 이름은 `infra/ready` 하나다. `main`, `infra/bootstrap`, 팀원 브랜치는 삭제하거나 수정하지 않았다.

이 완료 기록은 위 업로드 이후 문서만 보완한 것이다. 최종 원격 HEAD는 마지막 문서 커밋 업로드 후 다시 확인한다. 소스 브랜치 이름을 삭제했으므로 과거 지시서의 해당 branch checkout/diff 예시는 당시 기록으로만 읽고, 현재 소스와 상태는 `infra/ready`에서 확인한다. 새 GitHub Actions의 실행 결과는 별도로 확인한다.
