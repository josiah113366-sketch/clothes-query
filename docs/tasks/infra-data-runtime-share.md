# 데이터·Airflow 연결 작업 통합 공유

상태: 로컬 통합·검증 완료, 초안 PR 준비

## 범위

사용자 승인으로 최신 main `0312bad`에서 `infra/agent-runtime-connections` `444418c`, `infra/gold-b-catalog` `7499681`, `infra/live-code-audit` `01ec915`와 현황 문서를 묶는다. 원본 브랜치는 보존한다. 앱·DAG·업무 SQL 구현, AWS 적용·업무 실행은 이번 작업에 포함하지 않는다.

## 작업 결과

공통 대장·README·배포 안내 충돌은 양쪽 내용을 보존해 해결했다. 점검 안내서의 '현재 values가 ConfigMap 방식' 문구를 통합 후 GitDagBundle 설정과 맞췄다. Secret과 runtime override는 기존 비공개 공급을 유지한다. 확정된 JP Haiku 모델·남은 에이전트 업무 연결·Spark Streaming 인지 사항은 현황 문서에만 반영했고 미적용 Bedrock 정책을 활성화하지 않았다. 과거 작업 지시서는 적용·점검 당시 근거로 보존한다.

## 완료 확인

- [x] 최신 main에서 새 브랜치, 기존 원본 보존.
- [x] 카탈로그·권한·Git 공급·DAG 안내·현황 문서 통합.
- [x] Terraform fmt 통과, backend·자격증명 없는 격리 복사본에서 dashboard-access/gold-b-catalog/gold-b-access 및 test root validate 통과, mock plan 7개 통과.
- [x] Airflow chart schema/render 통과: Deployment 3개·Git bundle·paused 기본값·이전 DAG ConfigMap 미마운트·새 PVC/Ingress/노드 미생성 확인.
- [x] 공통 문서 추가 위치를 조정한 뒤 세 공유 브랜치를 합치는 임시 tree 검사 통과. 원본 브랜치 커밋 불변·민감 파일 제외·diff 검사 확인.
- [ ] 초안 PR 공유, 팀원 검토·승인·머지.
