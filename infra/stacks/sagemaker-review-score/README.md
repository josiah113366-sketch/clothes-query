# sagemaker-review-score stack

리뷰 점수화(`review-analysis/`의 s2c 합친 모델)를 하루 1회 SageMaker Processing Job 으로 돌리기 위한 AWS 기반. 담당: lemin 이 작성하고,
apply 는 인프라 담당(재영)이 plan 을 확인한 뒤 실행한다. 모듈은 [modules/sagemaker-review-score](../../modules/sagemaker-review-score/README.md),
실행 스크립트는 `review-analysis/deploy/`(`run_processing_job.py` 등).

- 선행: bootstrap(state 버킷), network(VPC·app subnet·NAT·S3 endpoint), storage(데이터 버킷). 두 스택 output 을 remote state 로 읽는다.
- backend key: `clothes-query/dev/sagemaker-review-score/terraform.tfstate`.
- 만드는 것(9개): Job 실행 IAM 역할 + 정책 4개(S3, CloudWatch, ECR(AWS 공개 이미지), VPC ENI), 보안 그룹(나가는 443 만) + 규칙,
  스크립트용 SSM 파라미터, Airflow 가 붙일 `launcher` IAM 정책(어떤 역할에도 자동으로 붙지 않음).
- 만들지 않는 것: Processing Job(Airflow 태스크가 호출마다 생성), 스케줄(실행은 Airflow silver DAG 종료 신호 기반), 이메일 알림·월 예산(2026-10-21 요청으로 제외), 버킷·VPC, 모델/코드 업로드.
- 권한 요약: 읽기 `silver/reviews/*`(Silver 리뷰, Bronze 아님)·`review-score/model/*`·`review-score/code/*`, 쓰기 `silver/review_aspect_scores/*`·`silver/review_aspect_scores_error/*` 뿐.
  `reviews_truth/`·`ground_truth/`·`gold_b/` 접근 불가.
- 결과 위치(결정, 2026-10-22): 점수 `s3://<버킷>/silver/review_aspect_scores/year=YYYY/month=MM/day=DD/scores_<model_version>.parquet` (날짜는 KST 후기 작성일, `model_version` 은 경로가 아니라 CSV 열),
  오류 `s3://<버킷>/silver/review_aspect_scores_error/year=/month=/day=/errors_<model_version>.jsonl`.
  **파티션은 실행한 날이 아니라 후기의 작성일(KST)** 이다. `score_batch.py` 가 후기 행의 `review_date_kst`(없으면 `created_at_kst`, `created_at`)를 읽어 각 후기를 자기 작성일 폴더에 나눠 쓰므로, 입력 파일에 여러 날짜가 섞여 있어도 날짜별로 알맞은 파티션에 들어간다.
  작성일을 알 수 없는 후기는 `--date`(없으면 입력 키의 `year=/month=/day=`)를 쓰고, 그것도 없으면 점수를 매기지 않고 오류 경로의 `no_review_date/` 에 남긴다. 실행 요약은 결과 경로 맨 위의 `_summary_scores_<model_version>_<실행시각>.json` 이다.
  주의: 날짜별 파일은 그 실행에서 처리한 후기만 담는다. 같은 날짜·같은 `model_version` 을 일부 후기만 담은 입력으로 다시 쓰면 그 날짜 파일이 그 후기들만으로 바뀐다(입력은 하루치 전체여야 한다).
  같은 날짜·같은 `model_version` 으로 다시 실행하면 **그 파일만 덮어쓴다**(파티션 덮어쓰기 방식, DB·테이블 포맷 없음). 다른 버전 파일은 남고, 버킷 버저닝으로 이전 내용도 남는다.
  Parquet 열: `review_id`(string), `aspect`(string), `score`(int32), `model_version`(string), `analyzed_at`(timestamp, UTC). 요약은 같은 폴더의 `_summary_scores_<model_version>.json`(`_` 로 시작해 Spark/Athena 가 데이터로 읽지 않음).
- 비용: 만들어 두기만 하면 0. 실행 비용은 Job 시간만큼: ml.g4dn.xlarge 시간당 약 0.994 USD, 1,000건 약 27분 ≒ 0.46 USD/회(개인 계정 실측). 유휴 비용 없음.
- 출력: `role_arn`, `role_name`, `security_group_id`, `config_parameter_name`, `image_uri`, `launcher_policy_arn`.

