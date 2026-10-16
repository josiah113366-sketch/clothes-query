# Kafka 단일 노드 축소 구성 검증

상태: 제안(배포 사양) / 로컬 축소 검증 완료 · 2026-10-16

## 목적과 범위

사용자는 특정 월 예산보다 필요한 기술을 유지하며 최소 규모로 운영하기를 원한다. Auto Mode를 유지한 t3a.large(2 vCPU/8 GiB) 한 대에서 Kafka·Connect를 시작할 후보를 검증한다. 실제 EKS·노드·NAT·Kafka를 생성하지 않고 기존 RDS·S3도 변경하지 않는다. EKS 전체 스케줄링·이미지 다운로드·EBS·RDS TLS·업무 처리량·장기 CPU credit은 로컬 테스트의 완료 기준에 포함하지 않는다.

## 별도 축소 프로필

`infra/platform/kafka/single-node-values.yaml`을 명시적으로 적용할 때만 `profile=single-node`를 선택한다. 파일만으로 Kafka/Connect가 활성화되지 않는다. 기존 기본 profile=standard의 3 broker·RF 3·min ISR 2·두 AZ 분산·Connect 2개는 보존한다.

| 대상 | 축소 값 |
|---|---|
| Kafka | broker/controller 겸용 1개, 1536 MiB, heap 512 MiB, CPU request 500m/limit 1 |
| 저장·보관 | 새 볼륨 20 GiB, 72시간, Retain/deleteClaim=false |
| Connect | 1개, 1 GiB, heap 512 MiB, CPU request 250m/limit 1 |
| 복제 | 업무/Connect 내부/offset/transaction 토픽 모두 RF 1·min ISR 1 |
| 배치 | Kafka의 두 AZ minDomains 강제 조건을 제거. 단일 노드 장애 시 중단 허용 |
| Topic/User Operator | 각각 request 256 MiB/limit 384 MiB, heap 128 MiB |
| Cluster Operator | 기존 request 384 MiB/limit 512 MiB 유지 |
| 인증·권한 | 내부 mTLS·명시적 ACL·Secret 참조 유지 |

Kafka/Connect/운영자 합산은 memory request 3456 MiB, limit 3840 MiB다. Kubernetes·CSI·CNI·Metrics Server·앱·Consumer·Spark는 별도다. CPU limits 합계는 실제 2 vCPU보다 클 수 있으며 Kubernetes는 requests로 배치하므로, 실제 동시 CPU 사용과 지연을 측정해야 한다. 이 예산은 전체 플랫폼 한 대 수용 보장이 아니다.

기존 RF=3 클러스터에 축소 프로필을 덮어쓰거나 이미 생성한 PVC 용량을 낮추지 않는다. 이번 후보는 아직 배포되지 않은 신규 개발 runtime용이다. 노드 수 자동 확장은 Kafka broker 수를 자동 변경하지 않는다.

## 정적 검증

사용자 결정으로 단일 노드 프로필의 저장·보관을 20 GiB·72시간으로 변경했다. 업무 토픽은 runtime values에서 `retentionMs: 259200000`을 명시해야 한다. 정적 검증은 이 업무 토픽 설정과 broker의 72시간, 20 GiB PVC 렌더링을 확인하며 Connect 내부 토픽의 compact 정책은 보존한다. 아래 로컬 smoke 결과는 변경 전 실행이며 72시간 경과나 20 GiB 디스크 포화 실험을 수행한 결과는 아니다.

Helm lint/render 및 고정 Strimzi 1.3.0 CRD schema 검증 통과. 기존 standard와 축소 profile 모두 검증한다. 업무·내부 토픽의 복제 계수 일치, 단일 노드 배치, 메모리 예산, TLS/ACL·PVC 보존 및 프로필 단독 비활성 상태를 확인한다. 잘못된 입력 25개를 거부한다.

## 로컬 실행

```powershell
python -X utf8 infra/platform/kafka/local-smoke/check.py --compact
```

고유 Compose project 안에서 Kafka 1536 MiB·Connect 1024 MiB·각 heap 512 MiB로 실행한다. Kafka/Connect의 CPU quota는 각각 1 vCPU(합계 2 vCPU)이며, 테스트 fixture인 PostgreSQL/client/exporter의 CPU는 이 예산 밖이다. fixture를 포함한 memory limit 합계는 3840 MiB다. 이는 별도의 컨테이너별 quota이며 2 vCPU/8 GiB짜리 Kubernetes VM/노드를 재현한 것이 아니다. Docker 엔진은 8 CPU/약 15.5 GiB로 관측했다. 데이터 초기화 컨테이너는 별도 선행 실행 후 종료한다.

