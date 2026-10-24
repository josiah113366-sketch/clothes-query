# Silver·Gold A 실행 자원 및 결과 공개 명세 후속

상태: 구현·로컬 검증 완료, PR 검토 대기

브랜치: `pipelines/runtime-followup` (최신 main `fe48119` 기준)

## 목적과 범위

- 머지된 PR #82 이후 업무 DAG 자원을 인프라 dedicated 프로필에 맞춘다.
- 실행 ID 고정 조회 방식의 Glue·Athena 공개 검토안을 공유한다.
- 발행된 기본 이미지로 수행한 업무 이미지 후보 검증 결과를 보존한다.
- 인프라 리소스·IAM·커넥터·Gold B 코드·형식 규칙은 변경하지 않는다. 브랜치 대장은 별도 취합한다.

## 작업 결과

- Driver heap 512m, Executor CPU 요청 500m, shuffle 파티션 4 및 제출기 자원·SPARK_DRIVER_MEMORY를 기존 인프라 코드에 정렬했다.
- 로컬 Airflow 실제 DAG 파싱·Pod 렌더링 및 인프라 자원 프로필 일치 검사를 통과했다. 변경 DAG Ruff(py310)·diff 검사도 통과했다.
- 공개 검토안은 [공개 명세](../contracts/silver-gold-a-publication.md)에 있다. DB·표·완료 목록·completed_at·R6 순차 소비·카탈로그 공개 코드는 아직 구현·배포하지 않았다.
- 이미지 후보는 원래 소스 커밋 `19027bb`로 빌드했다. 소스 파일 18개·패키지·JAR·Spark 실행 검사 및 고정 거래 입력(정상 주문 1건·7,900원·판매 수량 1개)의 독립 기대값 비교를 통과했다. Silver/Gold PASS이며 보류는 없다.
- 새 브랜치로 커밋을 재적용했으므로 기존 이미지 code_ref를 새 HEAD로 표시하지 않는다. main 반영 후 최종 main 커밋으로 이미지를 빌드·발행한다.
- 상세 검증과 수신 요청은 [기존 작업 기록](pipelines-runtime.md)에 보존했다. ECR 업무 이미지 push·EKS 업무 실행·Athena/Glue 변경은 수행하지 않았다.

## 검토·다음 작업

- 재영: 자원 프로필 정렬과 공개 명세의 카탈로그·권한 검토.
- 사용자 검토 및 main 머지 후, 최종 main 코드와 기본 이미지 digest로 업무 이미지를 발행하고 최종 ECR digest를 전달한다.
- 실제 S3→EKS Spark 입출력 검증, R6 완료 목록·Athena 공개, 승인 화면→Silver 재처리 DAG는 별도 구현한다.
