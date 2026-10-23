# Spark 실행 기반 및 공용 메모리 확대 대안 준비

상태: 상시 배포 비활성, 후속 EKS 합성 계산·동적 할당 시험 성공 및 리소스 정리 완료, 업무 연결 정보 대기

## 사용자 결정과 범위

2026-10-22 추가 결정: Spark 전용 노드풀로 준비하며, 작업이 없을 때 0대까지 축소한다. 공용 메모리 확대안은 참고용으로 보존한다. 실행 주기와 처리 대상·이미지·노드 타입·확장 상한은 미정이다. 기존 빈 노드 10분 정리 후보와 비활성 기본값을 유지하며 실제 배포는 하지 않는다.

사용자는 실제 노드를 생성하지 않고 Spark 실행 기반을 준비하도록 요청했다. 이후 별도 노드 대신 공용 노드 메모리를 늘리는 대안도 검토하도록 추가했다. 두 후보를 분리하고 기본 활성화를 금지한다. 업무 Spark 코드·DAG·데이터는 만들거나 변경하지 않는다.

## 완료 확인

추가 결정: 최초 노드 타입은 t3a.large로 선택했다. S3 외 RDS·Kafka 직접 읽기도 검토 범위에 포함하며 실제 읽기 대상·DB 계정·Kafka 토픽/인증·출력 경로·확장 상한은 미정이다. 아직 예시 용량 설정을 확정값으로 바꾸거나 실제 연결 권한을 적용하지 않았다.

추가 사용자 선택: S3 Bronze → Spark → Silver/Gold 처리 흐름. 정확한 경로·출력 계약과 업무 Spark 이미지는 미정이며, 기존 Python 코드를 자동으로 Spark로 전환하지 않는다. 아직 데이터 접근 권한이나 리소스를 적용하지 않았다.

- [x] 최신 main `194ff3a`에서 브랜치 생성, 기존 작업 보존.
- [x] Spark 전용 NodePool opt-in 변수, 기본 비활성 및 공유 auto tfvars 명시.
- [x] 공용 r6a.large 대안과 CPU 예약 조정·제출기 포함 자원 계산.
- [x] Spark 계정·RBAC·quota·Driver/Executor 프로필 및 파일만 생성하는 렌더 도구.
- [x] 실제 파이프라인에 Spark 실행 코드/이미지가 미연결인 점과 S3/SDK/committer 계약 기록.
- [x] Terraform 격리 validate·mock plan, Python 검사 최종 통과.
- [x] 변경/미적용 범위 최종 점검·로컬 커밋.

## 작업 결과

추가 결정: Silver·Gold A 개발자의 ECR push 신원은 arn:aws:iam::827913617635:user/de-ai-18로 확정했다. 전달 계약과 문안에 반영했으며 Spark 실행용 Pod Identity 역할과 분리한다. 추후 권한 축소 또는 신규 ARN으로 변경할 수 있게 유지한다. 신규 ARN 교체는 새 신원에 권한 부여·push 확인 후 기존 권한 회수 순서다. 이번 변경은 문서/계약만 수정했으며 IAM·ECR·EKS 권한을 적용하지 않았다.

최신 업무 연결 준비: 동료가 제공한 Bronze 주문/주문상품/결제 JSON Lines 경로와 Silver·Gold A run/manifest 공개 계약을 전달 명세에 반영했다. prepare_trade_access.py는 읽기/쓰기 경로 계획을 로컬로 출력하고, namespace·계정·실행 요청 JSON prefix가 있어야 기존 workload-access 입력에 Driver/Executor 권한을 병합하는 검토 파일을 만든다. 기존 binding 보존과 충돌/경로 확장/보호 경로 거부를 검사했다. 현재 20개 로컬 검사를 통과했다. 삭제·multipart 정리·Glue 권한과 영구 ECR/업무 이미지·DAG는 아직 적용하지 않았다. 전달 문안을 handoff/message-to-pipelines.md에 작성했다. AWS 리소스 생성·권한 변경·이미지 push·업무 데이터 읽기/쓰기는 이번 작업에서 하지 않았다.

최신 후속 결과: 사용자가 권한 수정 후 재시험을 요청했다. Spark 4.2 NetworkPolicy 권한의 실제 API 검사를 통과했고 EKS t3a.large 한 대에서 Driver 실행·합성 계산·Executor 1→2→1개 증감이 성공했다. 표본 합산 최대는 CPU 약 1.40 vCPU·메모리 약 1.64GiB였고 업무 성능 보장은 아니다. 임시 namespace·노드풀·ECR을 정리하고 EC2 terminated와 기존 노드 2대 유지까지 확인했다. 후속 시험 종료 시각은 2026-10-22 16:35 KST다. 10분 자동 축소를 기다린 검증은 아니다.

추가 결정 없이 진행한 로컬 준비: runtime.py에 namespace·이름 접두사·노드풀 입력을 추가하되 기본값을 유지했다. 계정·RBAC·설정·제출 Job 참조가 함께 바뀌는지와 잘못된 이름 거부를 검증했고 현재 검사 14개가 통과했다. Silver·Gold A 전달 명세와 적용 순서/로그 확인 계약을 준비했으며 namespace 공유·계정 이름·S3 prefix·영구 ECR·DAG 공급 방식은 확정하지 않았다. 로컬 기본 이미지의 Python 3.10.12를 확인했다. 이 추가 준비에서는 AWS/Kubernetes 변경·업무 DAG 작성·이미지 push·새 노드 생성은 하지 않았다.

