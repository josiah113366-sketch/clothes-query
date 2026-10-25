variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "name" {
  description = "Resource name prefix shared with the other dev stacks."
  type        = string
  default     = "clothes-query-dev"
}
variable "expected_account_id" {
  description = "Approved AWS account ID; prevents use of the wrong AWS account. Shared via deployment.auto.tfvars.json."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Provide the approved AWS account ID."
  }
}
variable "github_repository" {
  description = "GitHub owner/repo whose main-branch workflows may push dashboard images (github-actions.tf)."
  type        = string
  default     = "josiah113366-sketch/clothes-query"
}
variable "github_sub_prefix" {
  # GitHub OIDC 토큰 sub 의 접두어. 저장소가 immutable subject 를 쓰면 소유자·저장소 이름 뒤에 숫자 ID 가 붙는다.
  # 확인: gh api repos/josiah113366-sketch/clothes-query/actions/oidc/customization/sub 의 sub_claim_prefix
  description = "OIDC sub claim prefix of the repository (sub_claim_prefix from the GitHub OIDC customization API)."
  type        = string
  default     = "repo:josiah113366-sketch@307806325/clothes-query@1410004963"
}
variable "create_github_oidc_provider" {
  # 2026-10-24: 이 계정에는 GitHub OIDC 공급자가 이미 있다 (apply 시 EntityAlreadyExists). 그래서 기본은 기존 것을 읽어 쓴다.
  # 새 계정처럼 공급자가 없을 때만 true 로 바꾼다.
  description = "Create the account-wide GitHub OIDC provider. Keep false when it already exists in this AWS account."
  type        = bool
  default     = false
}
