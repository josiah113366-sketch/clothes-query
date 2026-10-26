# Silver–Gold A 실제 데이터 대시보드 연결

상태: 로컬 구현·검증 완료 / PR 검토·운영 배포 대기

## 범위

기존 통합 조회·주문/매출·상품 판매·구매 퍼널·리뷰/속성 화면을 유지한다. 기본 운영 모드는 기존 gold_runs 완료 공개 정책을 유지한다(기존 공개 PARTIAL도 보류 경고와 함께 유지). 시연 모드에서만 검증 완료 checkpoint tip의 미공개 퍼널 결과를 읽는다. 계산·집계·점수화 규칙, Gold current·checkpoint·manifest, DAG·Spark는 변경하지 않는다.

- 거래: 공개된 완료 실행 중 선택. 보류 신규 오류값은 제외하고 이전 정상 결과가 있으면 유지한다. 전체 매출 완료를 의미하지 않는다.
- 퍼널: tip SHA256→고정/완료 manifest 일치→고정 inventory와 누적 processed 일치→Athena 3개 테이블 건수 검증 후 조회. 실행 owner가 아닌 검증된 tip을 사용한다.
- 리뷰: 기존 공개 PASS 결과를 사용하고 상품/기간/모델 필터 유지. 속성 점수 건수와 리뷰 건수는 구분한다.
- 지표·차트에 run_id/상태/기록 시각/범위를 표시한다. 처리 파일 수는 고정 입력 기준이며 전체 세션 완전성 보증은 아니다.
- 실제 Gold 상태표 사용. 연결되지 않은 신뢰성 검사와 fallback 장애 기록은 정상·0건으로 표시하지 않는다. Gold B 계약은 바꾸지 않는다.

## 오늘 Windows 로컬 실행

Python 3.12, AWS CLI v2(인증 관리용)가 필요하다. 액세스 키를 소스·.env·tfvars에 쓰지 않는다. 기존 AWS default credential chain을 사용하며 필요한 경우 `-Profile`로 이미 설정된 프로필만 선택한다.

```powershell
# clothes-query 저장소 루트에서 실행
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}'
# SSO 프로필을 이미 사용하는 경우에만: aws sso login --profile <기존 프로필>
.\dashboard\run-local.ps1 -Setup
# 이후 재실행: .\dashboard\run-local.ps1
# 다른 기존 프로필: .\dashboard\run-local.ps1 -Profile <기존 프로필>
```

- `http://localhost:8501`에 접속한다. 127.0.0.1만 바인딩한다. 로컬 AUTH_MODE=dev는 화면 확인용이며 EKS의 기존 AUTH_MODE=local은 변경하지 않는다.
- 가상환경 `dashboard/.venv`, 패키지 `dashboard/requirements.txt`, 환경설정은 `run-local.ps1`가 설정한다. 별도 .env/키 저장은 없다. 종료는 실행 콘솔 Ctrl+C.
- 환경: AWS_REGION=ap-northeast-1, GOLD_A_DATA_SOURCE=athena, GOLD_A_ATHENA_WORKGROUP=clothes-query-dev-dashboard, GOLD_A_DATABASE=gold_a, GOLD_A_OUTPUT_ROOT=s3://clothes-query-datalake.
- launcher가 STS 인증과 workgroup/결과 S3 경로 읽기를 먼저 확인한다. 부족한 권한을 부여하거나 역할을 임의 assume하지 않는다.
- AccessDenied 시 그 항목은 미검증으로 남기고 건너뛴다. 로컬 권한을 확대하거나 반복 재시도하지 않는다. 확인이 필요하면 `aws athena get-work-group --region ap-northeast-1 --work-group clothes-query-dev-dashboard` 및 `aws s3api head-object --region ap-northeast-1 --bucket clothes-query-datalake --key silver/runtime/clicks/catalog-control/incremental.json`을 사용한다. 세부 S3 경로는 #131을 참고한다. Athena SELECT에는 기존 전용 쿼리 결과 prefix 쓰기 권한이 필요하지만 업무 데이터에는 쓰지 않는다.

## 검증 기록