아래 단락은 이전 시험과 준비 이력이다. 최신 결과는 위 두 단락과 상위 Spark README를 우선한다.

2026-10-22 사용자 요청으로 짧은 합성 시험을 진행했다. 공식 이미지 digest 고정·전이 의존성 4개 충돌 수정·기본 이미지 빌드와 네트워크 없는 로컬 Spark 계산/커넥터 클래스 로딩은 통과했다. 추가 jar 10개의 버전/체크섬을 기록했다. 이미지는 약 2.07GB(비압축)다.

임시 클라우드 시험 2회에서 전용 t3a.large 노드 생성·이미지 pull·제출기 실행을 확인했으나, Spark 4.2 NetworkPolicyFeatureStep의 NetworkPolicy PATCH 권한 부족(403)으로 제출이 실패했다. submitter Role에 namespace 한정 NetworkPolicy create/get/patch/delete를 코드로 추가했다. 로컬 회귀 포함 12개 검사가 통과했으며 수정 후 클라우드 실행은 반복하지 않았다. 따라서 Executor 1→2 증감·전체 처리 자원·10분 자동 축소는 미검증이다.

각 시험의 namespace·노드풀·ECR을 삭제하고 EC2 2대 모두 terminated를 확인했다. 기존 노드 2대와 업무 데이터/권한은 유지했고 공유 enabled=false도 유지한다. Terraform apply/state 변경은 하지 않았다. private 상세 증거는 .cache/spark-live-smoke-first-summary.json, spark-live-smoke-summary.json, spark-final-audit.json에 보관한다. 아래는 최초 준비 단계의 기록이며 최신 실행 결과는 이 단락을 우선한다.

Spark 4.2.0 선택 후 기본 이미지 Dockerfile·Maven 연결 의존성 POM·jar 충돌 검사와 안내서를 준비했다. 기본 Spark/Hadoop 버전 확인과 비특권 실행을 구성했고 jar 충돌 시 기존 파일을 바꾸기 전에 중단한다. registry digest 조회는 HTTP 401로 미확정이며 빌드 이미지도 digest를 전달받아야 한다. Docker 실행·Maven 의존성 해결·클래스 로딩·실제 접속·ECR push는 하지 않았다. 이미지 완성으로 보고하지 않는다.

이미지 책임 결정: 인프라는 기본 Spark 이미지와 연결 라이브러리를 준비하고, 팀원은 업무 코드를 추가한다. 기본 버전 선택이 다음 단계이며 이미지를 만들거나 업로드한 상태는 아니다.

최신 Executor 선택: 전용 프로필은 Driver 1개 + Executor 초기/최소 1개·최대 2개의 동적 할당과 shuffle tracking을 준비한다. 한 대분 노드 한도에 맞춰 Executor CPU request를 500m로 조정했다. 최대 요청량 1500m/4.5GiB이며 실제 실행 검증은 아직 하지 않았다. 공용 참고 프로필은 고정 1개를 유지한다.

최신 결정 반영: t3a.large 한 대분(2CPU/8GiB) 한도를 공유 compute auto tfvars와 전용 예시에 명시했다. enabled=false를 유지했으며 실제 노드 생성/권한 적용은 하지 않았다. Executor 수·자동 확장과 출력 경로는 후속 결정 대상이다.

후속 준비: 사용자 승인 범위에 맞춰 connections.example.yaml에 S3/RDS/Kafka 입력과 출력·checkpoint의 미정 필드를 분리했다. 모든 source는 비활성이며 runtime.py와 미연결인 계약 예시임을 명시했다. 실제 권한과 Secret·DB/Kafka 연결은 적용하지 않았다. 선택한 t3a.large의 확장 상한은 다음 사용자 결정 후 설정에 반영한다.

실제 Kubernetes/AWS API를 변경하지 않았다. Terraform apply·실제 인프라 plan·Job 제출·Docker 실행·S3 더미 데이터 입력·이미지 업로드를 하지 않았다. S3 역할은 예시만 있고 기존 workload bindings/네트워크 정책을 바꾸지 않았다. NodePool과 공유 CPU 후보는 아직 선택·성능 검증되지 않았다.

공용 대안은 RAM만 늘리는 변경으로 끝나지 않는다. CPU 요청량 조정 외에도 기존 Airflow private runtime의 hostname 고정 해제와 Kafka PVC AZ/단일 broker 교체 영향 검토가 필요하다. 전용 medium 한 대도 가용 메모리 대비 작은 개발 프로필일 뿐이며 실측을 보장하지 않는다. 두 후보의 상태와 비용·제약은 [실행 기반 안내](../../infra/platform/spark/README.md)에 정리한다.

검증: AWS/Kubernetes 인증을 비운 격리 복사본에서 compute 모듈·스택·test root init/validate, 기존 회귀와 두 후보/기본 미생성 등을 포함한 Terraform mock plan 7개를 통과했다. Python 안전성·배치·digest·기본 비활성·제출기를 포함한 CPU 계산 시험 7개, 기본/공유 렌더, Terraform fmt와 git diff 공백 검사도 통과했다. 원격 GitHub Actions 실행은 아직 하지 않았다. 테스트는 실제 Spark 바이너리·이미지·S3·EKS admission·노드 수용 성능을 검증하지 않는다.
