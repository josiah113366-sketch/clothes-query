# PostgreSQL CDC Connect 이미지

Strimzi 1.3.0 / Kafka 4.3.1 기반에 Debezium PostgreSQL 3.7.0.Final만 추가한다. 기반 이미지 digest와 플러그인 SHA-256은 Dockerfile에 고정했다. Maven Central의 SHA-512와도 대조했다. Debezium 공식 표의 PostgreSQL 지원 범위는 14~18이므로 실제 RDS 버전을 확인한 뒤 사용한다. 기존 CDC 모듈의 PostgreSQL >=13 검증은 이 플러그인의 호환성 보증이 아니다.

2026-10-24 CI 다운로드 실패 보완: 공식 파일과 SHA-512를 다시 대조해 기존 SHA-256이 맞음을 확인했다. BuildKit의 원격 HTTP ADD 대신 빌드 컨테이너의 HTTPS curl로 받고 고정 SHA-256을 통과한 파일만 압축 해제한다. 전송 실패·체크섬 불일치 모두 새로 받아 최대 3번 확인하며 끝까지 실패하면 빌드를 중단한다. 플러그인 버전과 고정 해시는 바꾸지 않았다.

Connect 전용으로 Cruise Control과 Kafka Exporter 디렉터리를 제거하고 공개 UBI의 curl/libcurl/pcre2/pcre2-syntax 패치를 정확한 RPM 버전으로 고정했다. JMX agent와 Kafka/Connect·Debezium Java 라이브러리는 유지한다. 이 Dockerfile의 OS 패치는 현재 노드 계획과 같은 **linux/amd64 전용**이다. 공개 저장소에서 고정 RPM을 더 이상 공급하지 않으면 빌드가 실패하므로 버전과 검사를 함께 갱신한다. broker와 lag exporter는 별도의 원본 Strimzi 이미지를 계속 사용한다.

로컬 Docker Linux 엔진이 있을 때 이 폴더에서 실행:

```powershell
docker build --platform linux/amd64 -t clothes-query-connect:3.7.0 .
docker run --rm --network none --entrypoint /opt/kafka/bin/connect-plugin-path.sh clothes-query-connect:3.7.0 list --plugin-path /opt/kafka/plugins
```

이미지 빌드만으로 배포하지 않는다. [ECR stack](../../../stacks/ecr/README.md)의 선택적 Connect 저장소를 준비·검토하고, 스캔·별도 승인된 push 이후 받은 **레지스트리 digest**를 `connect.image`에 넣는다. 로컬 image ID는 레지스트리 digest가 아니다. WEB/WAS ECR 저장소를 재사용하지 않는다. 저장소 코드는 준비했지만 실제 생성·업로드는 수행하지 않았다.

2026-10-14 이 PC에서 Linux/amd64 빌드와 위 네트워크 차단 검사를 실행했다. `PostgresConnector` 버전 `3.7.0.Final`의 발견 및 서비스 로더 등록을 확인했다. 이미지 조치 후 Strimzi 시작 스크립트로 [일회성 로컬 검사](../local-smoke/README.md)를 실행해 mTLS/ACL·DB 변경 전달·Kafka 재생성 후 offset 보존·지표 노출도 확인했다. [동일 DB 재검사](../../../../docs/design/infra/connect-image-remediation-2026-10-14.md)는 Critical 1→0/High 73→35다. 잔여 취약점이 있으며 실제 RDS/EKS 연결은 수행하지 않았다.

배포 시 `/connector-plugins` 응답에 `io.debezium.connector.postgresql.PostgresConnector`가 있는지 확인한다. Connector의 DB·table·publication·slot·snapshot·heartbeat·topic 계약은 CDC 담당자가 작성한다.

공식 근거: [Strimzi custom Connect image](https://strimzi.io/docs/operators/latest/deploying.html#creating-new-image-from-base-str), [Debezium 호환 범위](https://debezium.io/releases/), [고정 플러그인](https://repo.maven.apache.org/maven2/io/debezium/debezium-connector-postgres/3.7.0.Final/).
