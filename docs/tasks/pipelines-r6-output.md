상태: 진행 중 · 브랜치: `pipelines/r6-output`

# R6용 Silver 주문 금액 검사 결과 제공

## 목적과 제출 범위

기존 금액 검사를 유지하며 주문별 출력·실행 시각/ID·고정 manifest만 추가한다. 최신 main 기반이며 Gold A·Kafka 원본 추적(#35)·단가 하한 변경은 포함하지 않는다. 별도 코드/테스트 파일은 만들지 않고 브랜치당 지시서 규칙에 따라 이 작업 기록만 분리한다.

## 작업 결과와 과거 검증

## 2026-10-21 승인된 R6 조회 결과 제공

- 사용자가 승인한 범위: 기존 amount_checks를 주문별 order_amount_checks로 펼치기, checked_at(UTC)·run_id·고정 source_manifest 연결, 실행별 manifest.json 저장 후 최신 참조 공개. 기존 common.py/transactions.py·테스트·README만 수정하며 새 코드/테스트 파일은 만들지 않는다.
- Silver의 금액 판정 규칙은 유지하고 R6 알림/이상 지속·해소 판단·S3/Athena·DAG는 구현하지 않는다. 검사 불가 상태는 금액 오류와 구분하고 행이 없다는 이유로 해소를 추정하지 않는다.
- 작업 결과: transactions.v7에서 order_amount_checks 출력과 items-sum-v1 검사 이름/버전/금액/상태를 제공한다. 공용 로컬 저장 단계가 거래 결과에만 실행 ID·검사 완료 시각·고정 참조를 연결하고 실행 manifest를 저장한다. 기존 업무 출력·current.json 소비는 호환 유지한다.
- 검증: 기존 거래 테스트에서 MISMATCH→동일 주문 재검사 MISMATCH→PASS, 실행 ID 변경·UTC 시각·과거 고정 기록 보존·UNVERIFIED/PENDING_REFERENCE/ITEM_ERROR의 null 금액·고정 manifest 저장 실패 시 이전 공개 결과 및 실행 폴더 보존을 확인했다. 최종 회귀 결과는 아래에 기록한다.
- 최종 검증: Silver·Gold A·거래 연결 테스트 49개 통과(8.24초), 변경 실행 코드 Ruff 및 git diff --check 통과. 실제 S3/Athena·판정 잡은 호출하지 않았다. 로컬 산출물은 pipelines/silver/.local/r6-all-20261021/ 아래에 보존한다.


위 49개 검증은 최초 Silver 작업 브랜치 기록이다. 이번 main 기반 검증과 혼동하지 않는다.

## 완료 확인

main 기반 Silver 회귀 테스트, 변경 실행 코드 Ruff, diff 공백 검사 및 Gold A/공통 YAML 변경 미포함을 확인한다. 일반 PR로 제출하고 주현의 입력 계약 검토를 요청한다. S3/Athena/판정 잡 연결은 후속이다.

## 이번 제출 검증 결과

- 최신 origin/main 기반 Silver 테스트 29개 통과(3.03초), common.py/transactions.py Ruff·git diff --check 통과.
- main 대비 6개 파일이며 Gold A·Kafka 메타데이터·공통 YAML/단가 정책 변경은 없다. 불일치 지속/해소의 실제 알림 판정이 아니라 제공 출력과 고정 근거·저장 실패 보호를 검증했다.
