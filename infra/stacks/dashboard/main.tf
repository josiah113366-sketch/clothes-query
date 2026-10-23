# 대시보드(Streamlit) 이미지 저장소. 기존 ecr 스택(web/was/connect)과 state를 분리해 대시보드 담당이 독립적으로 관리한다.
# 정책은 ecr 스택과 같다: 태그 변경 불가(IMMUTABLE)라 push마다 새 태그를 쓰고, push 시 취약점 스캔, 삭제 보호.
resource "aws_ecr_repository" "dashboard" {
  name                 = "${var.name}/dashboard"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

# 후속(infra/platform/dashboard/README 참고): Athena/S3 읽기용 Pod Identity 역할(gold_a/·gold_b/ 읽기 전용, ground_truth/ 금지)은
# 실데이터 연결 때 이 스택에 추가한다. 지금은 저장소만 만든다.
