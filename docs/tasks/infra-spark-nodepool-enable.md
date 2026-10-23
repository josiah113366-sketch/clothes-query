# Spark 전용 NodePool 연결

상태: NodePool 적용·검증 완료, 업무 Job 일시정지 유지 (2026-10-23)
브랜치: infra/spark-nodepool-enable

팀원이 발행한 Silver·Gold A 이미지와 일시정지 검증 Job에 맞춰 기존 compute 스택의 전용 Spark 풀을 활성화한다. 이미지는 ECR 태그 b0185ffb76016d7cd2d65cbcf0e5cc7bf8a9df5a, digest sha256:241d5b96ac42ec5aff3be1a65059a925e7af1a009fe6b6d698c4aae99a34ee39로 일치했다.

`pipelines/silver-gold-a-v2-b0185ff` Job은 suspend=true, active=0이며 전용 풀 selector·Spark toleration·silver-gold-a-submitter 계정을 확인했다. Spark Pod는 없었다. 이 작업에서는 Job을 재개하거나 업무 S3 데이터를 변경하지 않는다.

Terraform fmt/validate와 실제 plan을 통과했다. 변경은 module.compute.kubernetes_manifest.spark_node_pool[0] 한 개 create이며 기존 리소스 update/delete/replace는 없다. 기존 private NodeClass를 참조하고 t3a.large·amd64·On-Demand·기존 두 AZ, 2CPU/8GiB 풀 한도, Spark 전용 taint, WhenEmpty/10분 정리를 적용한다. 고정 replicas가 없으므로 풀 생성 자체로 노드를 상시 띄우지 않는다. 한도는 동시 provisioning 중 일시적인 노드 수·요금의 엄격한 상한을 보장하지 않는다.

공유 auto tfvars를 true로 기록해 후속 기본 apply에서 풀을 삭제하지 않도록 한다. main 반영 전에는 이전 false 설정으로 compute apply하지 않는다. 원격 push·PR·머지는 이번 요청 범위에 포함하지 않는다.

## 작업 결과

실제 apply로 전용 NodePool 1개를 생성했다. Ready=True, NodeClassReady=True, ValidationSucceeded=True를 확인했다. 노드 등록 상태는 아직 노드를 요청하지 않아 AwaitingReconciliation이며 실제 부팅 성공을 검증한 뜻은 아니다. 이후 전체 compute plan의 managed 리소스 변경은 0개였다. Spark 런타임 기존 검사 11개도 통과했다.

검증 Job suspend=true 유지, Spark Pod/노드 0개, 기존 노드 3개의 UID 불변을 확인했다. 기존 공용 NodePool·NodeClass를 변경하지 않았으며 업무 데이터를 읽거나 쓰지 않았다. 수동 검증을 재개하면 실제 노드 부팅·이미지 pull·Driver/Executor 배치·S3 입출력 확인이 필요하다. 작업 종료 후 제출기·Driver·Executor가 남으면 빈 노드 정리가 지연되므로 완료·실패 잔여 Pod를 확인한다.
