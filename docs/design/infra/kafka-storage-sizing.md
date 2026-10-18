# Kafka 시작 디스크 검토

상태: 결정 · 2026-10-14. 사용자가 **broker당 20 GiB × 3개, 총 60 GiB**로 시작하기로 했다. 24시간 보관과 함께 chart 기본값·runtime 예제에 반영했다. 실제 생성은 마지막에 진행한다.

현재 구성은 broker/controller 3개, 업무 토픽 RF=3, gp3 암호화 PVC, Retain/deleteClaim=false다. StorageClass는 allowVolumeExpansion=true다.

| 후보 | broker당 | 합계 | 판단 |
|---|---|---|---|
| 승인된 시작안 | 20 GiB | 60 GiB | 연결·낮은 부하 실험부터 시작 |
| 여유 시작안 | 50 GiB | 150 GiB | 첫 실험에서 더 많은 데이터를 보관할 여유 |
| 기존 렌더 예제 | 100 GiB | 300 GiB | 실측이나 사용자 승인으로 정한 사양이 아님 |

복제 3개이므로 총 60 GiB가 서로 다른 데이터 60 GiB를 담는 것은 아니다. 데이터가 고르게 분산되고 RF=3일 때 원본 로그 기준 이론상 약 20 GiB이며, 실제로는 내부 토픽·인덱스·segment·삭제 지연·운영 여유를 빼야 한다. 성능·안정성 보장은 아니며 부하 테스트 전에 평균/피크 bytes/s, 메시지 크기와 partition 수를 확인한다.

예를 들어 저장되는 논리 로그가 평균 0.1 MiB/s이면 하루 약 8.44 GiB, 1 MiB/s이면 약 84.38 GiB다. 이는 용량 산정 예시이며 압축·Kafka overhead·내부 토픽·불균형·복구 여유를 포함하지 않는다. 20 GiB 시작안은 후자의 하루 보관량에 부족하다.

증설은 Helm 입력 kafka.storageGi를 올려 NodePool의 volume size를 변경하고 PVC 확장·Pod 상태를 확인한다. Kubernetes는 기존 PVC의 축소를 지원하지 않는다. 값을 낮추는 것을 축소 절차로 사용하지 않으며 데이터 이동·새 볼륨 준비는 별도 검토한다. [Kubernetes PVC 확장](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#expanding-persistent-volumes-claims)

사용량 증가 시 broker별 사용률·증가 속도, ISR/under-replicated partition, Consumer lag, 예상 남은 시간을 함께 보고 여유가 소진되기 전에 증설한다. 24시간 보관은 엄격한 디스크 상한이 아니다. 토픽별 partition·segment와 삭제 지연에 따라 필요한 여유가 달라진다.

비용은 프로비저닝한 gp3 합계 용량에 비례한다. 같은 단가라면 20 GiB×3은 기존 100 GiB×3 예제의 저장 용량 비용 20%다. 이번 공개 가격 페이지에서는 도쿄의 동적 단가를 확정하지 못해 달러 월액은 기재하지 않았다. 노드·NAT·EKS·스냅샷 등 다른 비용은 별도다. Retain 볼륨은 release 삭제 후에도 비용이 남을 수 있다. [AWS EBS 가격](https://aws.amazon.com/ebs/pricing/)

현재 chart는 `storageGi: 20`, `retentionHours: 24`, `enabled: false`다. 추후 증설은 비공개 runtime 입력에서 `kafka.storageGi`를 올려 검토한다. 예를 들어 50으로 변경하면 broker당 50 GiB, 총 150 GiB다. 생성 후 값을 20으로 되돌리는 방식의 축소는 지원되지 않는다. 예시 토픽·partition·client 값은 아직 배포 결정이 아니다.