## 실행

비공개 입력은 Git 제외 파일에만 둔다 (`deployment.backend.hcl`, `deployment.local.tfvars`).

```powershell
cd infra/stacks/sagemaker-review-score
# 비공개 파일 2개 (커밋 안 됨): deployment.backend.hcl (bucket, region), deployment.local.tfvars (terraform.tfvars.example 복사)
$env:TF_VAR_expected_account_id = "<계정 ID>"

terraform init -backend=false -lockfile=readonly   # 정적 검사
terraform fmt -check
terraform validate

terraform init --backend-config=deployment.backend.hcl -lockfile=readonly
terraform plan -input=false -var-file=deployment.local.tfvars -out=sagemaker-review-score.tfplan
terraform apply sagemaker-review-score.tfplan      # plan 을 확인한 담당자가 실행
```

첫 plan 은 모두 create 여야 한다(다른 스택 리소스를 바꾸지 않음). destroy/replace 가 보이면 멈추고 확인한다.

## GPU 할당량 확인 (apply 전에 팀 계정에서)

Processing Job 은 인스턴스 타입별 "processing job usage" 쿼터를 쓴다. 새 계정은 0 일 수 있다.

```powershell
# 현재 값 조회 (읽기 전용, servicequotas:ListServiceQuotas 권한 필요)
aws service-quotas list-service-quotas --service-code sagemaker --region ap-northeast-1 `
  --query "Quotas[?contains(QuotaName,'ml.g4dn.xlarge for processing job usage')].[QuotaName,Value,QuotaCode,Adjustable]" --output table

# 0 이면 증설 요청 (QuotaCode 는 위 조회 결과의 값을 쓴다). 승인에 시간이 걸릴 수 있다.
aws service-quotas request-service-quota-increase --service-code sagemaker --region ap-northeast-1 `
  --quota-code <QuotaCode> --desired-value 1

# 요청 상태 확인
aws service-quotas list-requested-service-quota-change-history-by-quota --service-code sagemaker `
  --region ap-northeast-1 --quota-code <QuotaCode> --query "RequestedQuotas[].[Status,DesiredValue,Created]" --output table
```

권한이 없으면 콘솔 Service Quotas > Amazon SageMaker 에서 같은 이름으로 검색한다. 증설 요청은 계정 설정 변경이라 인프라 담당(재영)과 확인 후 진행한다.

## apply 후 사용 순서

1. 모델 업로드: `upload_model.py --uri s3://<버킷>/review-score/model/2.4b_score_s2c/` (`--dry-run` 먼저). `score_batch.py` 는 `review-score/code/` 에 올린다.
2. Airflow 역할에 `launcher_policy_arn` 정책을 붙인다(이 스택 밖 작업: workload-access 또는 Airflow 담당).
3. silver DAG 종료 후 실행하는 Airflow 태스크가 SSM 파라미터(`config_parameter_name` output)를 읽어 `role_arn`, `image_uri`, `network`, `tags`, `output_prefix`, `error_prefix` 로 Job 을 만든다.
   `run_processing_job.py` 를 팀 계정용(SSM 설정 읽기, `tags`·`network` 적용)으로 바꿔 두었다. Airflow 태스크는 이 스크립트의 `build_request` 를 재사용하거나 같은 방식으로 만든다.
4. 오류 기록: Processing Job 의 S3 출력은 `output/` 하나만 설정할 수 있다. `error/` 로 보내려면 `score_batch.py` 가 오류 목록을 `error_prefix` 로 직접 PutObject 하거나, Airflow 가 실패 시 summary 를 `error/` 로 복사한다(역할에 쓰기 권한은 있음).

## 수동 실행 (Airflow 없이 로컬 PC 에서 SageMaker Processing Job 시작)

로컬 PC 에서 명령 한 번으로 팀 계정에 Processing Job 을 요청한다. 계산은 PC 가 아니라 AWS 의 GPU 인스턴스(`ml.g4dn.xlarge`)에서 돌고, PC 는 요청을 보내고 상태를 기다릴 뿐이다.
Job 은 Terraform 이 아니라 API 호출로 만든다. 정식 하루 1회 실행은 Airflow 가 같은 방식으로 한다.

### 흐름