첫 실행에서는 fixture까지 quota 합계 2 vCPU로 제한한 상태에서 초기 snapshot 관측이 timeout으로 실패했다. 당시 Kafka/Connect는 기동했고 connector/task RUNNING을 확인했으나, end-to-end 전달 성공으로 기록하지 않았다. 검증용 Java consumer의 0.3 CPU quota·짧은 수신 대기 시간의 영향을 구분하기 위해 실제 제안값과 같은 Kafka/Connect 각 1 CPU와 더 긴 관측 대기로 재검증한다. 첫 실행 project의 container/network/volume/image tag는 정리됐다.

두 번째 실행에서 추가한 compact 옵션 변수와 기존 CLI 인자 리스트의 이름 충돌을 발견해 수정했다. 해당 실패는 Kafka 성능 실패로 분류하지 않는다. 후속 실패 시 비밀값을 가린 로그·stats를 `.cache/kafka-compact-failure.json`에 보존하고 실행별 자원을 정리한다.

검증은 초기 snapshot, insert/update/delete, 1000행 burst, TLS/ACL 허용·거부, Connect 중단 중 변경의 재전달, Kafka 컨테이너 재생성 후 메시지/Connect offset 보존, 지표 노출이다. 주기적 Docker stats와 OOM/재시작·실제 CPU/memory 제한을 확인하며 `.cache/kafka-compact-report.json`에 결과를 저장한다. 테스트용 DB는 정수 ID/value만 사용하고 실제 RDS·업무 스키마에는 접속하지 않는다. 실행별 container/network/volume/image tag만 정리한다.

## 실제 결과

수정 후 실행 project `cq-cdc-77ee950018`에서 다음 검사를 모두 통과했다.

- TLS hostname·인증서 검증과 ACL 허용/거부, 초기 snapshot 및 insert/update/delete 전달.
- 추가 1000행 burst 모두 전달. 관측 소요 13.8초는 consumer JVM 시작·polling/수신 대기를 포함하므로 처리량 SLA나 지속 RPS로 환산하지 않는다.
- Connect 중단 중 변경의 재시작 후 전달, 캡처 범위 밖 테이블 토픽 미생성.
- Kafka 컨테이너 재생성 후 같은 named volume 사용, 메시지 end offset·Connect source offset 보존, snapshot 재시작 없이 CDC 이어받기.
- Kafka controller/복제·Connect task/CDC 연결·consumer lag 지표.
- Kafka/Connect 실제 CPU quota 각각 1 vCPU 및 memory limit 1536/1024 MiB 확인. 모든 실행 컨테이너 OOMKilled=false, RestartCount=0.
- Docker stats 268개 관측에서 service별 memory 최대: Kafka 522.5 MiB, Connect 688.6 MiB, PostgreSQL 43.8 MiB, client 164.2 MiB. 서로 다른 시점의 최대값이므로 합산 peak로 해석하지 않는다. Docker stats는 전체 JVM 예약량·페이지 캐시·Kubernetes 예산과 동일한 수치가 아니다. exporter는 마지막에 시작해 stats sample은 없으며 256 MiB limit과 정상 상태를 inspect로 확인했다.
- project의 container/network/volume/image tag 정리 완료. 정리 후 해당 project의 잔여 container/network/volume이 없음을 확인했다. 이미지 레이어 캐시는 남을 수 있다.

결론: 소량 CDC에서 Kafka 1536 MiB/heap 512 MiB + Connect 1024 MiB/heap 512 MiB 축소 runtime은 로컬 실행·복구 검사를 통과했다. t3a.large 단일 노드의 후보로 유지하되, 아래 실환경 검증 전에는 전체 플랫폼의 성능·가용성이나 8 GiB 노드 수용을 확정하지 않는다.

## 아직 검증하지 않은 것

- Strimzi 운영자/Topic·User Operator의 실제 실행과 재조정·인증서 회전.
- t3a.large 실제 allocatable·시스템 Pod 합산·배포 교체 여유와 장기 CPU credit.
- 실제 EKS 스케줄링·EBS 보존/복구·RDS TLS·S3 Sink 플러그인과 Bronze 적재.
- WEB/WAS·Consumer·Spark를 포함한 전체 서비스 동시 부하 및 처리량 목표.
