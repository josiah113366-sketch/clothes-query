# Connect 이미지 조치 및 재검증

상태: 결정 · 로컬 조치·재검증 완료 / 잔여 취약점 있음 / 실제 배포 미실행

## 변경과 검증 결과

Connect 전용 Dockerfile에서 사용하지 않는 `/opt/cruise-control`, `/opt/kafka-exporter`를 제거했다. 고정 Strimzi 이미지의 Connect 시작 스크립트와 Kafka classpath 구성을 확인하고 JMX agent·Kafka/Connect·Debezium은 유지했다. 공개 UBI 저장소에서 공급하는 다음 RPM 패치만 버전을 고정해 적용했다.

| Package | Before | After |
|---|---|---|
| curl-minimal / libcurl-minimal | 7.76.1-40.el9_8.7 | 7.76.1-40.el9_8.8 |
| pcre2 / pcre2-syntax | 10.40-6.el9 | 10.40-7.el9_8 |

linux/amd64 이미지에서 UID 1001, 제거 경로 부재, JMX agent 존재, 실제 RPM 버전과 PostgreSQL 플러그인 3.7.0.Final의 service loader 등록을 확인했다. Strimzi의 `kafka_connect_run.sh`로 실행한 로컬 전체 검사에서 mTLS/hostname·ACL 허용/거부·snapshot/insert/update/delete·중단 후 변경 전달·Kafka 컨테이너 재생성 후 메시지/Connect offset 유지·CDC 재개·JMX/consumer lag 지표를 모두 확인했다. project `cq-cdc-81b6e09dd3`의 container/network/volume/image tag를 정리했다.

## 동일 DB의 스캔 전후 비교

Trivy 0.75.0 digest 고정, OS/Java 포함 전체 이미지 검사, ignore 없음. [조치 전 결과](connect-image-security-2026-10-14.md)와 vulnerability/Java DB의 `UpdatedAt`이 각각 동일하다. 아래 수치는 CVE/package/설치 버전 기준 중복을 제거한 scanner 결과이며 위험도나 실제 공격 가능성의 합계가 아니다.

| Severity | Before | After | After: listed fix |
|---|---:|---:|---:|
| Critical | 1 | 0 | 0 |
| High | 73 | 35 | 13 |
| Medium | 297 | 241 | 21 |
| Low | 133 | 127 | 1 |
| Unknown | 7 | 0 | 0 |
| Total | 511 | 403 | 35 |

Critical Netty 항목은 Cruise Control 디렉터리 제거 후 현재 Connect 파일시스템 검사에서 사라졌다. High 감소 38개는 Cruise Control 34개와 Kafka Exporter 4개다. OS 패치 후 Medium도 감소했지만 pcre2의 잔여 High가 해결됐다고 표시하지 않는다. 삭제된 파일이 기반 이미지의 하위 레이어에서 완전히 사라지는 것은 아니다.

- 검사 UTC: `2026-10-13T19:16:37.732926+00:00`
- 로컬 image ID: `sha256:646f64070a9f9009cf3e3119a57895fdcd7b148836f02b134f93350f8d8c5b96` (ECR registry digest 아님)
- 로컬 Dockerfile SHA-256: `62f042a141c2b8018f23ae50c107c550ac642b6582fa7b8d3a1d76112c16c2e6` (checkout 줄바꿈에 따라 달라질 수 있음)
- Scanner: `ghcr.io/aquasecurity/trivy@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa`
- Vulnerability DB UpdatedAt: `2026-10-13T13:06:33.602531196Z`
- Java DB UpdatedAt: `2026-10-13T01:09:47.998143143Z`
- 보고서 inventory: OS 158개, Java 210개. PostgreSQL 플러그인 디렉터리의 Debezium/PostgreSQL JDBC 등 10개 package record 포함. 이 사실이 모든 라이브러리 취약점 검출 또는 무취약을 보증하지 않는다.
- 전체 원본·DB metadata는 로컬 `.cache/connect-security/{report.json,summary.json,summary.md}`에 남기며 원격에 업로드하지 않는다.

## 남은 High와 후속 조치

| 포함 위치 | High | 상태와 다음 조치 |
|---|---:|---|
| Base OS | 22 | expat, gnutls, util-linux 계열, pcre2, Python 계열. 현재 scanner DB에 수정 버전 정보 없음. 공개 UBI 패치 재확인·공급자 advisory·실제 실행 경로 검토 필요 |
| Kafka/Connect Java | 13 | Jackson core/databind, LZ4, Jetty security, JLine. scanner에 수정 버전 정보가 있으나 현재 고정 배포판에 미반영. 공식 Strimzi/Kafka 갱신 또는 별도 의존성 변경·호환성 검증 필요 |

확인 시 [Strimzi 최신 안정판](https://strimzi.io/downloads/)은 1.3.0, 지원 Kafka에는 현재 사용 중인 4.3.1이 포함되며 [Debezium 최신 안정판](https://debezium.io/releases/3.7/)은 3.7.0.Final이다. 최신 버전 사용을 취약점 해결로 간주하지 않는다. 이번 변경은 개별 Java jar를 교체하지 않았다. Java 후속 조치는 의존성 묶음·플러그인 격리·REST/TLS·압축 방식별 메시지 호환성까지 검증해야 한다. OS 수정 버전 부재도 안전함을 뜻하지 않는다.

조치는 **Connect 이미지에만 적용**했다. Kafka broker·lag exporter·operator의 원본 이미지와 해당 이미지의 취약점은 별도 관리 대상이다. 로컬 단일 broker 검사는 EKS operator/Secret 발급·RDS TLS·PVC/EBS·RF 3·AZ 장애·성능 검증을 대신하지 않는다. Critical 0 또는 CI 성공은 배포 승인이나 무취약 보증이 아니다.

근거: [Strimzi 1.3.0 이미지 구성](https://github.com/strimzi/strimzi-kafka-operator/blob/1.3.0/docker-images/kafka-based/kafka/Dockerfile), [Strimzi Connect 시작 스크립트](https://github.com/strimzi/strimzi-kafka-operator/blob/1.3.0/docker-images/kafka-based/kafka/scripts/kafka_connect_run.sh), [Red Hat UBI 패키지 관리](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/building_running_and_managing_containers/assembly_types-of-container-images_building-running-and-managing-containers), [로컬 검사 안내](../../../infra/platform/kafka/image-security/README.md).
