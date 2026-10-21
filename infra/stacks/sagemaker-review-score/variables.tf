variable "aws_region" {
  description = "리전. 팀 기준 도쿄."
  type        = string
  default     = "ap-northeast-1"
}

variable "expected_account_id" {
  description = "TF_VAR_expected_account_id 로 비공개로 넘긴다. 잘못된 AWS 계정 사용을 막는다."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "승인된 팀 AWS 계정 ID(12자리)를 비공개로 넘겨야 한다."
  }
}

variable "state_bucket" {
  description = "팀 state 버킷(deployment.backend.hcl 의 bucket 과 같은 값). network/storage output 을 읽는 데 쓴다. 비공개 tfvars 에만 둔다."
  type        = string
  sensitive   = true
}

variable "state_region" {
  description = "state 버킷 리전."
  type        = string
  default     = "ap-northeast-1"
}

variable "use_vpc" {
  description = "true: Job 을 app subnet(NAT 경유)에서 실행. false: SageMaker 관리 네트워크(인터넷 직접). 모듈 변수 설명 참고."
  type        = bool
  default     = true
}

variable "review_input_prefix" {
  description = "점수화할 리뷰 prefix(읽기 전용). 리뷰 시뮬레이터가 year=/month=/day= 파티션으로 쓰는 곳."
  type        = string
  default     = "bronze/reviews"
}

variable "work_prefix" {
  description = "모델(model/)·코드(code/)를 두는 prefix."
  type        = string
  default     = "review-score"
}

variable "output_prefix" {
  description = "점수 결과 prefix(쓰기 전용). 결정: silver/review-score/output"
  type        = string
  default     = "silver/review-score/output"
}

variable "error_prefix" {
  description = "오류 파일 prefix(쓰기 전용). 결정: silver/review-score/error"
  type        = string
  default     = "silver/review-score/error"
}

variable "instance_type" {
  description = "Processing Job 인스턴스 타입(SSM 설정의 기본값). 실측: ml.g4dn.xlarge 1,000건 약 27분."
  type        = string
  default     = "ml.g4dn.xlarge"
}

variable "max_runtime_seconds" {
  description = "Job 최대 실행 시간(초). 스크립트가 StoppingCondition 에 넣는 비용 안전장치."
  type        = number
  default     = 3600
}
