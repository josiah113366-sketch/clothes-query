# 판정·조사·승인 화면 인프라 연결

2026-10-22 확인. 앱·업무 DAG·모델 선택·표 설계·승인 상태 검증은 담당자 소유이며 인프라는 경로·권한·실행 환경과 연결을 준비한다.

| 대상 | 준비된 연결 | 담당자 제출물 |
|---|---|---|
| DAG | 이 저장소 main의 infra/platform/airflow/dags/, GitDagBundle 60초 갱신, 신규 DAG paused | DAG 파일, 필요한 provider/의존성, 자원·timeout 계약 |
| 판정 이미지 | ECR clothes-query-dev/detection-job, agent/detection-job SA, clothes-query-dev-detection workgroup | 이미지 digest, 실행 명령·환경변수·DAG |
| 조사 이미지 | ECR clothes-query-dev/investigation-agent, agent/investigation-agent SA, clothes-query-dev-investigation workgroup | 이미지 digest, 실행 명령·환경변수·DAG. 추론 프로필은 JP Haiku로 확정, 권한 적용 전 |
| 승인 화면 | dashboard/approval-dashboard SA, clothes-query-dev-dashboard workgroup, athena-results/dashboard/ | 앱 Deployment·이미지, 승인 SQL, 재처리 DAG ID/conf |

## 이미지 push

기존 agent 개발자 역할은 위 두 ECR 저장소 push를 허용한다. 본인 자격증명으로 해당 역할을 사용하는 프로필을 만들고 ECR 로그인 후 새 커밋 태그로 push한다. 태그는 immutable이다. 실제 build/push는 이미지 담당자가 실행한다. 장기 키를 이미지나 Pod에 넣지 않는다.

현재 판정 Dockerfile은 agent/detect context, 조사 PR #54 Dockerfile은 agent context다. 판정도 agent에서 빌드하려면 담당자가 COPY/실행 경로를 바꾼 Dockerfile을 제출해야 한다. [상세 명령과 권한 범위](../infra/platform/agent-development/README.md).

## 표와 첫 쓰기

PR #53 detection_runs와 같은 파티션 프로젝션 형식을 격리된 임시 표로 시험해, 실제 판정 SA에서 INSERT 후 SELECT 1행 성공을 확인했다. 추가 Glue 파티션 권한은 필요 없었다. 시험 표·Pod·S3 객체 버전을 정리했다. 업무 표 4개·뷰·reprocess_events를 생성한 결과가 아니다. 확정된 DDL은 담당자가 제출하고 인프라가 그 정의를 배포한다. [시험 근거와 범위](../infra/platform/agent-access/projection-validation.md).

## 승인 화면

읽기 대상은 gold_b.anomaly_current 및 원본 anomaly, agent.investigation_reports, gold_b.reprocess_events다. 업무 쓰기는 gold_b/reprocess_events/에만 허용한다. 정답표·다른 결과 경로·다른 업무 데이터 쓰기·객체 삭제는 차단한다. REQUESTED/APPROVED 값 제한·상태 전이·중복 승인 방지는 앱 담당자가 구현한다.

Airflow 내부 주소와 토큰 호출 방식은 [대시보드 연결 안내](../infra/platform/dashboard-access/README.md)에 있다. 2026-10-22 사용자 명시 승인 후 기존 approval 사용자 자격증명을 dashboard/airflow-api-client Secret으로 복제했다. 실제 대시보드 ServiceAccount Pod에서 토큰 발급 HTTP 201·인증한 DAG 읽기 HTTP 200을 확인했고 임시 Pod는 정리했다. 앱 담당자는 [환경변수 조각](../infra/platform/dashboard-access/airflow-client-env.example.yaml)을 컨테이너에 연결한다. 토큰 발급/갱신 코드는 백엔드 담당자가 작성하고, DAG ID/conf 확정 후 실제 호출을 연결한다. 업무 DAG는 실행하지 않았다. 원본 비밀번호 회전 시 복제 Secret도 갱신해야 한다.

## Bedrock

담당자가 jp.anthropic.claude-haiku-4-5-20251001-v1:0을 최종 선택했고 Nova는 제외했다. 해당 프로필과 조회된 목적지 모델 ARN만 연결할 변수 구조를 준비했다. 공유 입력은 아직 비어 있어 호출 권한은 추가되지 않았고 실제 Pod 추론도 실행하지 않았다. JP 프로필의 목적지는 도쿄·오사카로 확인한 이력이 있으며 실제 정책 적용 전에 ARN을 재조회한다.

IAM의 Converse 호출 권한은 bedrock:InvokeModel이며 목적지 모델 허용은 bedrock:InferenceProfileArn 조건으로 선택한 프로필에 묶는다. [AWS 공식 전제 조건](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html).

## 배포와 자원

Airflow 본체의 기존 자원·parallelism=1·노드 고정과 신규 DAG paused 기본값을 유지한다. 무거운 업무 코드는 ECR 이미지의 별도 Pod로 실행한다. Git 갱신으로 Python 패키지가 자동 설치되지는 않는다. 실제 이미지의 자원 요구량을 받은 뒤 5분 동시 실행과 추가 노드 여부를 검증한다. 새 노드나 Argo CD는 추가하지 않았다. 자동 머지하지 않는다.
