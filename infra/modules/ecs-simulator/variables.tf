variable "name" {
  description = "리소스 이름 접두사 (clothes-query-<환경>-<용도>)."
  type        = string
  default     = "clothes-query-dev-ecs-simulator"
}

variable "region" {
  type = string
}

variable "vpc_id" {
  description = "팀 VPC (network 스택 출력)."
  type        = string
}

variable "subnet_ids" {
  description = "Fargate 태스크를 띄울 private app 서브넷 (network 스택 app_subnet_ids). 밖으로는 공용 NAT로 나간다."
  type        = list(string)
}

variable "bucket_name" {
  description = "팀 데이터 레이크 버킷 (storage 스택 출력). 컨트롤러 정답표는 ground_truth/incident_log/ 에 쓴다."
  type        = string
  sensitive   = true
}

variable "bucket_arn" {
  type      = string
  sensitive = true
}

variable "image_digest" {
  description = "이 스택 ECR에 올린 시뮬레이터 이미지 digest (sha256:...). 비우면 기반만 만든다(태스크 정의·서비스 없음)."
  type        = string
  default     = ""
  validation {
    condition     = var.image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest 는 비워 두거나 sha256:<16진수 64자리> 여야 합니다."
  }
}

variable "api_url" {
  description = "내부 ALB를 거치는 업무 API 주소 (http://internal-...). 엔드포인트라 비공개 입력으로 준다."
  type        = string
  default     = ""
  sensitive   = true
}

variable "desired_count" {
  description = "실행할 시뮬레이터 태스크 수. 1 = 켬, 0 = 멈춤. 2 이상은 안 된다(트래픽과 정답표가 겹친다)."
  type        = number
  default     = 1
  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count 는 0 또는 1 이어야 합니다."
  }
}

variable "cpu" {
  description = "Fargate 태스크 CPU 단위 (컨테이너 3개 합계)."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate 태스크 메모리 MiB (컨테이너 3개 합계)."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "keep_images" {
  description = "ECR에 남길 이미지 수."
  type        = number
  default     = 10
}
