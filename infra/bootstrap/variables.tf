variable "aws_region" {
  description = "state 버킷을 만들 리전"
  type        = string
  default     = "ap-northeast-1"
}

variable "project" {
  description = "프로젝트 이름. 버킷 이름과 태그에 쓴다"
  type        = string
  default     = "clothes-query"
}