1. `run_processing_job.py` 가 SSM 파라미터(`config_parameter_name` output)에서 역할·이미지·서브넷·SG·태그·S3 경로를 읽는다.
2. `CreateProcessingJob` 으로 Job `review-score-<날짜-시각>` 을 요청한다.
3. SageMaker 가 GPU 인스턴스를 띄우고 S3 의 모델(`review-score/model/2.4b_score_s2c/`)·코드(`review-score/code/score_batch.py`)·입력 파일을 내려받는다.
4. 컨테이너에서 `pip install transformers==4.53.3 accelerate` 후 `score_batch.py` 를 실행한다.
5. 끝나면 결과를 `silver/review_aspect_scores/year=/month=/day=/` 에, 오류를 `..._error/` 같은 날짜 경로에 올리고 인스턴스가 사라진다(실행 시간만큼만 과금).

### 사전 조건 (모두 확인 후 실행)

| 항목 | 확인 방법 |
|---|---|
| 팀 계정 자격증명 | `aws sts get-caller-identity` 가 팀 계정인지 (키는 직접 설정, 채팅·파일에 적지 않는다) |
| 스택 apply 완료 | `terraform plan` 이 변경 없음, SSM 파라미터가 읽힘 (아래 참고) |
| 모델·코드가 S3 에 있음 | `upload_model.py`(모델), `aws s3 cp deploy/score_batch.py s3://<버킷>/review-score/code/score_batch.py`(코드) |
| GPU 쿼터 1 이상 | 위 "GPU 할당량 확인". 0 이면 Job 이 `ResourceLimitExceeded` 로 시작하지 못한다 |
| 권한 | `launcher_policy_arn` 과 같은 권한: Job 생성/조회/중지(`review-score-*`), 실행 역할 `iam:PassRole`, SSM 읽기 |
| 입력 파일 | `score_batch.py` 는 **파일 하나**(Silver 리뷰 `part-00000.jsonl` 등, `review_id`·`text` 필드)만 읽는다. S3 키로 지정 |
| 환경 | Python 3 + `boto3` (GPU/torch 불필요) |

```powershell
# SSM 설정 읽기 확인 (Git Bash 에서는 앞에 MSYS_NO_PATHCONV=1 이 필요하다. '/'로 시작하는 값이 Windows 경로로 바뀌기 때문)
aws ssm get-parameter --name /clothes-query/dev/sagemaker-review-score/config --region ap-northeast-1 --query "Parameter.Value" --output text

# 입력 파일 존재 확인
aws s3 ls s3://<버킷>/silver/reviews/scopes/ --recursive | findstr part-00000   # Silver 리뷰 파일 키 찾기
```

### 실행

```powershell
cd review-analysis

# 1) 요청 내용만 출력 (Job 을 만들지 않음, 과금 없음). 역할·이미지·입력/출력 경로·서브넷이 맞는지 본다
python deploy/run_processing_job.py --input-key silver/reviews/scopes/<시작일>_<종료일>/year=2026/month=10/day=20/part-00000.jsonl --dry-run

# 2) 실제 실행 (여기서부터 과금). --wait 면 30초마다 상태를 출력하고 끝나면 실행 시간을 알려 준다
python deploy/run_processing_job.py --input-key silver/reviews/scopes/<시작일>_<종료일>/year=2026/month=10/day=20/part-00000.jsonl --wait
```

| 옵션 | 설명 |
|---|---|
| `--input-key` (필수) | 버킷 안의 후기 파일 키 |
| `--dry-run` | 요청 내용만 출력, Job 생성 안 함 |
| `--wait` | 끝날 때까지 상태 출력(Ctrl+C 로 멈춰도 Job 은 계속 돈다) |
| `--instance` | 인스턴스 타입 덮어쓰기(기본은 SSM 설정의 `ml.g4dn.xlarge`) |
| `--max-seconds` | 최대 실행 시간 덮어쓰기(기본 SSM 설정의 3600초, 넘으면 SageMaker 가 중단) |
| `--ssm-name`, `--region` | 설정 파라미터 이름, 리전(기본값은 이 스택 값) |

처음에는 **100건 정도의 작은 파일**로 시험한다. 1,000건 기준 약 27분, 약 0.46 USD(개인 계정 실측)이다. 시작 시간(인스턴스 준비, 모델 다운로드, pip 설치)이 몇 분 더 든다.

