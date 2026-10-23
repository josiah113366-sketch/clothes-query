# 비활성 Spark 실행 기반 통합 공유

상태: 초안 PR #75 공유, 2026-10-23 후속 코드·이미지·권한 계획 검증 완료, AWS 적용·팀원 입력 대기

## 범위

사용자 승인으로 최신 main `0312bad`에서 원본 `infra/spark-runtime-prep` `c311785`을 통합한다. 원본은 보존한다. 노드 기본 비활성·업무 Job 미생성을 유지한다. 기존 합성 시험은 업무 데이터 성능·S3 입출력/Pod Identity 검증을 대신하지 않는다.

## 작업 결과

기본 이미지·연결 라이브러리, namespace/계정/RBAC/자원 렌더, Driver 1개·Executor 동적 1~2개, t3a.large 한 대분 opt-in NodePool과 로컬 권한 병합 도구를 공유한다. ECR push 개발자 de-ai-18은 확정했지만 실제 권한 적용은 미완료다. namespace·요청 JSON·최종 업무 이미지/인자·커미터·고정 검증 입력/기대값·Glue 공개 명세는 대기한다.

Gold B Kafka 직접 입력 Streaming은 별도 상시 작업 설계로 인지했다. 이 배치 준비만으로 Streaming 운영 배치·자원·checkpoint가 확정됐다고 해석하지 않는다. 현재 작업에서는 실행 코드·권한·노드를 추가로 변경하지 않는다.

## 완료 확인

- [x] 최신 main에서 새 공유 브랜치, 원본 보존.
- [x] enabled=false·업무 Job 기본 미생성 유지.
- [x] Python 회귀 20개, dedicated/shared/custom 3개 렌더 및 미정 권한 계획 렌더 통과. 업무 Job 미생성 확인.
- [x] Terraform fmt, 격리 compute stack/test root validate 및 mock plan 7개 통과. backend·AWS/Kubernetes 자격증명 없음.
- [x] 초안 PR #75 공유 완료. 팀원 검토·승인·머지는 대기.

## 2026-10-23 후속 작업

사용자가 받은 명세로 가능한 준비를 진행하고 나머지는 전달용 메일로 작성하도록 요청했다. 최신 main 965fd73을 반영해 Gold B 뷰·리뷰 점수 작업을 보존했다. 커밋 908c252는 원격 fetch와 GitHub commit 조회에서 확인되지 않아 업무 코드를 검증한 것으로 표시하지 않는다.

계정은 silver-gold-a-submitter/driver/executor로 선택했고 namespace 공유는 미정으로 유지한다. --existing-namespace 렌더는 Namespace/ResourceQuota를 생성하지 않는다. 기본 이미지에 받은 패키지 4개와 해결한 전이 버전을 고정하고 로컬 설치·실제 import·메모리 Parquet 왕복·KST·네트워크 없는 Spark 계산과 커넥터 클래스 로딩을 확인했다. 기본 이미지 영구 ECR 발행과 업무 코드 실행은 별개다.

ECR 모듈은 opt-in Spark 저장소 2개와 같은 계정 개발자 IAM 사용자 push 정책을 추가한다. 실제 Terraform plan은 저장소 spark-base/silver-gold-a와 de-ai-18 정책 3개 create만 보이며 기존 저장소 변경·삭제·교체는 없다. plan/상세 출력은 Git 제외 경로에 보관했다. 실제 apply·이미지 push는 하지 않았다.

별도 spark-access 스택은 namespace=null·enabled=false라 실행 역할/Pod Identity를 생성하지 않는다. 거래 Bronze·요청/입력 manifest 읽기, 출력 Get/Put·multipart 조회/중단, DeleteObject는 runs/<run_id>/<dataset>/__magic_job-* 작업 객체만 허용하는 구조다. 버킷 multipart metadata listing은 실제 커미터 설정 확인 전 false다. network endpoint action 검토안은 별도 예시 파일이고 공유 network 설정·기존 workload-access binding은 변경하지 않는다.

아직 필요한 정보는 namespace 공유 최종 확인, 원격 업무 코드, 고정 요청/입력/상품 기준정보/기대값, 실제 커미터 설정·작업 객체 예시, completed_at과 Glue 공개 DDL이다. handoff/email-to-pipelines.md에 메일 문안을 작성했으며 외부로 전송하지 않았다. Spark 노드·업무 Pod·테스트 S3 데이터·Glue 표를 생성하지 않았다.

최종 확인: Python 회귀 21개, shared namespace 소유권을 건드리지 않는 10개 객체 렌더, Terraform fmt·ecr/spark-access/test root 격리 validate, 기존 compute·ECR 회귀를 포함한 mock plan 18개 통과. 최종 고정 패키지 이미지 빌드·pip check·실제 import·Parquet/KST·로컬 Spark/커넥터 실행 통과. 로컬 시험 컨테이너는 --rm으로 종료했다. ECR 실제 plan은 create 3개뿐이며 apply하지 않았다. plan과 이미지 발행이 필요한 마지막 단계는 별도로 구분한다.

후속 원격 push는 자동 승인 검토가 이 변경에 대한 구체적 사용자 확인 부족으로 차단했다. 기존 PR #75는 열려 있지만 이 후속 코드·메일은 로컬 커밋에만 있다. 차단을 우회하지 않았으며 실제 AWS 적용·이미지 발행도 미완료다.
