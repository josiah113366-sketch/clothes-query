# 판정·조사 Pod 실행 신원

`service-accounts.yaml`은 `agent` namespace와 `detection-job`, `investigation-agent` ServiceAccount를 선언한다. [gold-b-access 스택](../../stacks/gold-b-access/README.md)의 Pod Identity association과 이름을 맞춘다. IRSA annotation이나 정적 AWS 키는 넣지 않는다. Kubernetes API token 자동 마운트는 끄며 EKS Pod Identity가 주입하는 별도 AWS 인증 토큰을 사용한다.

namespace/SA의 관리 주체는 이 manifest다. 기존 리소스와 다른 Helm/Terraform 소유자가 없는지 확인한 뒤 `kubectl apply -f infra/platform/agent-access/service-accounts.yaml`로 적용한다. 이후 Airflow/업무 앱 배포가 같은 자원을 중복 생성하지 않도록 재사용한다. scheduler의 Pod 생성 RBAC·실제 업무 이미지·자원 설정·DAG는 별도 작업이다. namespace만으로 노드가 분리되지는 않는다.

`probe.py`는 임시 Pod 내부에서 실행하는 합성 접근 검사다. 실제 정답표/업무 데이터를 출력하지 않는다. 기존 private 이미지 중 boto3를 포함한 digest를 검증해 사용하고 앱 기본 명령을 실행하지 않는다. 현재 AWS credential chain이 Pod Identity 역할인지 확인한 뒤 gold_b 합성 객체 읽기, 자기 결과 읽기/쓰기, 정답표 객체·버전·목록/상대 결과/다른 workgroup/업무 데이터 쓰기 거부와 SELECT 1 결과를 검사한다.

프로브에는 `PROBE_ROLE`(detection/investigation), `PROBE_BUCKET`, `PROBE_RUN_ID`, `PROBE_TRUTH_VERSION`만 공급한다. 실제 값은 Git에 기록하지 않는다. 실행 전 관리자가 해당 run의 합성 source/truth/결과 객체를 준비하고 객체 VersionId를 추적한다. 기존 compute 노드에 고정한 소형 일회성 Pod로 실행하며 실제 업무 서비스를 띄우지 않는다. Athena 실제 조회·S3 요청/저장에는 소액 과금이 발생할 수 있다.

완료 후 임시 Pod, 해당 run의 합성 객체 **모든 버전과 delete marker**, SELECT 1의 결과와 metadata를 정리한다. query ID와 run prefix가 일치하는 객체만 지운다. 기존 정답표·업무 파일·다른 쿼리 결과는 건드리지 않는다. namespace/SA와 운영 역할은 유지한다. 실제 Gold B SQL/뷰 조회·부하·1GiB cutoff 초과 실험을 대신하는 검사는 아니다. [실행 기록](../../../docs/tasks/infra-gold-b-access-prep.md).
