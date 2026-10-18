상태: 완료

# Silver 파이프라인 통합

브랜치: `silver/pipelines`. `main`을 기준으로 이미 검증한 회원·리뷰·거래 Silver 파일만 모은다. Gold A 코드와 테스트는 `gold-a/metrics` 브랜치로 분리한다.

## 입력과 남은 연결

- 회원: 실제 초기 Bronze 스냅샷으로 `members_current` 생성 확인. 이후 변경·탈퇴 이벤트 검증은 남았다.
- 리뷰: 운영 `reviews/` JSONL을 KST 작성일별로 정제하고 날짜 범위 재처리한다.
- 거래: 합의된 주문·주문상품·결제 컬럼의 순수 계산 규칙을 구현했다. 실제 CDC 봉투와 S3 Bronze 연결은 샘플 확인 후 진행한다.

## 승인된 추가 작업: 거래 오류 분리

- 기존 거래 코드가 정상 결과 4개와 함께 격리 기록·품질 요약을 반환하도록 수정한다.
- 행 오류는 격리, 연결 주문 없음은 대기, 키 충돌은 해당 키 전체 보류로 처리한다. 프로그램 오류는 호출자에게 전달한다.
- 코드 파일을 추가 분리하지 않는다. 검증은 `pipelines/silver/tests/test_transactions.py` 한 파일에서 오류와 정상 데이터 공존·충돌·연결 대기·재실행을 확인한다.
- S3/CDC 연결, YAML 공통 검사기, Gold A 변경, 이전 실행의 결과 갱신은 이번 범위에 포함하지 않는다.

## 완료 확인

`python -m pytest pipelines/silver/tests -q -p no:cacheprovider --basetemp pipelines/silver/.local/pytest-branchsplit`로 기존 Silver 동작을 확인한다. 거래 계산은 Gold A 브랜치의 연결 테스트에서 함께 확인한다.

추가 확인: 거래 테스트와 기존 Silver 테스트를 실행하고, 기존 Gold A 연결 테스트를 파일 변경 없이 새 Silver 결과로 확인한다. `git diff --check` 확인.

## 작업 결과: 거래 오류 분리

- **변경:** `transactions.py`에서 정상 상세 4개와 `quarantined_records`, `dq_results` 반환. 행별 오류와 연결 대기, 동일 키 충돌을 구분한다. 주문의 오류 변경을 누락한 채 과거 상태를 최신 상태로 내보내지 않도록 해당 주문은 보류한다.
- **기록:** 각 격리 행은 입력 목록 행 번호·업무 키·오류 필드·사유·검사 코드 버전을 남긴다. 원문과 회원 속성은 복사하지 않는다. 품질 요약은 원천별 집계와 영향 주문·입력 행을 남기며 오류가 있으면 INCOMPLETE다.
- **검증:** `python -m pytest pipelines/silver/tests -q -p no:cacheprovider --basetemp pipelines/silver/.local/pytest-transaction-quality`: 7개 통과. `gold-a/metrics`의 기존 거래 연결 테스트를 메모리에서 새 Silver 함수로 실행: 1개 통과. `git diff --check` 통과.
- **한계:** 실제 파일 저장과 이전 실행의 충돌 확인, 영구 원본 위치·실행 이력, 규칙 YAML 실행 연결은 다음 입력 연결 작업 범위다. 후속 집계/저장 코드는 정상 상세만 쓰지 말고 모든 품질 결과의 영향 범위를 확인해야 한다.
- **범위:** 거래 코드·Silver README·기존 작업 지시서 수정과 거래 테스트 파일 1개 추가. 회원·리뷰 코드, Gold A 코드와 공통 계약 PR은 수정하지 않음.
