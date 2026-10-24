# 도쿄 비용 예산

기존 RDS/Prometheus 장애 알림과 별개로 AWS Budgets 예산 3개를 만든다. 모두 도쿄 월 $200을 관측하며 알림 5개 제한을 나누기 위한 구성이므로 $600 예산을 뜻하지 않는다. 실비 10~100%를 10% 단위로, 월말 예상 100%를 별도로 알린다.

옛 `operations-alerts` 초안은 RDS 경보도 만들기 때문에 함께 적용하지 않는다. 이 스택은 SNS·CloudWatch 경보·EC2를 추가하지 않는다.

실행 전에 월 USD 기준 금액을 확정하고 공유 `deployment.auto.tfvars.json`의 `monthly_budget_usd`에 기록한다. 수신자는 기존 `infrastructure-alerts`와 같은 값으로 Git 제외 `deployment.local.tfvars.json`의 `email_recipients`에 저장한다. 이메일·state·plan은 공개하지 않는다.

```powershell
terraform init -backend-config=deployment.backend.hcl
terraform plan -var-file=deployment.local.tfvars.json -out=<Git-제외-plan>
```

plan이 Budget 3개 추가뿐이며 기존 자원 변경·삭제가 없는지 확인한다. 적용 뒤 재계획에서 변경 없음을 확인하고 Budgets API에서 도쿄 필터·금액·알림 총 11개·수신자 일치를 대조한다. API의 수신자는 화면·로그에 출력하지 않는다.

AWS Budgets는 글로벌 과금 서비스이며 API 조회에는 us-east-1 endpoint를 사용할 수 있다. 집계 대상은 ap-northeast-1뿐이다. 알림은 집계 지연이 있어 실시간 경보가 아니다. 이메일 도착 확인과 설정 일치 확인은 구분해 기록한다. Budget Action이나 자동 종료는 설정하지 않는다.

[입력·집계 기준](../../modules/cost-budget/README.md)을 따른다. [AWS 요금 안내](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/) 기준 일반 예산 감시·알림은 무료다. 유료 정기 Budget Reports는 설정하지 않는다.
