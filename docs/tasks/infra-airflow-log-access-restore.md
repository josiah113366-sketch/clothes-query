# Airflow S3 작업 로그 접근 복구

상태: AWS 연결·Pod 재시작·관찰 계정 로그 조회 검증 완료 (2026-10-23)
브랜치: infra/airflow-log-access-restore

## 문제

판정 DAG는 실행되지만 UI 로그가 비었다. 최신 main의 workload-access 공유 bindings에는 로그 역할 두 개가 포함되어 있었으나, 실환경 IAM 역할 두 개와 airflow namespace Pod Identity association이 모두 없었다. API의 S3 접근에서 NoCredentialsError를 재현했다. 제거를 일으킨 주체·명령은 이번 점검으로 확정하지 않았다.

## 적용

최신 main의 기존 설정 그대로 workload-access를 init/validate/plan했다. 변경은 로그 전용 IAM 역할 2개·inline 정책 2개·Pod Identity association 2개 create뿐이었다. Bronze·Bronze v2를 포함한 기존 리소스 update/delete/replace는 없었다. 적용 후 전체 workload-access plan의 managed 변경은 0개였다.

스케줄러는 airflow-logs/ 읽기·쓰기, API는 읽기만 갖는다. 실제 Secret·토큰·비밀번호는 출력하지 않았다. 실행 중/queued 업무가 없음을 확인하고 과거 task 로그 42개를 비공개 archive와 원래 S3 로그 key에 보존했다. If-None-Match로 기존 객체를 덮어쓰지 않았다. 테스트 업무 데이터는 만들지 않았다.

API와 scheduler는 기존 Recreate 전략으로 순차 재시작했다. 새 Pod의 실제 STS 신원이 각각 로그 전용 역할임을 확인하고 S3에서 18:05 실패 로그를 읽었다. observer 계정으로 Airflow 로그 REST API를 호출해 HTTP 200과 실제 TABLE_NOT_FOUND/payment_attempts 내용이 응답에 포함됨을 확인했다. 로그 조회 경로 복구와 업무 DAG 성공은 별개다. DAG paused 상태·업무 코드·이미지는 바꾸지 않았다.

## 후속 주의

bindings는 한 map 입력이므로 일부 키만 있는 local var-file로 덮어쓰면 공유 map의 다른 연결 삭제를 계획할 수 있다. compute의 Spark 활성화 브랜치와 마찬가지로 최신 공통 설정을 사용하고 전체 plan을 검토한다. 조회·정책·association 존재만으로 이미 떠 있는 Pod의 자격증명 주입을 보장하지 않으므로 실제 Pod STS/S3/API 확인까지 한다. 제거 원인을 조사하지 않고 특정 팀원이나 PR 탓으로 단정하지 않는다.

원격 push·PR·승인·머지는 하지 않았다. 다음 단계는 Gold B 조회 뷰 배포다.
