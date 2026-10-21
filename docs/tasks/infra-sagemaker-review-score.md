# 작업 지시서: infra/sagemaker-review-score

> 상태: 보류 (apply 완료, GPU 서비스 쿼터 증설 요청·승인 대기) · 브랜치: `infra/sagemaker-review-score` · 다음 작업: `review-model/score-batch-airflow` (입력 모으기·실행 스크립트 개선, 별도 PR)

## 목표

리뷰 점수화(s2c 합친 모델, `review-analysis/deploy/`)를 SageMaker Processing Job 으로 돌릴 **AWS 실행 기반**을 Terraform 으로 만든다:
Job 실행 IAM 역할, 보안 그룹, 스크립트용 SSM 설정, Airflow 가 붙일 launcher 정책.
Job 자체, 스케줄, 스크립트 수정은 만들지 않는다(실행은 Airflow silver DAG 종료 후 Airflow 가 한다).

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`, `review-analysis/CLAUDE.md`
- `review-analysis/deploy/README.md`, `run_processing_job.py`, `score_batch.py`
- `infra/stacks/ecs-review-simulator/README.md` (같은 방식의 선행 스택: 비공개 입력, remote state, SSM 설정)
- `infra/stacks/network/`, `infra/stacks/storage/` (output 을 remote state 로 받는다)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 2026-10-21 팀 관리자 승인으로 개인 계정이 아닌 **팀 계정**에 만든다.
- 알림 이메일(실패 알림 SNS)과 월 예산은 만들지 않는다.
- 실행은 EventBridge 스케줄이 아니라 **Airflow silver DAG 종료 신호**로 Airflow 가 시작한다.
- 결과는 `s3://<버킷>/silver/review-score/output/`, 오류는 `s3://<버킷>/silver/review-score/error/` 에 쓴다.
- 실측(개인 계정, 도쿄, `ml.g4dn.xlarge`, AWS PyTorch DLC): 1,000건 약 27분, 시간당 0.994 USD, 1회 약 0.46 USD.

## 시작 전 확인 (Claude가 한다)

- 브랜치가 `infra/sagemaker-review-score` 이고 최신 `main` 을 반영했는지 (apply 직전에 다시 확인)
- 팀 계정 자격증명이 있고 `TF_VAR_expected_account_id` 가 그 계정인지, state 버킷이 같은 계정 것인지
- network·storage 스택이 이미 apply 되어 있는지 (output 이 있어야 plan 이 된다)
- `ml.g4dn.xlarge for processing job usage` 쿼터가 1 이상인지 (스택 README 의 명령)

## 만드는 것

### 1. 모듈 `infra/modules/sagemaker-review-score/`
- Job 실행 IAM 역할: 읽기 `bronze/reviews/*`·`review-score/model/*`·`review-score/code/*`, 쓰기 `silver/review-score/output/*`·`error/*`,
  CloudWatch 로그·지표, AWS 공개 DLC 이미지 pull, VPC ENI. 정답 라벨·gold_b 접근 없음
- 보안 그룹(나가는 443 만, `use_vpc=true`), SSM 설정 파라미터(JSON), launcher IAM 정책(Job 생성/조회/중지·PassRole·SSM 읽기)

### 2. 스택 `infra/stacks/sagemaker-review-score/`
- backend key `clothes-query/dev/sagemaker-review-score/terraform.tfstate`, 비공개 값은 gitignore 된 `deployment.backend.hcl`·`deployment.local.tfvars`
- 이름 접두사 `clothes-query-dev-sagemaker-review-score`, 태그 `Component=sagemaker-review-score`
- README 와 `infra/README.md` 스택 표

## 만들지 않는 것

- Processing Job, 스케줄(EventBridge), 이메일 알림, 월 예산
- launcher 정책을 Airflow 역할에 붙이는 일 → Airflow 담당 또는 `workload-access` 후속
- `score_batch.py` 가 날짜 파티션 여러 파일을 읽게 하는 수정, `run_processing_job.py` 가 SSM 설정을 읽게 하는 수정, 오류를 `error/` 에 쓰는 코드 → `review-model` 영역 별도 PR
- 모델·코드 S3 업로드, GPU 쿼터 증설 요청(계정 설정 변경은 재영 확인 후)

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. 모듈 → 스택 → README 순으로 작성한다
3. `terraform fmt` → `validate` → `plan` (destroy/replace 가 있으면 먼저 알린다)
4. 재영이 plan 확인 후 apply, 결과를 PR 에 첨부한다
5. "완료 확인"을 실행하고 결과를 이 문서 맨 아래에 기록한다

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [x] `terraform fmt -check -recursive` (스택·모듈)
- [x] `terraform init -backend=false` 후 `terraform validate`
- [x] `terraform plan` → 첫 plan 은 9 create, 0 change, 0 destroy
- [ ] GPU 쿼터 조회 명령 실행 결과가 1 이상 (또는 증설 승인) ← 2026-10-21 증설 요청 필요, 승인 대기 중
- [ ] apply 후 `terraform plan` 이 변경 없음
- [ ] apply 후 SSM 파라미터 JSON 에 `role_arn`·`network`·`output_prefix`·`error_prefix` 가 있고, 계정 ID·버킷 이름이 저장소 파일에는 없음 (`git grep`)
- [ ] (후속 PR 이후) 100건 입력으로 Job 1회 실행 → `silver/review-score/output/` 에 CSV, 실패 건은 `error/` 에 기록

## README 갱신

- `infra/stacks/sagemaker-review-score/README.md`, `infra/modules/sagemaker-review-score/README.md` (작성함)
- `infra/README.md` 스택 표 (작성함), `docs/BRANCHES.md` 대장 한 줄 (작성함, 머지 때 상태 변경)

## 작업 결과 (머지 전에 작성한다. 사람과 AI가 나중에 이 브랜치가 무엇을 했는지 읽는 곳이다)

- **한 줄 요약:** 리뷰 점수화 Processing Job 을 팀 계정에서 돌리기 위한 IAM·SG·SSM 설정·launcher 정책 스택.
- **무엇을 만들었나:** `infra/modules/sagemaker-review-score/`, `infra/stacks/sagemaker-review-score/` (위 "만드는 것").
- **왜 그렇게 했나:** Job 은 호출마다 이름·입력 날짜가 달라 Terraform 리소스가 될 수 없고 Airflow 가 시작하므로, 실행 기반과 설정(SSM)만 코드로 둔다.
  스케줄·알림·예산은 요청으로 제외. 이미지는 AWS 공개 DLC 를 써서 팀 ECR 이 필요 없다.
- **입력과 출력:** 입력 `bronze/reviews/` 읽기, 모델·코드 `review-score/` 읽기. 출력 `silver/review-score/output/`, 오류 `silver/review-score/error/`.
  Airflow 와는 SSM 파라미터 `/clothes-query/dev/sagemaker-review-score/config` 와 `launcher_policy_arn` output 으로 맞춘다.
- **확인한 결과:** fmt·validate 통과, 첫 plan 9 create / 0 change / 0 destroy. (apply 후 항목은 위 체크리스트에서 채운다)
- **알려진 한계·남은 일:** GPU 쿼터 확인, launcher 정책 연결, `score_batch.py`·`run_processing_job.py` 수정(별도 PR), 오류 파일 기록 방식 결정,
  `/aws/sagemaker/ProcessingJobs` 로그 보존 기간(무기한) 정책.