### 상태·로그·중지

콘솔 SageMaker > Processing jobs 에서도 볼 수 있다.

```bash
aws sagemaker describe-processing-job --processing-job-name <Job 이름> --region ap-northeast-1 --query "[ProcessingJobStatus,FailureReason]"
aws logs tail /aws/sagemaker/ProcessingJobs --log-stream-name-prefix <Job 이름> --follow --region ap-northeast-1
aws sagemaker stop-processing-job --processing-job-name <Job 이름> --region ap-northeast-1
```

### 결과 확인

```bash
aws s3 ls s3://<버킷>/silver/review_aspect_scores/year=2026/month=10/day=20/
aws s3 cp s3://<버킷>/silver/review_aspect_scores/year=2026/month=10/day=20/scores_2.4b_score_s2c.parquet .
# 내용 확인(로컬): python -c "import pyarrow.parquet as pq; print(pq.read_table('scores_2.4b_score_s2c.parquet').to_pandas().head())"  (pandas 필요) 또는 pq.read_table(...).to_pylist()[:5]
```

- `scores_<model_version>.parquet` 는 `review_id,aspect,score,model_version,analyzed_at`(속성별 한 행, 점수 -2~2)이고 `_summary_scores_<model_version>.json` 에 건수와 실패 목록이 있다(같은 폴더, `_` 로 시작해 데이터로 읽히지 않는다). 컨테이너는 시작 때 `pip install pyarrow` 를 한다.
- 파싱에 실패한 후기는 `silver/review_aspect_scores_error/year=/month=/day=/errors_<model_version>.jsonl` 에 쓴다(실패가 없어도 빈 파일을 써서 이전 실행 결과를 지운다).

### 자주 나는 문제

| 증상 | 원인·조치 |
|---|---|
| `ParameterNotFound` | 스택이 apply 되지 않았거나 다른 계정/리전. Git Bash 면 `MSYS_NO_PATHCONV=1` 누락도 원인 |
| `AccessDenied` ... `iam:PassRole` / `CreateProcessingJob` | 실행하는 사람에게 `launcher_policy_arn` 정책(또는 같은 권한)이 없음 |
| `ResourceLimitExceeded` | `ml.g4dn.xlarge for processing job usage` 쿼터 0. 증설 요청 후 승인 대기 |
| Job 이 `Failed`: 입력/모델을 찾을 수 없음 | 모델·코드·입력 S3 경로 확인(`aws s3 ls`). 모델 폴더 이름은 `2.4b_score_s2c` |
| Job 이 `Failed`: `pip` 오류 | VPC 실행이라 NAT 를 거쳐 PyPI 에 나간다. NAT/보안 그룹(나가는 443) 확인 |
| `CapacityError` | 해당 AZ 에 GPU 인스턴스 여유 없음. 잠시 후 재시도 |
| `Stopped` (`MaxRuntimeExceeded`) | 3600초 초과. 입력을 줄이거나 `--max-seconds` 를 늘림 |

## 열린 질문 (결정 필요)

1. **입력 모으기**: 입력이 `year=/month=/day=` 파티션 여러 파일이고 `score_batch.py` 는 파일 하나만 읽는다. Airflow 태스크가 날짜를 정해 입력 prefix 를 넘기고, `score_batch.py` 가 prefix 의 JSONL 여러 개를 읽도록 바꿔야 한다(`review-analysis` 영역, 별도 PR).
2. **재점수화 정책**: 같은 날짜를 다른 `model_version` 으로 다시 점수화하면 파일이 따로 쌓인다. 소비 쪽(Gold)이 어느 버전을 쓸지 정해야 한다.
3. **GPU 쿼터**: 위 명령으로 확인 필요(자격증명에 조회 권한이 없어 확인하지 못함).
4. **로그 그룹**: Job 로그는 계정 공용 `/aws/sagemaker/ProcessingJobs`(보존 기간 무기한)에 쌓인다. Terraform 으로 만들지 않았다.

## 삭제 및 운영 주의

- 이 스택에는 데이터가 없어 destroy 가 안전하다(버킷·모델은 storage 스택/업로드 스크립트 몫이라 영향 없음).
- 비용 추적용 `Component` 태그는 결제 콘솔에서 비용 할당 태그로 활성화해야 Cost Explorer 에서 필터할 수 있다.
