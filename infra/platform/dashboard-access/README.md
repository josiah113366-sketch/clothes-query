# 대시보드 연결 계약

대시보드 앱 담당자는 Pod에 namespace dashboard와 serviceAccountName approval-dashboard를 지정한다. 앱 실행·화면·상태 검증·승인 SQL·중복 방지·DAG 호출 conf는 앱 담당자 소유다. 별도 agent 개발 권한은 이 namespace의 배포 권한을 포함하지 않는다.

AWS_REGION=ap-northeast-1, ATHENA_WORKGROUP=clothes-query-dev-dashboard를 사용한다. 읽을 표는 gold_b.anomaly_current와 agent.investigation_reports이며, reprocess_events는 승인 기록 읽기·쓰기용이다. 실제 업무 표가 생성되기 전 SELECT/INSERT 성공을 보장하지 않는다. results는 athena-results/dashboard/이며 쿼리당 1GiB 상한이다. IAM으로 REQUESTED/APPROVED 행만 제한할 수 없으므로 백엔드에서 검증한다.

Airflow 내부 주소는 http://airflow-api-server.airflow.svc.cluster.local:8080이다. 개발 Simple Auth의 approval 사용자로 POST /auth/token을 호출해 얻은 access_token을 Authorization: Bearer에 넣는다. 비밀번호·토큰을 브라우저나 Git에 두지 않는다. 별도 Secret airflow-api-client의 username/password를 백엔드 환경변수로 주입한다. 토큰은 만료 시 다시 발급하고 로그에 남기지 않는다. 이 user 역할은 특정 DAG만 허용하는 권한 체계가 아니다. 재처리 DAG ID와 conf는 담당자 확정 후 연결한다.

이 준비는 namespace/ServiceAccount·AWS 접근과 인증 경로이며 대시보드 Deployment나 이미지·업무 DAG를 설치하지 않는다. 노드 예산과 배치 설정은 실제 이미지 자원 요청을 받은 뒤 검증한다.

자격증명 상태: 2026-10-22 사용자가 구체적인 복제를 승인해 dashboard/airflow-api-client Secret을 생성했다. 기존 approval 사용자만 복제했고 관리자 자격증명·Git 토큰·AWS 키는 공급하지 않았다. 실제 approval-dashboard SA의 임시 Pod에서 POST /auth/token HTTP 201 및 인증한 DAG 읽기 HTTP 200을 확인했다. 토큰·비밀번호는 출력/파일 저장하지 않았고 임시 Pod는 정리했다. 업무 DAG를 실행하지 않았다.

앱 컨테이너에 [환경변수 예제](airflow-client-env.example.yaml)의 env 항목을 반영한다. 예제는 Deployment 전체가 아니라 컨테이너 설정 조각이며 자동 배포하지 않는다. 소스 approval 비밀번호가 회전되면 이 복제 Secret도 운영 담당자가 갱신해야 한다. 내부 Service 호출은 외부 프록시를 우회하도록 앱 네트워크 설정을 확인한다. 실제 시험에서는 프록시를 사용하지 않는 HTTP client로 내부 경로를 확인했다.
