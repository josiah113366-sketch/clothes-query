# 대시보드 연결 계약

대시보드 앱 담당자는 Pod에 namespace dashboard와 serviceAccountName approval-dashboard를 지정한다. 앱 실행·화면·상태 검증·승인 SQL·중복 방지·DAG 호출 conf는 앱 담당자 소유다. 별도 agent 개발 권한은 이 namespace의 배포 권한을 포함하지 않는다.

AWS_REGION/AWS_DEFAULT_REGION=ap-northeast-1, APPROVAL_ATHENA_WORKGROUP=clothes-query-dev-dashboard를 사용한다. 읽을 표는 gold_b.anomaly_current와 agent.investigation_reports이며, reprocess_events는 승인 기록 읽기·쓰기용이다. results는 athena-results/dashboard/이며 쿼리당 1GiB 상한이다. IAM으로 REQUESTED/APPROVED 행만 제한할 수 없으므로 백엔드에서 검증한다.

Airflow 내부 주소는 http://airflow-api-server.airflow.svc.cluster.local:8080이다. 개발 Simple Auth의 approval 사용자로 POST /auth/token을 호출해 얻은 access_token을 Authorization: Bearer에 넣는다. 비밀번호·토큰을 브라우저나 Git에 두지 않는다. 별도 Secret airflow-api-client의 username/password를 백엔드 환경변수로 주입한다. 토큰은 만료 시 다시 발급하고 로그에 남기지 않는다. 이 user 역할은 특정 DAG만 허용하는 권한 체계가 아니다. 재처리 DAG ID와 conf는 담당자 확정 후 연결한다.

2026-10-23에는 기존 대시보드 Deployment에 이 계정과 환경변수 연결을 적용했다. 이미지·사용자 계정 파일은 변경하지 않았다. 실제 Pod의 승인 후보/요청 읽기·모델 registry 읽기와 Airflow 인증 성공을 확인했다. 업무 DAG는 별도이며 gold_b_reprocess와 silver_gold_a_reprocess 조회는 현재 404다. [작업 기록](../../../docs/tasks/infra-dashboard-runtime-connect.md)을 참고한다.

자격증명 상태: 기존에 승인·생성된 dashboard/airflow-api-client Secret의 username/password를 AIRFLOW_API_USER/PASSWORD로 참조한다. 실제 값은 문서·Git·로그에 두지 않는다. 이번 연결에서는 비밀번호를 새로 복제하거나 변경하지 않았다.

앱 컨테이너의 [환경변수 예제](airflow-client-env.example.yaml)는 전체 Deployment가 아닌 참조용 조각이다. 현재 실제 Deployment의 APPROVAL_ATHENA_WORKGROUP과 기존 Secret username/password 연결이 우선한다. 원본 approval 비밀번호가 회전되면 연결된 Secret도 운영 담당자가 갱신하고 내부 Service 호출의 프록시 우회를 확인한다.
