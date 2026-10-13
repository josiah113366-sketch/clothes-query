# 로컬 CDC 연결 검사

Python 표준 라이브러리와 Docker Desktop Linux/Compose로 임시 PostgreSQL 16·Kafka 4.3.1·Connect/Debezium 3.7.0.Final을 실행한다. PostgreSQL 공식 이미지와 Kafka 기반 이미지는 digest 고정이다. 테스트 데이터는 ID/value 정수뿐이며 사용자·상품·업무 스키마를 사용하지 않는다.

저장소 루트에서 실행:

```powershell
python -X utf8 infra/platform/kafka/local-smoke/check.py
```

검사 범위는 플러그인 발견, 전용 replication 계정(비 superuser), 실제 Secret 디렉터리 참조, 초기 snapshot, insert/update/delete envelope, Connect 중단 중 발생한 변경의 재시작 후 전달, 캡처 범위 밖 테이블의 토픽 미생성이다. 전달 중복은 허용하며 exactly-once를 주장하지 않는다.

Kafka 데이터 경로는 임시 CA의 mTLS·hostname 검증과 StandardAuthorizer ACL을 사용한다. Connect는 허용 토픽에 쓰고 reader는 허용 토픽/group을 읽는다. 인증서 없음·다른 CA 인증서·권한 없는 토픽/group을 실제 오류 종류로 구분해 거부되는지 검사한다. CA 개인 키는 workload에 mount하지 않는다. 인증서 발급 스크립트는 bytes stdin으로 전달해 Windows에서도 Linux 줄바꿈을 유지한다.

Kafka의 KRaft/log는 실행별 named volume에 둔다. Connect 정지 후 Kafka를 force-recreate해 새 container ID/같은 volume, 보존된 메시지 end offset과 Connect source offset을 확인한다. Connector config를 다시 등록하지 않고 재시작해 중단 중 추가한 행이 초기 snapshot 대신 변경 이벤트로 전달되는지 검사한다. 로컬 volume 초기화 컨테이너는 해당 실행의 volume에서만 Kafka UID 소유권을 맞춘다. 다른 volume/host 경로는 수정하지 않는다.

[chart와 같은 지표 규칙](../metrics/README.md)을 agent로 읽어 Kafka 복제/controller·Connect task/CDC 연결 상태와 실제 backlog의 consumer lag 노출도 검사한다. exporter 추가 메모리 상한은 256Mi다. Prometheus 서버는 실행하지 않는다.

2026-10-14 이 PC에서 전체 검사와 해당 project 정리를 완료했다. 짧은 그룹 할당 대기 때문에 메시지를 놓치는 검사 오류를 피하도록 단일 partition을 직접 읽는다. 이는 업무 Consumer 구현이 아니다.

매번 고유 Compose project를 사용한다. Docker 내부 전용 네트워크로 호스트 포트를 공개하지 않고, 비밀번호는 실행 시 생성해 임시 파일/프로세스 환경에만 전달한다. 원격 Docker context는 거부한다. 정상 종료·예외 시 해당 실행의 container/network/volume/image tag만 정리한다. 강제 프로세스 종료로 정리가 실패하면 출력된 `cq-cdc-...` project를 확인해 해당 project만 정리한다. 다른 Docker 자원이나 저장소 파일은 삭제하지 않는다.

로컬 RF 1·DB SSL 비활성과 내부 관리/controller/exporter용 평문 superuser 경로는 격리된 검사 전용이다. 클라이언트 데이터 경로의 mTLS/ACL 검증과 구분하며 이 예외를 EKS에 복사하지 않는다. Strimzi 인증서 발급/회전·NetworkPolicy·RDS TLS·RF 3·AZ/디스크 장애 복구·S3 적재·성능은 검증하지 않는다. 로컬 DB에서만 테스트 publication/slot/테이블을 생성한다. Docker 메모리는 약 4.25Gi 상한과 엔진 여유가 필요하고 최초 실행은 이미지 다운로드가 필요하다. 업무 값·회원 데이터·로그를 넣지 않는다.

공식 근거: [Debezium PostgreSQL 구성·권한·복구](https://debezium.io/documentation/reference/3.7/connectors/postgresql.html), [PostgreSQL 공식 이미지](https://hub.docker.com/_/postgres).
