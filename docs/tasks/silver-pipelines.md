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

## 승인된 추가 작업: 클릭・상품 Silver

- 사용자가 선택한 클릭・상품의 문서 기반 구현을 진행한다. 리뷰 경로 수정과 회원 코드는 포함하지 않는다.
- `clicks.py`: 이벤트 키 중복/충돌, 조회·담기 허용 값, UTC・KST 변환, 정상/격리/품질 결과.
- `products.py`: 원천 DDL 컬럼의 디자인/상품 스냅샷 검사, 중복/충돌, 디자인 연결 대기와 오류 구분.
- `common.py`: 기존 거래 입출력과 기본 검사 재사용. 거래 CLI와 정상 반환 구조를 유지한다.
- 테스트 파일은 `tests/test_clicks_products.py` 1개만 추가한다. 회원・리뷰・거래 기존 테스트를 함께 확인하고 문서 기반 합성 데이터로 클릭/상품 CLI를 실행한다.
- 실제 CDC/S3/Parquet 입력, YAML 공통 검사기, 날짜・상품 부분 재처리, Gold A 코드 변경은 포함하지 않는다.

### 작업 결과: 클릭・상품 Silver

- **변경:** 클릭 정제・이벤트 중복/충돌・UTC/KST 시각, 디자인/상품 원천 컬럼 정제・키 중복/충돌・디자인 연결 검사. 각 처리에 정상/격리/품질 결과와 로컬 CLI 제공. 공용 읽기・저장을 common.py로 이동해 거래에서도 재사용.
- **검증:** Silver 테스트 13개 통과(기존 회원・리뷰・거래 포함). 원격 main의 상품 DDL과 디자인/상품 출력 컬럼 집합 일치 확인. 합성 JSONL로 클릭 CLI 결과 정상 2행・격리 1행・품질 1행, 상품 CLI 결과 디자인 1행・상품 1행・격리 1행・품질 2행 확인. `git diff --check` 통과.
- **확인 위치:** `pipelines/silver/.local/clicks-products-md-demo/output/silver/clicks/current.json`, 같은 output 아래 `silver/products/current.json`. 합성 입력・출력은 커밋하지 않는다.
- **다음 연결:** 실제 Bronze/스냅샷 형식과 S3・Parquet 연결, 부분 재처리, 공통 규칙 적용, Gold A 연결. 리뷰・회원 코드 변경 없음.

## 승인된 추가 작업: 리뷰 경로・최신 main 호환성

- 최신 origin/main을 Silver 브랜치에 병합하고 원천 LakeSink 경로에 맞춘다. 기존 작업과 로컬 자료는 보존한다.
- 리뷰 입력은 year/month/day와 기존 dt를 모두 지원하고 출력 KST dt는 유지한다. 입력 파일 없음과 정상 0건을 구분한다.
- 기존 리뷰 테스트 파일에서 최신 생산자 LakeSink 입력・구형 중복・UTC/KST 경계・반복 실행・S3 목록・입력 없음 보호를 확인한다. 실행 중 AWS 쓰기는 하지 않는다.
- Silver 테스트 전체와 기존 Gold A 리뷰/거래 연결 호환성을 확인한다. 브랜치 대장 자기 영역 등록.

### 작업 결과: 리뷰 경로・최신 main 호환성

- **변경:** 원격 main `9bbc29f`를 병합. 리뷰 입력 year/month/day와 기존 dt를 모두 읽고 review_id로 중복 정리. 출력 KST dt와 Gold A 인터페이스 유지. 운영 입력 파일을 못 찾으면 기존 출력을 보존하고 실패한다.
- **검증:** Silver 테스트 16개 통과. 최신 main의 LakeSink를 직접 호출한 파일과 Silver 연결, 새/구형 파티션 중복, S3 목록 호출(모의), 입력 없음과 명시적 0건 구분 확인. 기존 Gold A 리뷰 연결 테스트를 구형/신규 경로로 각각 실행해 2개 통과, 거래 연결 테스트 1개 통과. Gold A 소스 파일은 변경하지 않고 브랜치 내용을 메모리에서 실행했다. `git diff --check` 통과, origin/main이 현재 브랜치의 조상임을 확인.
- **기록:** README 입력 경로와 원천 상품 키 설명 갱신. 최신 브랜치 규칙에 따라 docs/BRANCHES.md의 silver 구역과 구조도 등록.
- **한계:** AWS 읽기/쓰기를 실행한 결과가 아니라 로컬 합성 입력과 S3 목록 모의 검증이다. 실제 거래 CDC/S3, 부분 재처리, 공통 YAML 실행 연결은 후속 범위다. push・PR 생성・main 머지는 별도 사용자 승인 후 진행한다.
