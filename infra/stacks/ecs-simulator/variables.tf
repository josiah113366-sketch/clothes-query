variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "expected_account_id" {
  description = "TF_VAR_expected_account_id 로 비공개로 준다. 다른 AWS 계정에 잘못 적용하는 것을 막는다."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "승인된 AWS 계정 ID(12자리)를 비공개로 넣어야 합니다."
  }
}
variable "state_bucket" {
  description = "팀 state 버킷 (deployment.backend.hcl 과 같은 값). network·storage 출력을 읽는 데 쓴다."
  type        = string
  sensitive   = true
}
variable "state_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "image_digest" {
  description = "push 한 시뮬레이터 이미지의 sha256:... . 첫 apply(기반만)에서는 비운다."
  type        = string
  default     = ""
}
variable "api_url" {
  description = "업무 API 내부 ALB 주소. 엔드포인트라 deployment.local.tfvars(.json) 에 넣는다."
  type        = string
  default     = ""
  sensitive   = true
}
variable "desired_count" {
  type    = number
  default = 1
}
