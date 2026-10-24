# Bronze v2 지연 수집기 AWS 접근

독립 ECR·Pod Identity 역할만 만든다. pipelines/gold-b-lag-collector가 gold_b/bronze_lag_snapshots/에 PutObject할 수 있고 객체 읽기·삭제·다른 장부/정답표 접근은 추가하지 않는다. Kafka 인증/ACL·네트워크 및 실제 실행은 platform/bronze-lag-collector에서 별도로 관리한다.
