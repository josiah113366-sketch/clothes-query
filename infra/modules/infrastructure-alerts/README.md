# Infrastructure alerts

SNS 이메일 구독, 도쿄 RDS 표준 지표 경보 5개, Alertmanager 전용 SNS publish 역할과 Pod Identity만 관리한다. AWS Budget, CloudWatch Logs, DB/노드 변경, 데이터 쓰기 권한은 없다. [스택](../../stacks/infrastructure-alerts/README.md)에서 사용한다. 이메일은 비공개 변수로 공급한다.
