# infra/local-ready 병합 검토

2026-10-14. 대상 `origin/infra/local-ready@84080d8`, 현재 `infra/analysis@7cdd4d5`와 이 작업 폴더의 미커밋 단일 AZ 변경을 함께 비교했다. 실제 병합·AWS 배포·이미지 push는 하지 않는다.

판단: **통합할 가치가 있다. 현재 단일 AZ 결정을 보존하고 아래 문제를 수정한 뒤 통합하는 것이 적절하다.** 단순 문서 모음이 아니라 Terraform 기능, Helm chart, 실제 로컬 CDC 검증과 CI가 있다. 다만 배포 완료된 플랫폼이나 업무 파이프라인 전체 구현은 아니다.

## 우선 수정할 항목

### P1: Kafka 배치 조건이 현재 단일 AZ 구성과 충돌

[kafka.yaml 45행](https://github.com/josiah113366-sketch/clothes-query/blob/84080d87615c68bdb20fa3f99733d37841d57c37/infra/platform/kafka/chart/templates/kafka.yaml#L45)의 `minDomains: 2`, `maxSkew: 1`, `DoNotSchedule`은 두 AZ를 요구한다. 현재 워커는 a 한 AZ에만 생성된다. 이 조합에서는 첫 Kafka Pod 이후 나머지 Pod가 배치되지 않아 3개 controller/broker quorum을 구성할 수 없다. 기본 비활성 상태는 영향이 없지만 활성화 시 막힌다.

단일 AZ에 맞게 배치 조건을 변경하고 그 구성을 검증해야 한다. Kafka replicas=3, RF=3, min ISR=2는 별개 결정이다. replicas만 1로 줄이면 schema와 topic/Connect 복제 설정도 맞지 않는다. 단일 AZ에서도 3 broker를 유지할 수 있으나 최소 3개 호스트와 디스크 비용을 다시 검토해야 한다. [Kubernetes minDomains 동작](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/)

### P2: 업무 토픽의 resourceName이 Connect 내부 토픽과 충돌 가능

[_helpers.tpl 16~23행](https://github.com/josiah113366-sketch/clothes-query/blob/84080d87615c68bdb20fa3f99733d37841d57c37/infra/platform/kafka/chart/templates/_helpers.tpl#L16)은 업무 토픽의 `.name`만 예약 이름과 비교한다. 별도 `.resourceName`은 업무 토픽 사이의 중복만 검사한다.

실제로 `name=orders`, `resourceName=clothes-query-dev-connect-configs`를 주고 Connect를 활성화하면 Helm이 성공(exit 0)하면서 동일한 metadata.name의 KafkaTopic 두 개를 출력한다. 한쪽은 orders, 다른 쪽은 Connect configs topic이다. Kubernetes 리소스 정체성이 겹쳐 두 토픽을 의도대로 관리할 수 없다.

해결: 최종 resourceName도 Connect의 configs/offsets/status 예약 이름과 비교하고 거부 테스트를 추가한다.

### P2: 추가 RDS 테스트가 이전 Multi-AZ 인터페이스를 전제

[rds-cdc.tftest.hcl 4행](https://github.com/josiah113366-sketch/clothes-query/blob/84080d87615c68bdb20fa3f99733d37841d57c37/infra/tests/rds-cdc.tftest.hcl#L4)의 공통 입력에는 현재 추가한 필수 `availability_zone`이 없다. 23행은 `multi_az=true`를 요구한다. 현재 RDS 모듈을 보존한 채 새 테스트를 가져오면 실패하므로 Single-AZ 입력/검증으로 바꾸되 CDC·WAL·보호 기능 테스트는 유지해야 한다.

## 통합할 가치가 있는 구현

| 추가 내용 | 가치와 경계 |
|---|---|
| Terraform 검사기/CI | 임시 복사본·backend 없는 init·환경 인증 제거·모든 테스트 mock 강제. Linux lock checksum도 보완 |
| apps 검증 | WEB→WAS 라우팅, Pod Identity, S3 prefix 권한, foundation/HTTPS 입력 거부 검증 추가 |
| RDS CDC | 선택적 논리 복제 parameter group, slot/WAL 예산. 실제 DB 사용자/publication/connector는 별도 |
| workload-access | 서비스별 namespace/ServiceAccount·S3 prefix 권한을 분리하고 endpoint 정책과 대조 |
| Kafka/Connect | Strimzi chart, TLS/ACL, 보존 PVC, 고정 이미지/플러그인, 선택적 지표 및 로컬 smoke test |
| 선택적 Connect ECR | 기본 비활성, 기존 WEB/WAS 저장소 주소 유지 |

Kafka/Connect 기본 비활성, 논리 복제 기본 null, workload bindings 기본 빈 값, Connect ECR 기본 비활성으로 추가 기능을 곧바로 배포하지 않도록 설계했다. 이 기본값은 통합 시 유지하는 편이 좋다.

## 병합 관계와 충돌

현재 HEAD는 대상 브랜치의 ancestor다. 대상 브랜치는 이미 커밋된 analysis 변경을 포함한다. 하지만 **현재 폴더의 미커밋 단일 AZ 변경은 포함하지 않는다.** 따라서 대상 파일로 덮어쓰면 NAT 2개/Multi-AZ RDS/두 AZ 워커 설정으로 돌아갈 수 있다.

임시 파일에서 현재 작업 내용·공통 base·대상 브랜치를 `git merge-file`로 비교했다. IMPLEMENTATION/README, network 모듈 main/outputs/variables, rds 모듈 main/variables, network 스택 main/outputs/variables, rds 스택 main/example, ha 테스트의 **13개 파일에서 텍스트 충돌**이 발생했다. 이는 실제 git merge 실행 결과가 아니라 파일 단위 병합 사전 점검이다. 자동 병합되는 파일도 의미상 호환성을 별도로 확인해야 한다.

diff에 보이는 simulator 변경은 대상 브랜치가 최신 main의 팀원 변경을 포함하기 때문이다. `main@f0a6059`와 대상 브랜치 사이의 simulator 차이는 없다. 이 브랜치가 제네레이터 전체를 새로 구현한 것으로 평가하지 않는다.

## 검증 범위와 배포 한계

리뷰는 원본 작업 폴더를 전환하지 않고 별도 임시 복사본에서 수행했다. 이번 PC에서 직접 재실행한 결과는 다음과 같다.

- 검사기 unit 테스트 9개 통과.
- Terraform fmt 및 backend 없는 init/validate 10개 root, mock 8개 suite/38개 plan 모두 통과. AWS 인증 환경을 제거한 검사다.
- Helm lint/렌더, 고정 Strimzi CRD schema, 잘못된 입력 18개 거부, 지표 selector 검사 통과.
- Connect Docker 이미지 실제 빌드 성공. 로컬 PostgreSQL/Kafka/Connect에서 mTLS·hostname 검증, 인증서/토픽/group 권한 거부, snapshot·insert/update/delete 전달, Connect 중단 중 변경의 재시작 후 전달 통과.
- Kafka 컨테이너 재생성 후 메시지·Connect offset 보존과 CDC 재개, Kafka/Connect 지표 및 양수 consumer lag 검사 통과.
- 별도 부정 사례로 업무 topic resourceName과 Connect 내부 리소스 이름 충돌을 재현했다. 기존 검사가 통과한다는 것만으로 해당 입력 오류가 방지되는 것은 아니다.

위 결과는 수정 전 대상 브랜치 자체의 결과다. 현재 단일 AZ 작업과 통합한 결과를 검증한 것은 아니다.

원격 [CI 실행 38455289322](https://github.com/josiah113366-sketch/clothes-query/actions/runs/38455289322)를 API로 확인했다. `8bbd72c`에서 Terraform, Kafka Helm, Kafka local, Connect image scan 네 job 모두 success다. 이후 대상 HEAD까지의 변경은 인수인계 문서다.

이미지 검사는 report-only다. 브랜치의 조치 기록에는 Critical 0/High 35가 남아 있으며 CI 녹색을 무취약 판정으로 보면 안 된다. 이번 리뷰는 최신 취약점 DB로 별도 스캔을 재실행하지 않는다. 실제 EKS scheduling/CNI 정책/EBS/RDS TLS, 장애·성능 검증은 로컬 테스트로 확인되지 않는다. 실제 WEB/WAS 이미지, 업무 KafkaConnector, Consumer→S3 파이프라인, Secret 공급, 수집 서버/알림은 여전히 별도 준비다.

## 권장 통합 순서

1. 현재 단일 AZ 작업과 비공개 입력을 보존한다. 비공개 입력/state/plan은 Git에 넣지 않는다.
2. 통합 검토용 브랜치에서 local-ready의 추가 기능을 반영하며 NAT 1개·단일 AZ 워커·RDS Single-AZ·PostgreSQL 16.15·DB 크기 보류·기존 HPA를 유지한다.
3. Kafka 단일 AZ 배치, 토픽 리소스 이름 충돌, CDC 테스트 입력을 수정한다.
4. 통합 결과에서 Terraform/Helm/로컬 CDC 검사를 다시 실행한다. 그다음 최종 AWS plan을 따로 검토한다.

이 리뷰는 통합 권고이며 실제 merge/push/apply를 수행한 기록이 아니다.
