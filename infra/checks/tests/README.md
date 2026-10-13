# 검사기 단위 검사

`python -m unittest discover -s infra/checks/tests -v`로 Terraform 검사기의 mock·provider·module 제한과 환경 격리를 확인한다. AWS에 연결하지 않으며 실제 인프라 배포 검증은 아니다.
