# Bronze v2 지연 수집기

main의 Python 수집기를 상시 Pod 1개, --interval 60으로 실행한다. Spark는 사용하지 않는다. 대상은 bronze-s3-sink-v2 및 connect-bronze-s3-sink-v2이며 5개 업무 토픽을 고정한다. 결과는 기존 gold_b.bronze_lag_snapshots 표의 경로로 쓴다. 상시 적재 Spark 잡과 별개다.

Dockerfile은 저장소 루트를 context로 쓰며 .dockerignore allowlist로 collector Python과 고정 requirements만 포함한다. .env·시드·자격증명·다른 업무 코드를 포함하지 않는다. linux/amd64의 고정 digest를 발행한 뒤 render.py --image <ECR@sha256:...> --output <Git 제외 JSON>으로 준비한다. --image가 없으면 KafkaUser와 추가 NetworkPolicy만 렌더한다.

AWS는 ../../stacks/bronze-lag-collector에서 ECR·쓰기 전용 S3 역할·Pod Identity를 관리한다. 기존 workload-access map을 변경하지 않는다. Kubernetes는 pipelines의 전용 ServiceAccount와 Kafka namespace의 mTLS 사용자·수집기 라벨만 허용하는 9093/8083 네트워크 경로를 쓴다. 기존 Kafka/Connect CR·listener·broker 설정은 바꾸지 않는다.

Strimzi가 만든 KafkaUser Secret의 user.crt/user.key와 cluster CA의 ca.crt를 pipelines/gold-b-lag-collector-tls에 비공개 복사한다. 원본과 복사본의 해시/인증서 만료를 운영 기록으로 확인한다. 인증서 갱신 시 복사·Pod 재시작이 필요하며 자동 mirror controller는 설치하지 않는다. 실제 Secret·Helm values·접속 설정 렌더는 Git에 올리지 않는다.

기존 API 노드풀 여유를 확인한 뒤 requests 25m/128Mi, limits 250m/384Mi로 시작한다. Recreate라 배포 시 중복 수집기를 만들지 않는다. K8s Running/Ready만으로 신선도를 보장하지 않으며 최근 S3 행과 R3의 측정 누락 판단으로 확인한다. 실패 회차는 새 파일이 없고 다음 60초 회차에 재시도한다. 실제 자원은 측정 후 조정한다.

검증은 최근 1~2분 안의 collected_at과 RUNNING 상태를 S3 Parquet 및 Athena에서 확인하고 노드·브로커 UID/재시작이 그대로인지 대조한다. 측정 기록은 실제 운영 관측 데이터이며 더미 업무 이벤트를 만들지 않는다. 안전한 중지는 이 전용 Deployment를 0으로 내리는 방식이며 기존 Sink·offset·S3 장부를 삭제하지 않는다.
