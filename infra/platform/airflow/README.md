# Airflow 실행 기반 후보

상태: 제안(운영 배포) / 로컬 검증 완료 · 2026-10-16

사용자가 Airflow를 AWS 배포 전에 로컬에서 검증하도록 요청했다. [local-smoke](local-smoke/README.md)는 공식 Airflow 3.3.2 이미지·LocalExecutor·일회성 PostgreSQL 메타데이터 DB로 API 실행·인증·5분 예약·동시 실행 제한을 검사한다. 운영 버전/Executor/인증 모듈을 확정하거나 AWS/Helm 리소스를 생성하는 변경은 아니다. 팀원의 이상 판정·재처리 업무 DAG는 구현하지 않는다.

[실행 결과](../../../docs/design/infra/airflow-local-validation-2026-10-16.md): 인증/권한 거부·API 재처리·중복 ID 거부·비중첩·활성화 이후 실제 5분 예약 두 번·OOM/재시작 없음·project 정리를 통과했다. synthetic 작업에서 관측한 상시 컨테이너+테스트 DB 메모리 합의 최고치는 약 0.95GiB다. 이 수치는 Athena 업무 부하나 EKS의 전체 자원 예산이 아니다.

현재 EKS compute는 t3a.large, 6 vCPU/24GiB 한도이며 평소 한 대 목표다. 기존 Kafka 자원 검증에는 Airflow가 포함되지 않았다. Airflow를 추가한 전체 Pod 배치·메모리/CPU·DB 연결·노드 확장·비용은 다시 검증해야 한다. 같은 RDS를 메타데이터 DB로 사용할지는 미정이다.

운영 전에 정할 입력은 Airflow 버전·Executor·배포 담당, 메타데이터 DB/전용 계정, 승인 처리 백엔드의 실행 위치와 네트워크 경로, Auth Manager와 DAG별 최소 권한, 이미지/DAG 공급·로그 보관, 작업별 자원과 Athena/Glue/S3 IAM이다. 조사 에이전트와 채점 작업의 역할·S3 prefix·Athena 결과 경로도 분리한다. 로컬 SimpleAuthManager는 운영의 DAG별 권한 검증을 대신하지 않는다.

후속 팀원 계약: 재처리 DAG 종료 시 판정 DAG를 직접 호출하지 않는다. 5분 판정 작업이 `reprocess_events`의 새 교체 완료 기록을 읽어 재판정한다. 실측에는 해당 Athena 읽기 조회도 포함한다. 정답표는 `[버킷]/ground_truth/incident_log/`의 JSON이며 조사 에이전트는 `gold_b/`만 읽고 `ground_truth/` 전체 접근을 막는다. 판정 역할과 조사 에이전트 역할을 분리해야 하며 LocalExecutor의 DAG 이름만으로 자격증명을 격리했다고 간주하지 않는다. [확정 내용과 받을 입력](../../../docs/design/infra/team-inputs.md).
