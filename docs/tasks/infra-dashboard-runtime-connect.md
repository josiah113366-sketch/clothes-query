# 대시보드 승인·모델 패치노트 실행 연결

상태: AWS 정책·실제 Pod 연결·읽기/인증 검증 완료, 재처리 DAG 미등록 (2026-10-23)
브랜치: infra/dashboard-runtime-connect

## 변경과 근거

기존 적용된 dashboard-access 원본(8492873)의 모듈·스택을 복원했다. 기존 backend key `clothes-query/dev/dashboard-access/terraform.tfstate`로 init/validate 및 baseline plan 변경 0개를 확인했으며 import·새 역할 중복 생성은 하지 않았다.

기존 `approval-dashboard` 역할에 변수 `model_registry_prefix`(기본 review-score/model-registry/releases/)의 GetObject와 해당 prefix ListBucket만 추가했다. 실제 plan은 기존 inline 정책 1개 update뿐이었다. 적용 후 전체 dashboard-access managed 변경은 0개다. IAM 시뮬레이션 7개로 패치노트 읽기 허용, 패치노트 쓰기/삭제·모델 가중치 읽기 거부, ground_truth 명시 거부, reprocess_events 쓰기 유지·anomaly 쓰기 거부를 확인했다.

Deployment는 ServiceAccount approval-dashboard, 전용 workgroup clothes-query-dev-dashboard, AWS_REGION/AWS_DEFAULT_REGION 도쿄, 클러스터 내부 AIRFLOW_API_URL, 기존 Secret airflow-api-client의 username/password를 AIRFLOW_API_USER/PASSWORD로 연결했다. main #94에 있던 dashboard-airflow/user 주석 예시를 실제 이름·키로 고쳤다. 실제 패치는 SA와 환경변수만 대상으로 했고 기존 이미지·계정 Secret·ALB를 변경하지 않았다. 원격 Secret 값은 출력하거나 커밋하지 않았다.

## 실제 검증

실제 대시보드 Pod STS가 승인 전용 역할임을 확인했다. 승인 Backend는 REAL이며 앱이 쓰는 후보·요청 조회가 성공했다(각 0건). 모델 registry index.json 읽기와 등록 버전 1개를 확인했다. 기존 Secret으로 Airflow 토큰 인증 HTTP 201을 확인했다. 승인/재처리 실행·기록 쓰기는 하지 않았다. 기존 노드 UID는 모두 같고 새 노드는 없었다.

앱 기본 계약에 등장하는 gold_b_reprocess 및 silver_gold_a_reprocess는 Airflow GET에서 모두 404다. R1/R4/R5는 POLLER 방식으로 승인 줄을 읽는 업무 DAG가 필요하고, Silver 재처리 DAG ID는 업무 담당의 확정·등록이 필요하다. 인증 연결 완료가 승인→재처리 전체 성공을 뜻하지 않는다. IAM은 REQUESTED/APPROVED 등 행의 내용별 쓰기 제한을 할 수 없으므로 상태 전이·승인자 검증은 앱에서 지킨다.

원격 push·PR·승인·머지는 하지 않았다. 기존 draft #74의 원본과 중복되는 복원 파일은 후속 공유 때 중복 없이 통합한다.
