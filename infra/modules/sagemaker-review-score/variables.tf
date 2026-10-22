# 입력 변수. 스택(stacks/sagemaker-review-score)이 값을 넘긴다.
# 계정 ID·버킷 이름 같은 비공개 값은 이 파일에 기본값으로 두지 않는다(공개 저장소). 스택이 remote state 에서 받아 넘긴다.

variable "name" {
  description = "리소스 이름 접두사. 팀 규칙: clothes-query-<환경>-<용도>."
  type        = string
  default     = "clothes-query-dev-sagemaker-review-score"
}

variable "component" {
  description = "비용 할당 태그 Component 값. 예산 필터와, 스크립트가 만드는 Processing Job 의 태그가 같아야 한다."
  type        = string
  default     = "sagemaker-review-score"
}

variable "region" {
  description = "리전. 팀 기준은 도쿄(ap-northeast-1)."
  type        = string
  default     = "ap-northeast-1"
}

# ------------------------------------------------------------------ 네트워크 (network 스택 output)

variable "use_vpc" {
  description = <<-EOT
    true 면 Processing Job 을 VPC(app subnet)에서 실행한다. NAT 를 통해 pip install(PyPI)과 ECR 이미지 받기를 하고,
    S3 는 Gateway Endpoint 를 탄다. false 면 SageMaker 관리 네트워크(인터넷 직접)로 실행하며 SG·ENI 권한이 필요 없다.
  EOT
  type        = bool
  default     = true
}

variable "vpc_id" {
  description = "network 스택 output vpc_id. use_vpc=false 여도 값은 받되 쓰지 않는다."
  type        = string
}

variable "subnet_ids" {
  description = "network 스택 output app_subnet_ids. 스크립트가 NetworkConfig 에 넣는다(SSM 설정에 담김)."
  type        = list(string)
}

# ------------------------------------------------------------------ S3 (storage 스택 output)

variable "bucket_name" {
  description = "팀 데이터 버킷 이름(storage 스택 output). 민감 값이라 코드에 쓰지 않는다."
  type        = string
}

variable "bucket_arn" {
  description = "팀 데이터 버킷 ARN(storage 스택 output)."
  type        = string
}

variable "review_input_prefix" {
  description = <<-EOT
    점수화할 리뷰가 있는 prefix. 2026-10-22 결정: Bronze 가 아니라 Silver 리뷰를 읽는다. Silver 파이프라인(pipelines/silver/reviews.py)이 <이 값>/scopes/<시작일>_<종료일>/year=/month=/day=/part-00000.jsonl (KST 작성일)로 쓴다.
    역할은 이 아래 읽기만 한다. 정답 라벨(reviews_truth)·ground_truth·gold_b 는 일부러 권한을 주지 않는다.
  EOT
  type        = string
  default     = "silver/reviews"
}

variable "work_prefix" {
  description = <<-EOT
    모델·코드를 두는 작업 영역 prefix. 아래 두 곳을 쓴다(둘 다 역할은 읽기만).
      <work_prefix>/model/ : 합친 모델(upload_model.py 로 올림)
      <work_prefix>/code/  : score_batch.py
  EOT
  type        = string
  default     = "review-score"
}

variable "output_prefix" {
  description = <<-EOT
    점수 결과를 쓰는 prefix. 역할은 쓰기만. 2026-10-22 결정: 최종 테이블이 아니라 Iceberg MERGE 의 입력(staging)이다.
    athena-review-score 스택의 staging_prefix 와 같아야 한다(그 스택의 staging 테이블이 이 경로를 읽는다). model_version 은 경로가 아니라 스키마 열이다.
      <output_prefix>/year=YYYY/month=MM/day=DD/scores_<model_version>_<실행시각>.parquet  (날짜는 KST 후기 작성일)
    파일명에 실행시각이 들어가 같은 날짜를 다시 실행해도 파일이 겹치지 않고 쌓인다(중복은 MERGE 의 dedupe 가 처리).
  EOT
  type        = string
  default     = "staging/review-score"
}

variable "error_prefix" {
  description = "파싱 실패 등 오류 건을 쓰는 prefix. 역할은 쓰기만. <error_prefix>/year=/month=/day=/errors_<model_version>_<실행시각>.jsonl (실패가 있을 때만)"
  type        = string
  default     = "silver/review_aspect_scores_error"
}

variable "model_version" {
  description = "출력 열 model_version 과 파일명에 쓰는 모델 버전 이름(영문·숫자·._-). SSM 설정에 담겨 스크립트가 기본값으로 쓴다. 모델을 바꾸면 이 값도 바꾼다."
  type        = string
  default     = "2.4b_score_s2c"
  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.model_version))
    error_message = "model_version 은 영문·숫자·점·밑줄·하이픈만 쓸 수 있다."
  }
}

# ------------------------------------------------------------------ 컨테이너 이미지 (AWS 공개 Deep Learning Container)

variable "dlc_registry_account_id" {
  description = "AWS 가 운영하는 Deep Learning Container ECR 의 계정 ID(도쿄 포함 공개 값, 우리 계정이 아님)."
  type        = string
  default     = "763104351884"
}

variable "dlc_repository" {
  description = "DLC 저장소 이름."
  type        = string
  default     = "pytorch-training"
}

variable "dlc_image_tag" {
  description = "DLC 이미지 태그. 개인 계정 실측(1,000건 약 27분)에 쓴 것과 같다. 바꾸면 transformers 호환을 다시 확인한다."
  type        = string
  default     = "2.5.1-gpu-py311-cu124-ubuntu22.04-sagemaker"
}

# ------------------------------------------------------------------ 실행 옵션 (스크립트가 SSM 설정에서 읽는 기본값)

variable "instance_type" {
  description = "Processing Job 인스턴스. ml.g4dn.xlarge 는 시간당 약 0.994 USD(실측 기준, 1,000건 약 27분 ≒ 0.46 USD)."
  type        = string
  default     = "ml.g4dn.xlarge"
}

variable "volume_size_gb" {
  description = "인스턴스 EBS 크기(GB). 합친 모델 다운로드 + pip 설치분을 담는다."
  type        = number
  default     = 50
}

variable "max_runtime_seconds" {
  description = "비용 안전장치. 이 시간이 지나면 SageMaker 가 작업을 중단한다(StoppingCondition). IAM 으로는 강제할 수 없어 스크립트가 지킨다."
  type        = number
  default     = 3600
}

variable "job_name_prefix" {
  description = "Processing Job 이름 접두사. 실패 알림 규칙이 이 접두사로 이 작업만 골라낸다. 기존 run_processing_job.py 는 review-score-<시각> 을 쓴다."
  type        = string
  default     = "review-score"
}

variable "config_parameter_name" {
  description = "스크립트가 읽는 SSM 파라미터 이름. 다른 스택과 겹치지 않게 스택 이름을 넣는다."
  type        = string
  default     = "/clothes-query/dev/sagemaker-review-score/config"
}
