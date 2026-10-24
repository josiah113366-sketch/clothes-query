# 인프라 장애 알림

기존 network/EKS/RDS → 이 독립 스택 → 모니터링 Helm의 Alertmanager 순서다. state key는 infrastructure-alerts 전용이며 보류 중인 operations-alerts/Budget 작업과 분리한다. 기존 SNS/경보가 있으면 중복 생성하지 말고 먼저 소유권을 확인한다.

```powershell
terraform init -backend-config=deployment.backend.hcl
terraform plan -out=<Git-제외-plan>
```

개인 이메일은 Git 제외 `deployment.local.tfvars.json`의 email_recipients 배열로 공급한다. 이 이름은 Terraform이 자동으로 읽지 않으므로 `-var-file=deployment.local.tfvars.json`을 plan에 명시한다. 비밀/이메일/state/plan은 커밋하지 않는다. 공통 식별자는 deployment.auto.tfvars.json을 사용한다.

경보: 여유 디스크 <5GiB 10분/<2GiB 5분, WAL instance lag ≥예산 75% 2분 또는 해당 지표 누락, CPU >80% 15분, 여유 메모리 <256MiB 10분. WAL 경보는 실제 slot invalidation을 직접 감지하지 않는다. 알림과 정상 복귀 통보만 하며 자동 재시작·용량 변경·slot 삭제는 없다.

이메일은 SNS 확인 메일의 Confirm subscription을 수신자가 눌러야 실제 경보를 받는다. 배포만으로 확인 완료라고 보고하지 않는다. 수신 확인 후 합성 테스트 경보는 업무 데이터 없이 Alertmanager API로 발송할 수 있다.

삭제 시 이메일·경보·전달 역할이 사라지므로 먼저 monitoring Helm의 alertmanager.enabled를 끄고, SNS에 다른 구독/사용자가 없는지 확인한다. 업무 DB/노드/데이터는 이 state에 없다. 표준 CloudWatch 경보 5개 및 SNS 사용량에 소액 과금이 추가된다. 신규 노드나 CloudWatch Logs는 만들지 않는다.
