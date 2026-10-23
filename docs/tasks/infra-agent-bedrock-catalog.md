# 조사 Bedrock 권한 및 판정·조사 표 배포

상태: 적용 및 검증 완료, 로컬 브랜치 보관

브랜치: infra/agent-bedrock-catalog

2026-10-23 사용자가 Bedrock 권한 → #53 표·뷰 배포와 첫 쓰기 시험을 진행하도록 승인했다. 최신 main fe48119에서 작업하며 기존 infra/data-runtime-share에서 Bedrock 관련 파일만 가져왔다. 대시보드·Airflow ConfigMap·Spark·알림 변경은 포함하지 않는다.

## 적용 내용

- investigation-agent Pod Identity의 기존 clothes-query-dev-investigation-agent 역할에 confirmed-investigation-inference-profiles 정책 1개만 추가했다. 기존 IAM 역할·S3·workgroup·정답표 차단 설정은 유지했다.
- 최종 모델은 jp.anthropic.claude-haiku-4-5-20251001-v1:0이다. 도쿄 Bedrock API로 ACTIVE 프로필 및 실제 도쿄·오사카 목적지 모델 ARN 두 개를 확인했다. 선택 프로필의 GetInferenceProfile/InvokeModel, 선택 프로필을 경유하는 목적지 모델 InvokeModel만 허용한다. Nova·다른 프로필·모델 직접 호출·streaming 권한은 추가하지 않는다.
- 기존 Glue DB gold_b와 agent를 재사용했다. main agent/ddl에서 gold_b.anomaly, gold_b.detection_runs, agent.investigation_reports, agent.investigation_runs 및 gold_b.anomaly_current 뷰를 생성했다. database_agent.sql·기존 원장·reprocess_events 정의는 실행하지 않았다.
- 기존 동일 이름 자원이 없는 것을 확인하고 생성했다. Athena 실행 이력 및 해당 DDL 일치를 확인해 이번 실행에서 만든 표만 재개 대상으로 인정했다. 다른 표를 교체하거나 삭제하지 않았다.

## 검증

- Terraform validate 및 Bedrock mock 3개 통과. 실제 plan은 정책 1개 생성, 수정/삭제/교체 0개였다. 적용 후 동일 입력 plan은 변경 없음이다.
- 실제 IAM simulation은 선택 프로필과 그 프로필을 통한 목적지 모델 호출 허용, 모델 직접 호출·Nova 호출 implicitDeny를 확인했다. 실제 Converse/과금 추론은 수행하지 않았다.
- agent/ddl/test_ddl.py의 컬럼·타입·파티션·INSERT 순서·뷰 검사를 통과했다. 배포 후 Glue LOCATION·dt 파티션·projection.enabled 및 뷰 타입을 확인했고 뷰 LIMIT 0도 성공했다.
- Athena가 LOCATION 끝 슬래시를 정규화하는 점과 Windows AWS CLI 응답 인코딩 때문에 초기 검증이 실패했다. 메타데이터 비교의 슬래시 정규화와 UTF-8 출력을 반영해 확인했다. 서버의 DDL과 소스가 일치함을 검증했으며 업무 스키마를 임의 수정하지 않았다.

## 첫 쓰기 및 정리

agent/detection-job ServiceAccount의 일회성 Pod를 기존 Airflow scheduler 노드에 고정했다. 요청 25m CPU/96Mi, 한도 200m/256Mi, activeDeadlineSeconds=300이다. STS의 실제 assumed-role이 clothes-query-dev-detection-job임을 확인한 뒤 판정 workgroup clothes-query-dev-detection에서 고유 TEST-INFRA run_id의 detection_runs 1행 INSERT·조회에 성공했다. 파티션 프로젝션을 유지했고 Glue 파티션 생성 권한이나 임시 IAM 권한은 추가하지 않았다.

시험 Pod는 생성한 UID·라벨을 대조한 뒤 삭제했다. INSERT manifest가 가리키는 새 S3 데이터 파일 1개만 관리자 정리 권한으로 삭제했고 기존 데이터 파일 목록과 대조했다. 기존 업무 파일이나 partition 전체를 지우지 않았다. 같은 run_id 조회 결과가 0행임을 확인했다. 해당 시험 쿼리의 결과·metadata·manifest만 구분해 정리하고 정확한 키의 버전/삭제 마커도 확인했다. Athena 쿼리 실행 이력은 남는다.

기존 노드 UID는 보존됐으며 노드 증설·Spark 실행·업무 DAG 활성화는 하지 않았다. 실제 조사 이미지의 Bedrock 호출·전체 판정/조사 업무 결과는 아직 검증하지 않았다. 두 업무 이미지의 확정 digest를 받으면 AIRFLOW_AGENT_CONFIG 연결과 실제 실행으로 이어간다. Git push·PR·승인·머지는 하지 않았다.

공식 근거: [Inference profile 권한](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html), [프로필로 모델 호출](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-use.html). Converse의 비스트리밍 호출은 InvokeModel 권한을 사용하며 목적지 모델은 프로필 조건으로 제한할 수 있다.
