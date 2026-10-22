variable "aws_region" {
  description = "리전. 팀 기준 도쿄."
  type        = string
  default     = "ap-northeast-1"
}

variable "expected_account_id" {
  description = "공유 배포 설정 deployment.auto.tfvars.json 의 값(자동 로드). 잘못된 AWS 계정 사용을 막는다."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "승인된 팀 AWS 계정 ID(12자리)가 필요하다. deployment.auto.tfvars.json 을 확인한다."
  }
}

variable "state_bucket" {
  description = "팀 state 버킷(deployment.backend.hcl 의 bucket 과 같은 값). network/storage output 을 읽는 데 쓴다. 공유 배포 설정 deployment.auto.tfvars.json 에 있다."
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
  description = "점수화할 리뷰 prefix(읽기 전용). 결정(2026-10-22): Bronze 가 아니라 Silver 리뷰(silver/reviews, KST 작성일 파티션)."
  type        = string
  default     = "silver/reviews"
}

variable "work_prefix" {
  description = "모델(model/)·코드(code/)를 두는 prefix."
  type        = string
  default     = "review-score"
}

variable "output_prefix" {
  description = "점수 결과 prefix(쓰기 전용). 결정(2026-10-22): Iceberg MERGE 의 입력 staging. athena-review-score 스택의 staging_prefix 와 같아야 한다. staging/review-score/year=/month=/day=/scores_<model_version>_<실행시각>.parquet"
  type        = string
  default     = "staging/review-score"
}

variable "error_prefix" {
  description = "오류 파일 prefix(쓰기 전용). 결정: silver/review_aspect_scores_error/year=/month=/day=/"
  type        = string
  default     = "silver/review_aspect_scores_error"
}

variable "model_version" {
  description = "출력 열·파일명의 model_version(SSM 설정 기본값). 모델을 바꾸면 같이 바꾼다."
  type        = string
  default     = "2.4b_score_s2c"
}

variable "model_version_no" {
  description = "모델 번호 \"x.y\" 형식 문자열(model_version 이름과 1:1). 평가 모델/로직 변경은 메이저(0.0→1.0), 작은 수정은 마이너(0.0→0.1), 마이너는 0~9(x.9 다음은 메이저). Gold 는 가장 큰 번호를 읽는다. 현재 2.4b_score_s2c = 1.0."
  type        = string
  default     = "1.0"
}

variable "score_log_prefix" {
  description = "후기별 점수 로그 staging prefix(쓰기 전용). athena-review-score 스택의 staging_log_prefix 와 같아야 한다."
  type        = string
  default     = "staging/review-score-log"
}

variable "unscored_input_prefix" {
  description = "select_unscored.py 가 미점수 후기를 쓰는 입력 prefix(Job 읽기 전용)."
  type        = string
  default     = "staging/review-score-input"
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
