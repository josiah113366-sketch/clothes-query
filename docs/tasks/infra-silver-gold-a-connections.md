# Silver·Gold A 첫 거래 실행 연결 준비

상태: 코드·로컬 검증 준비, 실환경 미적용

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

실제 AWS 계획: ECR 저장소 spark-base·silver-gold-a와 de-ai-18 사용자 이미지 push inline 정책, 총 3개 생성. network는 S3 endpoint 정책 1개 update뿐이고 삭제·교체는 없다. 역할 enabled plan은 endpoint 선행 변경 후 다시 확인한다. terraform validate 및 mock 검사는 통과했다.

현재 Airflow 실제 Helm values를 읽어 overlay 병합 호환성을 확인했다. 기존 extraEnv 1개와 Git bundle을 보존하며 새 runtime 참조 하나만 추가한다. 실제 digest는 없으므로 placeholder ConfigMap을 저장하거나 적용하지 않았다.

프리뷰와 적용을 분리했다. namespace 공유와 같은 namespace 내 ServiceAccount 선택은 강한 보안 경계가 아니므로 역할 분리만으로 완전한 격리를 주장하지 않는다. Glue 공개·재처리 SILVER 기록 작성·Gold B 상시 Spark 및 agent 권한은 이 변경에 섞지 않는다. 실제 이미지 digest·네트워크/IAM 적용·노드 활성화 이후에 별도 수동 검증한다. 현재 AWS apply·노드 기동·업무 실행·push·PR·머지는 하지 않았다.