- 새 Windows 로컬 venv(Python 3.12 / Streamlit 1.66.1)에서 기존 19 + 신규 15 = **34 passed**.
- 실제 71999개 상품의 기본 전체 선택은 단일 '전체 상품' 항목으로 표시하며 계산 대상은 그대로 유지한다. 개별 상품/빈 선택·모델·기간 필터 회귀도 확인했다.
- 운영 모드 기존 조회·보류·리뷰 모델 버전 분리, 시연 거래 선택·퍼널 검증 실패 차단, SHA/완료 기록/입력 범위/권한 오류, 모델·기간·빈 상품 선택 회귀 확인.
- 실제 AWS 조회: 퍼널 `funnels-inc-1550c14fc8898fffea6ef8a5`, PARTIAL, 처리 45/1745·미처리 1700. 일별 105038행 / 세션 상세 410319행 / 보류 64행. 일별 조회 합계 view 410319 / cart 29501 / order 12916 / paid 12117. 실제 상품 필터 목록 71999개 읽기 확인.
- 거래 `trade-r6-demo30-20261024T083441Z`, PARTIAL·보류 2, 결제 1건·7900원.
- 리뷰 `reviews-gold-e2e-20261025T143914Z-f18302cd`, PASS, 리뷰 18514 / 속성 점수 30048. 실제 브라우저에서 운영 및 시연 모드의 리뷰 지표·차트·모델 필터 렌더링 확인.
- 운영 시연 신규 IAM은 아직 미적용이므로 운영 UI 검증은 배포 후 진행한다. Spark 이미지·재실행은 불필요하다.

## 내일 반영 순서

1. **인프라 PR #131 먼저 승인·머지**. 최신 main의 `infra/stacks/dashboard-access`에서 init/fmt/validate/plan. `1 add / 0 change / 0 destroy`와 전용 정책 하나만 확인 후 인프라 담당자가 apply.
2. 실제 dashboard Pod 역할로 checkpoint·manifest·inventory GetObject 확인. 정확한 명령은 #131의 `docs/tasks/infra-dashboard-gold-demo-read.md`.
3. **그 다음 이 앱 PR 승인·머지**. main push의 기존 Dashboard deploy workflow가 amd64 이미지 빌드·push하고 deploy/dashboard digest를 갱신한다. Argo CD가 자동 배포한다. 오늘 빌드·push·배포하지 않았다.

```powershell
# 저장소 루트, 앱 PR 머지 후 실행 기록 확인
gh run list --workflow dashboard-deploy.yml --branch main --limit 3
# 해당 main SHA의 실행 ID를 선택한다.
gh run watch <workflow-run-id> --exit-status
# 실패 후 같은 최신 main 재시도 시에만 기존 workflow를 수동 실행한다.
# gh workflow run dashboard-deploy.yml --ref main
kubectl --context clothes-query-dev-admin get application dashboard -n argocd -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision}'
kubectl --context clothes-query-dev-admin rollout status deployment/dashboard -n dashboard --timeout=180s
kubectl --context clothes-query-dev-admin get deployment dashboard -n dashboard -o jsonpath='{.spec.template.spec.containers[0].image}'
```

표준 이미지 빌드 설정은 `.github/workflows/dashboard-deploy.yml`: 컨텍스트 저장소 루트, Dockerfile `infra/platform/dashboard/Dockerfile`, linux/amd64, 태그 main SHA 앞 7자리, ECR `clothes-query-dev/dashboard`, digest는 deploy/dashboard에 기록한다. `deploy.ps1`/`kubectl set image`는 Argo CD selfHeal과 충돌하므로 사용하지 않는다. 수동 강제 push도 하지 않는다.

## 운영 완료 확인

- 로그인 후 기존 5개 상품 화면 확인. 화면 상단과 각 패널 run_id/상태가 같은지 확인.
- 운영 모드에서 기존 미공개 퍼널 정책 유지. 시연 모드에서 45/1745·미처리 1700 및 PARTIAL 경고 표시(실제 checkpoint가 진전되면 그 검증된 범위로 표시).
- 거래 PARTIAL과 보류 사유, 이전 정상값 유지/없음의 차이 표시. 정상 전체 매출로 해석하지 않음.
- 리뷰 PASS·18514/30048을 전체 상품/해당 기간/모델 2.4b_score_s2c · 1.0으로 확인.
- 데이터 상태/신뢰성/관련 장애에 더미 정상값이 실제 검증 결과로 보이지 않는지 확인.
- Gold current·checkpoint·완료 목록·업무 데이터가 변경되지 않았는지 확인. 불일치면 공개 상태를 수정하지 말고 조회 오류/근거를 보고.

## 작업 결과

새 앱을 만들지 않고 기존 조회/화면에 검증된 부분 결과를 읽는 모드를 추가했다. IAM을 별도 PR로 먼저 적용해 자동 이미지 배포와 순서가 충돌하지 않게 했다. PR 머지·Terraform apply·운영 이미지 빌드/배포·DAG 실행은 사용자 및 인프라 담당 승인 대기다.
