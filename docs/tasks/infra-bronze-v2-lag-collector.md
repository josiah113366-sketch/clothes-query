# Bronze v2 지연 수집기 배포

상태: 준비 중

브랜치: infra/bronze-v2-lag-collector

사용자가 측정 대상으로 v2를 지정했다. main 3a4e17c 기준 기존 collector 코드를 수정하지 않고 이미지·권한·네트워크·Pod 배포를 준비한다. Spark·새 노드는 만들지 않는다. 기존 API 노드의 예약 여유 680m/1331Mi를 확인했으며 수집기 요청은 25m/128Mi다.

전용 ECR·Pod Identity/S3 역할을 독립 Terraform key에서 관리한다. KafkaUser는 토픽 Read/Describe 및 v2 Sink 그룹 Describe만 허용해 Sink 처리 위치를 바꿀 수 없게 한다. 수집기 라벨/namespace만 기존 broker 9093 및 Connect 8083에 접근할 수 있게 추가 NetworkPolicy로 연결한다. broker/Connect CR은 변경하지 않아 재시작을 피한다.

## 작업 결과

렌더/권한 경계 검사 4개와 Terraform mock 1개, validate를 통과했다. 실제 plan은 ECR·IAM 역할·쓰기 정책·Pod Identity 4개 create뿐이었고 삭제·교체는 없다. 공용 provider 캐시를 재사용해 init했다.

승인된 v2 연결 범위에서 해당 저장 계획과 전용 KafkaUser/추가 NetworkPolicy 3개를 서버 dry-run 후 적용했다. 기존 Kafka/Connect CR은 변경하지 않았다. 사용자 Ready·생성 TLS Secret의 pipelines 복사 일치와 적용 후 Terraform 변경 없음을 확인했다. 인증서/키는 출력하거나 Git에 넣지 않았다.

이미지 빌드·실행·최근 측정 검증은 이어서 기록한다. Git push·PR·승인·머지는 별도 요청 전 하지 않는다.
