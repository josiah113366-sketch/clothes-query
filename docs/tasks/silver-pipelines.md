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

## 승인된 추가 작업: 문서 기준 로컬 거래 입출력

- 실제 거래 Bronze가 아직 없어 문서 컬럼의 JSONL로 진행하라는 사용자 지시에 따른다. 실제 CDC 포맷이나 S3 경로를 임의 확정하지 않는다.
- 기존 `transactions.py`에 명시적 세 입력 경로, JSONL 읽기, 원본 파일·행 번호, CLI, 결과 묶음 저장을 추가한다.
- 결과 6개 저장 완료 후 current.json만 교체해 읽기·쓰기 실패 시 이전 대표 결과를 보존한다. 지정 입력 전체를 처리하며 날짜·상품 부분 교체는 포함하지 않는다.
- 기존 거래 테스트 파일에서 반복 실행, 파싱 오류 원본 추적, 입력 없음·저장 실패 시 이전 결과 보존을 확인한다.
- 완료 확인: Silver 테스트, 합성 입력으로 CLI 실행, `git diff --check`.

### 작업 결과: 문서 기준 로컬 거래 입출력

- **변경:** 명시적 JSONL 파일/폴더 읽기, 파싱 오류 격리와 원본 파일·줄 추적, CLI, 결과 6개와 대표 결과 manifest 저장. 문서가 정한 업무 컬럼을 사용하며 CDC 봉투는 조용히 오해하지 않고 실행 오류로 알린다.
- **검증:** Silver 테스트 9개 통과. 정상·중복·실패 코드 누락을 포함한 합성 입력 CLI 실행 결과는 주문 현재 상태 2행, 상태 이력 2행, 주문상품 1행, 정상 결제 1행, 격리 1행, 품질 요약 3행. 반복 실행 후 같은 결과 건수 확인. 읽기·저장 실패 시 이전 current.json 보존 테스트 통과. `git diff --check` 통과.
- **로컬 확인 위치:** `pipelines/silver/.local/transactions-md-demo/output/silver/transactions/current.json`. 합성 입력·출력은 커밋하지 않는다.
- **한계:** 실제 S3 거래 Bronze·CDC 연결, 날짜·상품 부분 재처리, 공통 YAML 검사기, Gold A 파일 연동은 포함하지 않는다. 대표 manifest가 가리키는 결과만 읽어야 하며 과거 runs 전체를 합치지 않는다.
