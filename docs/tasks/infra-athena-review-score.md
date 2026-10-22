# 작업 지시서: infra/athena-review-score

> 상태: 초안 (코드·validate·plan 작성, 방식 확정 대기) · 브랜치: `infra/athena-review-score` (제안) · 다음 작업: `review-model/score-to-iceberg` (Airflow 태스크·SageMaker 출력 경로 변경)

## 목표

리뷰 점수 결과(`review_id, aspect, score, model_version, analyzed_at`)를 파일 덮어쓰기 대신 **Iceberg 테이블에 MERGE 로 반영**하는 Athena/Glue 기반을 Terraform 으로 만든다(방식 D).
이번 브랜치는 기반(Glue DB, Athena 워크그룹, Airflow 용 IAM 정책, SSM 설정)과 SQL 템플릿까지다. Airflow 태스크, SageMaker 출력 경로 변경, 실제 데이터 이행은 만들지 않는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`
- `docs/tasks/infra-sagemaker-review-score.md` (선행 작업: 점수화 Job 기반, 결과 경로·파티션 결정)
- `infra/stacks/sagemaker-review-score/README.md` (현재 방식 A: 날짜+모델버전별 파일 덮어쓰기)
- `pipelines/silver/README.md` (Silver 리뷰 입력 구조, KST 작성일 파티션)
- `infra/stacks/storage/` (데이터 버킷, remote state 로 받음)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 2026-10-22 결정: 점수 결과는 Parquet 이고, 날짜 파티션은 **후기 작성일(KST)** 이다(실행한 날이 아님). `model_version` 은 경로가 아니라 열이다.
- 2026-10-22 결정: 결과 관리 방식은 **D(Iceberg + MERGE)** 로 진행한다(A 덮어쓰기와 비교 후). 작업은 작업 지시서와 Terraform 초안부터 한다.
- 2026-10-22 결정: 다시 점수화했을 때 새 결과에서 **빠진 속성은 삭제**한다(`merge.sql` 의 tombstone 처리).
- 2026-10-22 결정: Gold 는 후기마다 **`model_version_no` 가 가장 큰 결과**를 읽는다. 모델 번호 `model_version_no`("x.y", decimal(4,1)): 평가 모델/로직이 바뀌면 메이저를 올리고(0.0→1.0), 작은 수정·버그 수정이면 마이너를 올린다(0.0→0.1). 마이너는 0~9 까지이고 x.9 다음 변경은 메이저를 올린다. 현재 `2.4b_score_s2c` = `1.0`.
- 2026-10-22 결정: Gold 가 읽는 **Athena 뷰 `review_aspect_scores_latest`** 를 Terraform(Glue `VIRTUAL_VIEW`)으로 만든다. 뷰는 후기마다 `model_version_no` 최대 결과이며, Gold 는 `review_date` 로 걸러 읽는다.
- 2026-10-22 결정: 매일 입력은 **아직 점수가 없는 후기만**이다(`select_unscored.py`). 이를 위해 후기별 점수 로그 테이블 `review_score_log`(속성이 0개인 후기도 한 행)를 둔다. 모델 번호를 올리면 전부 다시 점수화된다.
- 방식 A(날짜+모델버전별 파일 덮어쓰기)로 이미 만든 `sagemaker-review-score` 스택은 그대로 둔다. 전환(출력 prefix 를 staging 으로 변경)은 별도 변경이다.
- 하루 후기 수와 늦게 오는 후기 빈도는 아직 모른다. 이 값이 확정되면 D 가 과한지 다시 판단한다(한 번에 처리 가능한 양: 현재 실측으로 Job 당 약 2,200건, 최대 실행시간 3600초).

## 시작 전 확인 (Claude가 한다)

- 브랜치가 최신 `main` 에서 만들어졌는지, `sagemaker-review-score` 변경이 main 에 반영됐는지
- 팀 계정 자격증명이 있고 공유 설정 `deployment.auto.tfvars.json` 의 `expected_account_id` 와 state 버킷이 같은 계정인지
- storage 스택이 apply 되어 있는지(output `bucket_name`, `bucket_arn` 필요)
- Athena 엔진 v3, Iceberg `MERGE`/`OPTIMIZE`/`VACUUM` 문법이 도쿄 리전에서 지원되는지(공식 문서 확인)

## 만드는 것

### 1. 모듈 `infra/modules/athena-review-score/`
- Glue 데이터베이스, Iceberg 테이블 2개(점수 `review_aspect_scores`, 점수 로그 `review_score_log`, 스키마·`review_date` 파티션)와 staging 외부 테이블 2개, Athena 워크그룹(엔진 v3, 결과 위치, 쿼리당 스캔 10GB 한도, 설정 강제)
- Airflow 가 붙일 IAM 정책 `athena_runner`: 해당 워크그룹의 Athena 쿼리, 해당 DB·테이블의 Glue 읽기/`CreateTable`·`UpdateTable`, S3 staging 읽기·테이블 prefix 읽기/쓰기/삭제·결과 prefix 읽기/쓰기
- 스크립트용 SSM 설정 파라미터(워크그룹, DB, 테이블, S3 위치)

### 2. 스택 `infra/stacks/athena-review-score/`
- backend key `clothes-query/dev/athena-review-score/terraform.tfstate`, 계정 ID·state 버킷은 추적되는 `deployment.auto.tfvars.json`·`deployment.backend.hcl`(공통 배포 설정 규칙, `infra/DEPLOYMENT_CONFIG.md`), 개인 값은 `deployment.local.tfvars.json`(Git 제외)
- 이름 접두사 `clothes-query-dev-athena-review-score`, 태그 `Component=athena-review-score`, storage 스택을 remote state 로 읽음
- README 와 `sql/` 템플릿: `merge.sql`(upsert + 빠진 속성 삭제), `merge_log.sql`, `migrate_add_model_version_no.sql`(한 번만), `optimize.sql`, `vacuum.sql`, `read_latest.sql`(후기마다 `model_version_no` 최대)
- `infra/README.md` 스택 표 한 줄

## 만들지 않는 것

- MERGE/OPTIMIZE/VACUUM 를 실행하는 Airflow 태스크, 정기 일정 → Airflow 담당 또는 후속 브랜치
- `stacks/sagemaker-review-score` 의 출력 prefix 변경과 Job 역할 쓰기 권한 변경 → 후속 변경(이미 apply 된 스택이라 별도 plan)
- S3 수명주기 규칙(staging·Athena 결과 정리) → storage 스택 소유라 이 스택에서 하지 않음
- `athena_runner` 정책을 Airflow 역할에 붙이는 일 → Airflow 담당 또는 workload-access 후속
- 기존 Parquet 시험 결과(`silver/review_aspect_scores/`)의 이행·삭제

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. 모듈 → 스택 → `sql/` → README 순으로 작성한다
3. `terraform fmt` → `validate` → `plan` (destroy/replace 가 있으면 먼저 알린다)
4. 재영이 plan 확인 후 apply, 결과를 PR 에 첨부한다
5. apply 후 Terraform 이 만든 테이블을 Athena 에서 확인하고 `merge.sql` 을 샘플 1일치로 시험한다(문법 검증)
6. "완료 확인"을 실행하고 결과를 이 문서 맨 아래에 기록한다

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [x] `terraform fmt -check -recursive` (스택·모듈)
- [x] `terraform init -backend=false` 후 `terraform validate`
- [x] `terraform plan` → 첫 plan 은 6 create, 0 change, 0 destroy (초안 작성 시점)
- [x] apply 후 `terraform plan` 이 변경 없음 (2026-10-22 sagemaker·athena 두 스택 모두 "No changes" 확인)
- [ ] apply 후 SSM 파라미터 JSON 에 `workgroup`·`database`·`table_location`·`staging_location` 이 있고, 계정 ID·버킷 이름이 공유 설정 파일(`deployment.*`) 밖의 코드·문서에는 하드코딩돼 있지 않음 (`git grep`)
- [x] apply 로 만들어진 Iceberg 테이블·staging 테이블을 Athena 가 읽음(`SELECT`) (2026-10-22). 이후 plan 변경 없음 확인은 위 "apply 후 plan 이 변경 없음" 항목에서 계속
- [x] 샘플 staging 1일치로 `merge.sql` 2회 실행 → 두 번째는 행 수가 늘지 않음(멱등). 같은 날짜 Job 을 재실행해 staging 에 같은 키 193개가 2번씩(파일 2개) 있는 상태에서 `merge.sql` 이 오류 없이 반영, 테이블 193행·후기 100개·중복 0, `analyzed_at` 이 두 번째 실행 시각으로 갱신됨 (2026-10-22 확인)
- [x] 같은 날짜를 다른 `model_version`(`test-v`)으로 넣었을 때 행이 따로 쌓이고 `read_latest.sql` 이 최신 버전을 고름 (사용자 시험, 2026-10-22; 시험 행은 삭제함)
- [x] `optimize.sql`·`vacuum.sql` 이 오류 없이 실행되고 `read_latest.sql` 이 기대한 결과를 냄 (사용자 시험, 2026-10-22). 남은 확인: 테이블 속성에 `vacuum_*` 보존 기준이 보이지 않음(Glue 가 저장하지 않았을 수 있음) → 필요하면 `ALTER TABLE ... SET TBLPROPERTIES` 로 지정
- [ ] 쿼리당 스캔 한도(10GB)와 워크그룹 설정 강제가 적용됨(콘솔 확인)
- [ ] 뷰 `review_aspect_scores_latest` plan: 1 add(뷰) + SSM 설정 1 change, 삭제/교체 없음 (2026-10-22 plan 확인: 1 to add, 1 to change, 0 to destroy)
- [ ] apply 후 뷰 확인: `SELECT count(*)`, 버전별 후기 수, `WHERE review_date = ... LIMIT 5` 가 읽힘, `EXPLAIN` 으로 `review_date` 조건이 테이블 스캔까지 내려감(파티션 프루닝)
- [ ] 높은 번호 우선 읽기를 뷰로 재확인: 후기 3개에 `model_version_no = 2.0` 복사 행을 넣으면 뷰가 그 3개 후기는 2.0 행만 돌려줌, 시험 행은 삭제
- [x] (모델 번호·점수 로그·미점수 입력 변경 후) Terraform plan: 점수 로그 테이블·staging 로그 테이블 2 create, staging 점수 테이블·runner 정책·SSM 변경, 삭제/교체 없음 → apply 후 두 스택 "No changes" (2026-10-22)
- [x] `migrate_add_model_version_no.sql` 4문장 실행: 열 추가, 기존 행 `model_version_no = 1.0`, 비어 있는 행 0, 점수 로그 채우기 (사용자 시험, 2026-10-22; 로그 100행, 점수 테이블 `model_version_no = 1.0`)
- [x] 빠진 속성 삭제 시험: 한 후기에 가짜 속성 행을 넣고 `merge.sql` 재실행 → 가짜 행 삭제, 다른 후기 행은 그대로(행 수 불변) (사용자 시험, 2026-10-22)
- [x] `merge_log.sql` 실행 후 `review_score_log` 에 후기당 한 행(속성 0개 후기는 `n_aspects = 0`) (사용자 시험, 2026-10-22; 로그 100행)
- [x] 높은 모델 번호 시험: 같은 후기에 `model_version_no = 2.0` 행을 넣으면 `read_latest.sql` 이 2.0 행만 고름, 시험 행은 삭제 (사용자 시험, 2026-10-22; 시험 행 `test-v` 삭제됨)
- [x] `select_unscored.py` 시험: 전부 점수 있음(0건, Job 없음) / 일부만 점수 있음(로그 행 삭제 후 그 후기만 선택) / 속성 0개 후기가 다시 선택되지 않음 / 모델 번호를 올리면 전부 선택 (사용자 시험, 2026-10-22; 열 순서 주의: ADD COLUMNS 는 열을 맨 뒤에 붙임)

## README 갱신

- `infra/stacks/athena-review-score/README.md`, `infra/modules/athena-review-score/README.md` (작성함)
- `infra/README.md` 스택 표 (작성함), `docs/BRANCHES.md` 대장 한 줄 (작성함, 머지 때 상태 변경)

## 작업 결과 (머지 전에 작성한다. 사람과 AI가 나중에 이 브랜치가 무엇을 했는지 읽는 곳이다)

- **한 줄 요약:** (초안) 점수 결과를 Iceberg 테이블에 MERGE 로 반영하기 위한 Glue DB·Iceberg/staging 테이블·Athena 워크그룹·IAM 정책·SSM 설정과 SQL 템플릿.
- **무엇을 만들었나:** `infra/modules/athena-review-score/`, `infra/stacks/athena-review-score/` (+ `sql/`).
- **왜 그렇게 했나:** 파일 덮어쓰기(A)는 입력이 하루 전체여야 하고 늦은 후기마다 전체를 재점수화한다. Iceberg MERGE 는 행 단위 upsert 로 늦은 후기·정정·재점수화를 DB 서버 없이 처리한다.
  테이블은 Terraform 으로 만든다(Glue 테이블 리소스의 `open_table_format_input` 이 Iceberg 스키마·파티션 사양을 지원, 앞선 "Terraform 으로 불가" 설명은 정정). apply 검증 전이다(안 되면 Athena DDL 로 만드는 방식으로 바꾼다).
- **입력과 출력:** 입력 `staging/review-score/year=/month=/day=/scores_<model_version>_<실행시각>.parquet`(열에 `review_date` 포함, 실행마다 새 파일)(SageMaker Job 출력). 출력 Iceberg 테이블 `<database>.review_aspect_scores`(파티션 `review_date`).
  연동 값은 SSM `/clothes-query/dev/athena-review-score/config` 와 `runner_policy_arn` output.
- **확인한 결과:** fmt·validate 통과, 첫 plan 6 create / 0 change / 0 destroy. Athena 에서의 테이블 읽기·SQL 실행은 아직 하지 않았다.
- **추가된 결정(2026-10-22):** 빠진 속성 삭제, Gold 는 `model_version_no` 최대 결과 읽기(모델 번호 `model_version_no`("x.y", decimal(4,1)): 평가 모델/로직이 바뀌면 메이저를 올리고(0.0→1.0), 작은 수정·버그 수정이면 마이너를 올린다(0.0→0.1). 마이너는 0~9 까지이고 x.9 다음 변경은 메이저를 올린다. 현재 `2.4b_score_s2c` = `1.0`.), 매일 미점수 후기만 입력(점수 로그 `review_score_log` + `select_unscored.py`).
- **알려진 한계·남은 일:** SQL 실제 검증, SageMaker 출력 prefix 변경, Airflow 태스크, staging·결과 정리 정책(수명주기), 사라진 속성 처리, Gold 의 버전 선택 규칙, 타임스탬프 타입 확인.
