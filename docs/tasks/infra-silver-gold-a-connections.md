# Silver·Gold A 첫 거래 실행 연결 준비

상태: ECR·18번 push 권한 적용 및 기본 Spark 이미지 발행 완료, 업무 이미지 대기

브랜치: infra/silver-gold-a-connections

기존 infra/spark-runtime-followup의 ECR·Spark access 준비를 보존하고 #82가 머지된 origin/main 36835f5를 반영했다. 사용자는 노드·업무 실행 없이 준비를 계속하도록 요청했다. [최신 연결 명세](../../infra/platform/spark/handoff/silver-gold-a-ready.md)를 따른다.

## 범위

- pipelines namespace의 제출기·Driver·Executor 계정과 제한된 RBAC/template 렌더. 실행 Pod·Job·NodePool 및 공유 namespace 전체 ResourceQuota는 생성하지 않는다.
- 최종 ECR digest가 있을 때만 Airflow runtime ConfigMap을 렌더한다. 기존 Git bundle 및 env·Secret 참조를 보존하는 values overlay를 별도 파일로 생성한다.
- Bronze 거래 입력·거래 출력·확인한 상품 스냅샷만 허용하는 Driver/Executor 역할. 제출기에는 AWS data 역할이 없다.
- Magic 작업 객체와 두 고정 검증 실행의 part-*.parquet에 한정한 삭제. 전체 prefix·manifest/current/completed 삭제는 허용하지 않는다. 과거/다른 정상 실행은 삭제 대상으로 추가하지 않는다.
- S3 endpoint에 multipart listing/parts/delete 전달 권한을 추가하는 검토. 역할 plan은 endpoint 선행 적용을 검사하며 우회하지 않는다.

## 실제 상태 읽기 확인

2026-10-23 두 고정 요청 JSON의 존재·run_id·입출력 경로를 확인했다. 상품 기준정보 버킷은 도쿄다. pipelines namespace·해당 Pod Identity 역할 연결·Spark base 및 업무 ECR은 아직 실환경에 없다. 요청 JSON의 존재 확인은 실제 업무 검증 성공을 뜻하지 않는다.

## 완료 확인

- Python unittest: 기존 runtime/이미지 검증과 새 runtime 준비 검사, 총 25개 통과.
- Terraform mock: Spark access 7개와 network 3개 통과. 실제 AWS 자원을 생성하는 테스트가 아니다.
- digest 없는 렌더: 11개 객체, 실행 Job/Pod/NodePool 및 공유 ResourceQuota 0개, Airflow placeholder 설정 없음.
- spark-access deployment 자동 설정은 enabled=false 유지. ECR·network 실제 plan 결과는 검토 후 아래 작업 결과에 기록한다.

## 작업 결과

2026-10-23 연결 권한 적용을 시작했다가 사용자가 Kafka 변경 분리를 먼저 요청했다. 요청 전에 이미 진행 중이던 network 저장 계획은 S3 endpoint 정책 1개 update를 완료했고, 적용 후 변경 없음까지 확인했다. 현재 공통 network auto 설정에 실제 허용 작업 8개를 보존했다. spark-access는 init/validate까지만 진행했고 IAM·Pod Identity·namespace·RBAC는 아직 적용하지 않았다. 작업을 전환하며 spark-access auto 설정은 실제와 같이 disabled 상태로 유지했다. 재개 시 network를 다시 변경하기보다 현재 상태를 읽고 spark-access 계획부터 이어간다.

실제 AWS 계획: ECR 저장소 spark-base·silver-gold-a와 de-ai-18 사용자 이미지 push inline 정책, 총 3개 생성. network는 S3 endpoint 정책 1개 update뿐이고 삭제·교체는 없다. 역할 enabled plan은 endpoint 선행 변경 후 다시 확인한다. terraform validate 및 mock 검사는 통과했다.

현재 Airflow 실제 Helm values를 읽어 overlay 병합 호환성을 확인했다. 기존 extraEnv 1개와 Git bundle을 보존하며 새 runtime 참조 하나만 추가한다. 실제 digest는 없으므로 placeholder ConfigMap을 저장하거나 적용하지 않았다.

프리뷰와 적용을 분리했다. namespace 공유와 같은 namespace 내 ServiceAccount 선택은 강한 보안 경계가 아니므로 역할 분리만으로 완전한 격리를 주장하지 않는다. Glue 공개·재처리 SILVER 기록 작성·Gold B 상시 Spark 및 agent 권한은 이 변경에 섞지 않는다. 실제 이미지 digest·네트워크/IAM 적용·노드 활성화 이후에 별도 수동 검증한다.

### ECR 단계 적용

이후 사용자가 ECR 생성과 18번 push 권한 적용에 동의했다. origin/main을 다시 fetch해 36835f5가 최신임을 확인했고, fmt·validate 및 최신 실제 plan을 재확인했다. ECR 저장소 2개와 de-ai-18 inline 정책만 create인 저장 계획을 적용했다. 수정·삭제·교체는 0개다.

AWS에서 두 저장소의 IMMUTABLE 태그와 scan_on_push 설정을 확인했다. 실제 사용자 정책은 두 저장소 ARN에 대한 push/pull 작업 및 리소스 제한을 지원하지 않는 GetAuthorizationToken만 포함함을 확인했다. 다른 기존 사용자 권한을 축소하거나 사용자의 전체 권한이 이 정책에만 한정된다고 주장하지 않는다. 적용 후 plan은 변경 없음이었다.

이미지 발행·Spark 실행 계정·network endpoint 변경·노드 활성화·업무 실행은 아직 하지 않았다. Git push·PR·승인·머지는 하지 않았다. 다음 단계는 기본 이미지 발행과 digest 전달이며 그 후 동료가 업무 이미지를 빌드·push한다.

### 기본 이미지 발행

이후 사용자가 기본 이미지 발행을 요청했다. 8c7cf9339de77db60452c7d3a5ad67e9777ede66의 커밋된 image Dockerfile/고정 의존성으로 linux/amd64 이미지를 다시 빌드했다. 해당 커밋 해시 태그로 clothes-query-dev/spark-base에 발행했다. digest는 sha256:9548d0949843699f8722a4eb78551129ab718a340a618a06f088483c0ac7985f다.

네트워크 없는 로컬 일회성 컨테이너에서 Spark 4.2.0 / Python 3.10.12 / Java 21·주요 패키지 버전, JAR 10개 체크섬, 연결 클래스 로딩, 숫자 1,000개 합성 계산과 메모리 Parquet 왕복을 확인했다. 첫 검증은 일반 python3 실행에서 PySpark 경로를 지정하지 않아 실패했고 점검 스크립트에 공식 이미지의 /opt/spark/python 및 py4j 경로를 지정해 통과했다. 이미지·업무 코드의 변경은 필요하지 않았다.

업로드 후 최초 식별자 비교는 Docker의 manifest ID를 config digest와 비교해 실패했다. 각각 대응하는 manifest/config 식별자로 대조해 원격 이미지와 검증 이미지가 일치함을 확인했다. 잘못된 이미지를 다시 발행하거나 immutable 태그를 덮어쓰지 않았다. 임시 Docker 인증 설정은 로그아웃 후 제거했다.

동료의 SPARK_IMAGE 인자와 업무 빌드·push 명령을 handoff에 정리했다. 업무 이미지 발행·Spark 실행 권한·network 적용·노드 기동·업무 실행·Git push/PR/머지는 하지 않았다.
