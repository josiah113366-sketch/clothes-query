# 판정·조사 DAG 실행 설정 연결

업무 이미지는 동료가 빌드·push한다. 인프라 담당은 전달된 digest와 실제 ECR 태그를 대조하고 기존 Airflow values에 실행 설정을 연결한다. 값 준비와 적용은 별도 단계다.

## 공급 방식

- namespace airflow의 ConfigMap airflow-agent-runtime, data.config JSON을 AIRFLOW_AGENT_CONFIG 환경변수로 공급한다.
- 기존 인프라 GitDagBundle와 env·Secret 참조를 보존하고 main의 agent/dags를 읽는 agent-dags GitDagBundle를 추가한다.
- 두 DAG ID는 agent_detection_5min, agent_investigation_5min이다. 초기 paused를 유지하며 구성 연결만으로 수동 실행하거나 주기를 활성화하지 않는다.
- 실제 이미지는 digest로 고정한다. region·두 전용 workgroup·확정 Bedrock 프로필·investigate_max를 공급한다. hostname은 생략해 특정 노드에 고정하지 않는다.
- #109 이후 R6는 `silver_checks_table=silver.order_amount_checks`와 `silver_runs_table=silver.silver_runs`를 함께 넣는다. 준비 도구는 두 값이 모두 정확히 일치할 때만 허용한다. DAG가 판정 Pod에 SILVER_CHECKS_TABLE·SILVER_RUNS_TABLE로 전달하며 조사 Pod에는 전달하지 않는다. 새 R6 업무 이미지 digest를 확인하기 전에는 구 이미지에 이 설정을 활성화하지 않는다.
- 제출 Pod는 agent/detection-job 및 agent/investigation-agent ServiceAccount와 기존 Pod Identity를 사용한다. ConfigMap은 AWS 키·토큰·비밀번호를 공급하지 않는다.

## 준비 및 검토

prepare_agent_runtime.py는 로컬 렌더 도구다. AWS/Kubernetes를 호출하거나 리소스를 적용하지 않는다. 실제 설정 JSON과 기존 Helm values는 Git 제외 경로에서 공급한다.

```powershell
python infra/platform/airflow/prepare_agent_runtime.py --config .cache/agent-config.private.json --base-values .cache/airflow-values.private.yaml --output-dir .cache/agent-review
```

기존 설정을 병합해 Helm 전체 candidate를 검토한다. overlay만을 전체 values처럼 사용해 기존 DB·인증·로그·배치 설정을 지우면 안 된다. 실제 ConfigMap 값·Helm values·렌더·Secret은 커밋하지 않는다.

적용 전에는 실행 중인 DAG/태스크가 없는지와 기존 paused 상태, 현재 Helm revision/values를 다시 확인한다. 같은 chart와 Airflow 버전을 유지하고 변경은 config 참조 및 새 Git bundle로 제한한다. 현재 Recreate 전략에서는 Airflow 재시작 중 접속이 잠시 중단된다. migration Job이 남아 있다면 완료·release 소유권을 입증한 뒤 필요한 경우에만 재생성한다. 업무 Job은 삭제하거나 실행하지 않는다.

ConfigMap에서 환경변수로 읽는 값은 실행 중 Pod에 자동 반영되지 않는다. 이미지 digest와 설정 변경은 함께 검토하고 작업이 없는 시점의 순차 재시작 후 실제 DAG/Pod 설정을 대조한다. 실행 태스크가 없다는 사실만으로 다음 5분 예약과 겹치지 않는다고 보장할 수 없으므로 활성 DAG의 배포 창을 별도로 관리한다. LocalExecutor parallelism=1에서는 장시간 Spark 제출/대기가 판정 작업의 큐 지연을 만들 수 있으며 이 대기를 판정 계산 시간과 구분한다.

적용 후에는 실제 DAG 등록·import 오류·paused 상태·실행 이력 0개와 노드 UID 보존을 확인한다. 이는 판정/조사 업무 코드·Athena 전체 조회·모델 응답 성공을 증명하지 않는다. 수동 1회 검증과 5분 주기 활성화는 별도 단계다.

승인 화면은 dashboard/airflow-api-client Secret의 username·password 키를 AIRFLOW_API_USER·AIRFLOW_API_PASSWORD에 연결한다. 실제 Secret 값은 이 문서나 ConfigMap에 넣지 않는다. 현재 개발 인증은 Simple Auth Manager이며 업무 API 인증을 EKS IAM 권한으로 대신하지 않는다.
