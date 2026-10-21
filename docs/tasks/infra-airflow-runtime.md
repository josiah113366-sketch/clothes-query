# 작업 지시서: infra/airflow-runtime

상태: DB·인증 선택 및 개발 profile 렌더/server dry-run 완료 / 실제 미설치

## 사용자 결정

- 기존 EKS 사용. Airflow 본체 namespace는 airflow, 판정·조사는 별도 agent Pod/ServiceAccount를 재사용한다. agent namespace/역할은 기존 infra/gold-b-access-prep 작업으로 실제 연결·합성 검증됐다.
- 기존 RDS 안에 Airflow 전용 DB·계정을 만든다. 새 RDS를 만들거나 기존 업무 테이블을 변경하지 않는다.
- 개발용 Simple Auth Manager로 시작한다. 현재 개발 구성의 접속은 port-forward로 준비하며 새 ALB를 생성하지 않는다. 고정 역할 기반 개발 인증이며 세부 업무 권한 설계나 DAG allowlist를 대신하지 않는다.
- 실제 설치 전 버전/Helm 호환성·자원 여유·비밀 공급·DB 연결·로그/DAG 공급과 실패 시 복구를 확인한다. 현재는 설정 준비/렌더링이며 EKS/RDS 변경을 수행하지 않는다.
- CI/CD·비용 알림 보류는 유지하며 PR 승인/머지는 팀원이 한다.

## 확인한 사실

- Apache 공식 발표의 최신 3.3 안정판은 3.3.2(2026-09-17). 공식 Helm index의 최신 안정 차트는 1.22.0이며 기본 appVersion은 3.2.2다. 실제 image/version은 3.3.2-python3.12/3.3.2로 명시한다. 차트 archive SHA256을 official index와 대조했다.
- 차트 기본 core.auth_manager는 FAB여서 SimpleAuthManager로 덮어써야 한다. 사용자 비밀번호를 미리 만든 Secret 파일로 공급해 자동 생성 비밀번호의 로그 노출을 피한다. 인증 해제 옵션은 false로 유지한다. operator/admin, observer/viewer, approval/user는 준비용 서비스 이름이며 실제 비밀번호·전달 방식은 비공개로 관리한다.
- EKS 1.36에 대해 Helm 렌더가 성공하는 것은 실제 실행 호환성 검증을 의미하지 않는다. Airflow 3.3.2 prerequisite 페이지의 공식 테스트 Kubernetes 목록은 1.35까지다. 실제 EKS 실행 검증이 필요하다. PostgreSQL 16은 명시된 지원 버전이다.
- 실제 Kafka 노드는 t3a.large, 요청량 CPU 1350m·메모리 3840Mi. 할당 가능량 기준 여유 약 430m/3207Mi다. API 노드는 t3a.medium이지만 API 전용 taint가 있어 Airflow가 사용하지 않도록 유지한다.

## 개발 profile과 남은 일

- LocalExecutor 본체 3개(API·scheduler·dag processor), 일반 작업 병렬1. 판정·조사는 KubernetesPodOperator로 agent namespace의 전용 SA를 지정하는 연결 후보다. 업무 DAG는 담당자가 구현한다. 자체 작업 Pod 생성 RBAC는 아직 추가하지 않았다.
- 본체 requests 합계 300m/1152Mi, DB migration Job 별도 50m/256Mi를 후보로 둔다. 렌더된 init/sidecar/Job의 실제 유효 requests를 검사한다. 이 예약량은 실측 사용량이나 안정성 보장이 아니다. 공식 최소 메모리 권고와 실제 업무 부하를 함께 검토한다.
- Redis/Celery·내장 PostgreSQL·PgBouncer·StatsD·triggerer·추가 ALB/PVC는 비활성. 개발용 Recreate 전략이므로 업데이트 중 중단될 수 있다. 자동으로 무중단을 보장한다고 주장하지 않는다.
- metadata DB 이름/역할 이름, 연결 한도와 Secret 공급·TLS verify-full/CA, RDS 현재 부하·연결 여유 확인 후 DB 생성과 마이그레이션을 준비한다. 현재 DB·계정은 생성하지 않았다.
- Secret은 metadata connection, Fernet, API key, JWT, Simple Auth passwords를 별도 공급하며 공개 values나 Helm --set 명령에 실제 값을 넣지 않는다. 샘플 password를 사용하지 않는다.
- DAG 공급, Kubernetes provider 이미지 검증·고정 digest, agent Pod 실행 RBAC, 실제 task 로그 보관은 아직 미완료다. profile의 remote_logging=false/영속 로그 없음은 초기 렌더용이며 업무 배포 완료 구성으로 취급하지 않는다.
- 실제 설치 직전 자원 재점검 및 필요시 기존 노드에만 배치하는 별도 검증 guard를 사용해 예상치 못한 증설을 피한다. 추가 노드/유료 자원이 필요한 경우 먼저 비용과 구성을 제시한다.

## 참고 자료

- [공식 발표](https://airflow.apache.org/announcements/)
- [Helm 1.22.0](https://airflow.apache.org/docs/helm-chart/1.22.0/index.html)
- [Airflow 3.3.2 요구 조건](https://airflow.apache.org/docs/apache-airflow/3.3.2/installation/prerequisites.html)
- [Simple Auth Manager](https://airflow.apache.org/docs/apache-airflow/3.3.2/core-concepts/auth-manager/simple/index.html)
- [Helm DB/Secret 준비](https://airflow.apache.org/docs/helm-chart/1.22.0/production-guide.html)

## 작업 결과

DB 재사용과 Simple Auth 선택을 기록하고 개발용 values를 준비했다. 공식 chart checksum과 기본 설정을 대조했다. 최종 렌더는 14개 객체(API/DAG processor Deployment, scheduler StatefulSet, migration Job 포함)이며 실제 EKS 1.36 서버 dry-run이 통과했다. 추가 Secret/Ingress/PVC/ClusterRole/내장 DB/Redis는 렌더되지 않는다. LocalExecutor에서 사용하지 않는 chart broker Secret을 억제했고 사용되지 않는 외부 broker 참조가 컨테이너 환경에 없는지도 확인했다.

본체 requests는 300m/1152Mi, migration Job은 50m/256Mi다. scheduler는 단일 replica StatefulSet RollingUpdate, API/DAG processor는 Recreate로 추가 surge를 피한다. 차트 기본 dagProcessor.strategy.rollingUpdate가 병합돼 Recreate와 충돌했던 것을 null로 제거하고 server dry-run을 재통과했다. 파일 문법/Helm schema·diff도 확인했다. 이 결과는 프로세스 메모리 실측·DB 연결·사용자 로그인·업무 DAG 성공을 의미하지 않는다.

실제 Helm 설치·DB/계정/Secret 생성·업무 실행은 아직 수행하지 않았다. 실제 작업은 DB/Secret 공급, 이미지/provider·로그/DAG 공급, 전용 Pod RBAC 준비 이후 이어간다. 중간 PR #14 상태 문의를 읽기 전용 확인했고, 해당 PR은 OPEN이며 신뢰성 SQL은 SQLite 검증만 완료한 초안이다. PR #29도 OPEN으로 실제 판정 잡 연결과 구분했다.
