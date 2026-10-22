# Spark 실행 기반 및 공용 메모리 확대 대안 준비

상태: 코드 준비·검증 완료, 실제 미적용·로컬 브랜치 보관

## 사용자 결정과 범위

사용자는 실제 노드를 생성하지 않고 Spark 실행 기반을 준비하도록 요청했다. 이후 별도 노드 대신 공용 노드 메모리를 늘리는 대안도 검토하도록 추가했다. 두 후보를 분리하고 기본 활성화를 금지한다. 업무 Spark 코드·DAG·데이터는 만들거나 변경하지 않는다.

## 완료 확인

- [x] 최신 main `194ff3a`에서 브랜치 생성, 기존 작업 보존.
- [x] Spark 전용 NodePool opt-in 변수, 기본 비활성 및 공유 auto tfvars 명시.
- [x] 공용 r6a.large 대안과 CPU 예약 조정·제출기 포함 자원 계산.
- [x] Spark 계정·RBAC·quota·Driver/Executor 프로필 및 파일만 생성하는 렌더 도구.
- [x] 실제 파이프라인에 Spark 실행 코드/이미지가 미연결인 점과 S3/SDK/committer 계약 기록.
- [x] Terraform 격리 validate·mock plan, Python 검사 최종 통과.
- [x] 변경/미적용 범위 최종 점검·로컬 커밋.

## 작업 결과

실제 Kubernetes/AWS API를 변경하지 않았다. Terraform apply·실제 인프라 plan·Job 제출·Docker 실행·S3 더미 데이터 입력·이미지 업로드를 하지 않았다. S3 역할은 예시만 있고 기존 workload bindings/네트워크 정책을 바꾸지 않았다. NodePool과 공유 CPU 후보는 아직 선택·성능 검증되지 않았다.

공용 대안은 RAM만 늘리는 변경으로 끝나지 않는다. CPU 요청량 조정 외에도 기존 Airflow private runtime의 hostname 고정 해제와 Kafka PVC AZ/단일 broker 교체 영향 검토가 필요하다. 전용 medium 한 대도 가용 메모리 대비 작은 개발 프로필일 뿐이며 실측을 보장하지 않는다. 두 후보의 상태와 비용·제약은 [실행 기반 안내](../../infra/platform/spark/README.md)에 정리한다.

검증: AWS/Kubernetes 인증을 비운 격리 복사본에서 compute 모듈·스택·test root init/validate, 기존 회귀와 두 후보/기본 미생성 등을 포함한 Terraform mock plan 7개를 통과했다. Python 안전성·배치·digest·기본 비활성·제출기를 포함한 CPU 계산 시험 7개, 기본/공유 렌더, Terraform fmt와 git diff 공백 검사도 통과했다. 원격 GitHub Actions 실행은 아직 하지 않았다. 테스트는 실제 Spark 바이너리·이미지·S3·EKS admission·노드 수용 성능을 검증하지 않는다.
