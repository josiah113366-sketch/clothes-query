# 대시보드 연결 계약

대시보드 앱 담당자는 Pod에 namespace dashboard와 serviceAccountName approval-dashboard를 지정한다. 앱 실행·화면·상태 검증·승인 SQL·중복 방지·DAG 호출 conf는 앱 담당자 소유다. 별도 agent 개발 권한은 이 namespace의 배포 권한을 포함하지 않는다.

AWS_REGION=ap-northeast-1, ATHENA_WORKGROUP=clothes-query-dev-dashboard를 사용한다. 읽을 표는 gold_b.anomaly_current와 agent.investigation_reports이며, reprocess_events는 승인 기록 읽기·쓰기용이다. 실제 업무 표가 생성되기 전 SELECT/INSERT 성공을 보장하지 않는다. results는 athena-results/dashboard/이며 쿼리당 1GiB 상한이다. IAM으로 REQUESTED/APPROVED 행만 제한할 수 없으므로 백엔드에서 검증한다.

Airflow 내부 주소는 http://airflow-api-server.airflow.svc.cluster.local:8080이다. 개발 Simple Auth의 approval 사용자로 POST /auth/token을 호출해 얻은 access_token을 Authorization: Bearer에 넣는다. 비밀번호·토큰을 브라우저나 Git에 두지 않는다. 별도 Secret airflow-api-client의 username/password를 백엔드 환경변수로 주입한다. 토큰은 만료 시 다시 발급하고 로그에 남기지 않는다. 이 user 역할은 특정 DAG만 허용하는 권한 체계가 아니다. 재처리 DAG ID와 conf는 담당자 확정 후 연결한다.

이 준비는 namespace/ServiceAccount·AWS 접근과 인증 경로이며 대시보드 Deployment나 이미지·업무 DAG를 설치하지 않는다. 노드 예산과 배치 설정은 실제 이미지 자원 요청을 받은 뒤 검증한다.

자격증명 상태: airflow-api-client Secret은 아직 만들지 않았다. 기존 approval 비밀번호의 dashboard namespace 복제는 자동 승인 검토에서 구체적인 승인 없이 보관/접근 범위를 넓힌다는 이유로 차단됐다. 사용자가 해당 복제를 명시 승인한 뒤에만 생성한다. namespace/ServiceAccount·AWS 권한·인증 없는 네트워크 도달 검증은 별도로 진행한다.
