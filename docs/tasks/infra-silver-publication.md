# Silver·Gold A 조회 공개 연결

상태: DDL·권한·Airflow 적용 및 정상 거래·Athena 공개 검증 완료. 브랜치: `infra/applied-state-sync`.

## 결정과 범위

2026-10-24 사용자는 #104의 최종 이미지·DDL·공개/재처리 계약 전달 뒤 실행을 요청했다. main 3d046f3을 먼저 반영했다. 이미지 digest는 `sha256:d00fdded7e53e8c6c9dbd2bb430695a5c7c15fddc133828123c5a7d9a642fdad`이며 ECR 존재와 main 커밋 태그를 확인했다.

거래 정상 배치 하나와 Athena 공개 확인을 우선한다. 기존 dedicated 자원·노드 한도·Spark 4.2.0/Python 3.10을 유지한다. 리뷰 Athena 조회/퍼널·리뷰 출력 권한, 원본 수정·부분 재처리·승인 이벤트 생성은 이번 실행에 포함하지 않는다.

## 적용

- 앱 DDL 세 파일의 12문장을 배포 권한으로 실행해 DB 2개·표 10개를 준비했다. 기존 schema·location 불일치 시 중단하도록 대조했으며 projection은 false다. 업무 행 INSERT는 하지 않았다.
- Spark 접근 정책 4개 추가·기존 2개 업데이트. 기존 역할·Pod Identity는 유지하고 새 정상 실행의 Parquet rollback 경로만 추가했다. 적용 뒤 plan 변경 없음이다.
- Driver는 거래 표 파티션 등록만 가능하며 DB·표 생성/변경은 불가하다. Executor는 Bronze v2 읽기만 추가했다. 판정은 Silver 완료 목록·공개 금액 검사 결과 읽기만 추가했다. 원본·정답표·agent 결과 쓰기나 이벤트 삭제는 열지 않았다.
- 실제 IAM 허용·차단 10개가 통과했다. Terraform 24 roots·23 mock suites/103 plan, runtime 준비 검사 5개가 통과했다.
- Airflow 신규 ConfigMap과 환경 변수 참조를 적용했다. 기존 Secret·agent·GitDagBundle·이미지·자원을 보존했고 같은 chart 1.22.0/앱 3.3.2를 유지했다. Ready 확인 후 trade DAG만 수동 1회 실행한다. 기존 5분 판정 활성과 다른 업무 DAG의 paused 상태를 보존한다.

## 정상 시험

이전에 성공한 거래 입력 5개를 같은 ETag의 고정 객체로 재사용한다. 새 요청·결과 실행 ID는 `trade-publication-20261024-104`, Airflow run ID는 `infra-publication-20261024-104`다. 입력에는 읽기 전용 상품 기준정보 두 객체와 이미 고정한 Bronze v2 스냅샷이 포함된다. 실제 입력 내용·원문 로그는 Git 제외 경로에만 저장한다.

완료 기준은 DAG 및 Driver/Executor 성공, Silver/Gold 완료·공개 기록, Athena 주문 1건·성공 결제 7,900원·수량 1개·보류 0건과 실행 ID 일치다. 결과는 지우지 않고 검증 로그를 보존한다. 실행 뒤 trade DAG를 원래 paused로 복구하고 이번 완료 Pod만 정리해 Spark 자원 비용을 종료한다.

## 작업 결과

거래 DAG의 check_request·submit_spark·publish_r6·publish_gold가 첫 시도에 모두 success이고 실패 전파 태스크는 skipped다. Driver 1개·Executor 2개 모두 exit 0이다. Silver/Gold 결과와 완료 목록이 PASS/COMPLETED이며 새로운 `dq_order_results`도 생성됐다.

Athena 집계 조회 6개에서 주문 1건·성공 결제 7,900원·판매 수량 1개·보류 0건·실행 ID 일치를 확인했다. 공개 금액 검사는 모두 PASS다. 실제 agent/detection-job ServiceAccount의 Pod Identity로도 Silver 표 2개의 Athena 조회가 성공했다(업무 쓰기 없음). 관리자 권한 조회만으로 판정 역할 연결 성공을 주장하지 않는다.

전체 Spark 준비 검사 26개가 통과했다. 초기 실행 도중 자원 표본은 Driver 580MiB, Executor 1개 365MiB, 제출기 300MiB였으나 전체 실행 최고치나 Executor 2개 합계로 해석하지 않는다. 이번에는 기존 dedicated 자원을 축소하지 않았다.

trade DAG는 원래 paused로 복구했다. 완료 Spark Pod 3개의 전체 로그를 비공개 로컬과 S3에 보존·해시 대조한 뒤 해당 UID의 Pod만 삭제했고, 읽기 시험 Pod도 정리했다. 사용자 비용 절감 의도에 맞춰 다른 일반 workload가 없는 이번 전용 노드만 확인하고 NodeClaim을 명시적으로 삭제했다. EC2 terminated·Spark 노드 0대·NodePool 설정 불변을 확인했다. 정상 자동 축소 대기 10분을 다시 측정한 결과로 표현하지 않는다. 업무 결과와 완료 목록은 보존했다.

부분 재처리·MISMATCH 복구 시험과 대시보드 등 최종 소비자 권한, 리뷰 Athena·퍼널/리뷰 실행은 후속이다. 원본 수정·운영 승인 이벤트를 생성하지 않았다.
