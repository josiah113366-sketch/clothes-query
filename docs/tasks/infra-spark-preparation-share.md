# 비활성 Spark 실행 기반 통합 공유

상태: 로컬 통합·검증 완료, 초안 PR 준비

## 범위

사용자 승인으로 최신 main `0312bad`에서 원본 `infra/spark-runtime-prep` `c311785`을 통합한다. 원본은 보존한다. 노드 기본 비활성·업무 Job 미생성을 유지한다. 기존 합성 시험은 업무 데이터 성능·S3 입출력/Pod Identity 검증을 대신하지 않는다.

## 작업 결과

기본 이미지·연결 라이브러리, namespace/계정/RBAC/자원 렌더, Driver 1개·Executor 동적 1~2개, t3a.large 한 대분 opt-in NodePool과 로컬 권한 병합 도구를 공유한다. ECR push 개발자 de-ai-18은 확정했지만 실제 권한 적용은 미완료다. namespace·요청 JSON·최종 업무 이미지/인자·커미터·고정 검증 입력/기대값·Glue 공개 명세는 대기한다.

Gold B Kafka 직접 입력 Streaming은 별도 상시 작업 설계로 인지했다. 이 배치 준비만으로 Streaming 운영 배치·자원·checkpoint가 확정됐다고 해석하지 않는다. 현재 작업에서는 실행 코드·권한·노드를 추가로 변경하지 않는다.

## 완료 확인

- [x] 최신 main에서 새 공유 브랜치, 원본 보존.
- [x] enabled=false·업무 Job 기본 미생성 유지.
- [x] Python 회귀 20개, dedicated/shared/custom 3개 렌더 및 미정 권한 계획 렌더 통과. 업무 Job 미생성 확인.
- [x] Terraform fmt, 격리 compute stack/test root validate 및 mock plan 7개 통과. backend·AWS/Kubernetes 자격증명 없음.
- [ ] 초안 PR 공유, 팀원 검토·승인·머지.
