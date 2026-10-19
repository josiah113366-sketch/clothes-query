상태: 진행 중

# Gold A 지표 분리

브랜치: `gold-a/metrics`. 최신 `main`에서 생성한 뒤 선행 `silver/pipelines` 커밋을 포함한다. Silver 브랜치가 먼저 반영되면 이 브랜치의 PR 차이는 Gold A 파일과 이 작업 문서만 남는다.

## 범위

- Silver 리뷰를 이용한 상품별 일간 리뷰 집계와 상품·기간·키워드 조회.
- 거래 Silver를 이용한 KST 시간별 주문·승인 금액과 결제일·`article_id`별 판매 수량·금액.
- 회원 Gold 분석은 제외한다. 실제 거래 Bronze 연결과 리뷰 AI 분석 결과 연결은 아직 없다.

## 완료 확인

`python -m pytest pipelines/gold_a/tests -q -p no:cacheprovider --basetemp pipelines/gold_a/.local/pytest-branchsplit`와 `python -m unittest pipelines.test_transactions_flow`를 실행한다.


## 승인된 추가 작업: 최신 Silver manifest·품질 결과 연결

- 사용자 진행 승인에 따라 기존 리뷰·거래 집계가 최신 Silver 저장 결과를 읽도록 연결한다. 퍼널·AI 집계·새 지표·상품 키 변환은 제외한다.
- gold-a/metrics의 기존 Gold A 커밋 하나를 최신 silver/pipelines(7e57ae6) 위로 로컬 rebase한다. Silver가 먼저 main에 반영되어야 후속 PR 차이가 Gold A만 남는다. 원격 브랜치는 변경하지 않는다.
- 기존 reviews.py/transactions.py와 __init__.py를 수정한다. __init__.py에서 기존 리뷰 입출력 함수를 공유하고 Silver manifest·실제 dq_results 검사와 입력 추적을 제공한다. 새 코드 파일은 만들지 않는다.
- Gold 결과도 완료 묶음 저장 후 current.json으로 공개한다. 품질 미완료·필요 파일 없음·읽기 실패 시 갱신 중단과 기존 결과 보존.
- 기존 테스트 두 파일에서 최신 생산 경로·반복 실행·정상 0건·INCOMPLETE·manifest와 품질 결과 불일치를 확인한다.

## 작업 결과

- **변경:** 거래 로컬 CLI·대표 Silver 결과 읽기, 리뷰 요청 범위 manifest와 신규 KST 날짜 파일 읽기, 품질 상태 확인 후 기존 3개 집계 생성. 키워드 검색도 동일 품질 검사를 적용한다.
- **저장:** Gold A current.json에 결과 파일과 사용한 Silver manifest·경로·검사 버전·품질 결과를 남긴다. 모든 파일 완료 후 교체하며 과거 실행을 합치지 않는다.
- **검증:** 연결 테스트 4개 통과. 리뷰 원본→Silver→Gold A, 정상 0건·반복 실행, 불완전 품질/누락 입력 때 기존 Gold 보존, manifest만 PASS인 경우도 실제 DQ로 차단. 거래 파일 입력→Silver→Gold A에서 승인 금액·상품 키·반복 결과 일치 및 품질 오류 때 이전 결과 보존 확인.
- **한계:** 실제 AWS·거래 Bronze 검증 아님. 모든 PASS가 원천 입수 완전성을 보증하지 않는다. Gold A의 새 명세 컬럼·퍼널·AI·부분 재처리·실패 이력 자동 저장은 후속 범위다. 실패 후 남은 이전 Gold의 입력은 manifest로 확인해야 한다.
- **다음:** 새 명세와 기존 컬럼 차이를 검토하고 상품 연결·추가 지표의 구현 범위를 승인받는다. push·PR 생성·머지는 별도 승인 후 진행한다.


## 승인된 추가 작업: Gold A 잔여 명세 구현

- 사용자 승인: 기존 집계 컬럼·상품 연결 → 퍼널 → 리뷰 속성 집계 → 날짜·상품 부분 재처리까지 구현 후 결과 비교.
- 기존 __init__.py/reviews.py/transactions.py 확장, funnels.py와 기존 tests/ 안의 통합 검증 파일 하나만 추가한다.
- 상품은 PASS인 Silver 기준정보로 검증한다. 리뷰 product_id는 정확히 일치하는 article_id 또는 명시적 매핑으로만 연결한다.
- 분석 입력은 명세의 review_id/aspect/sentiment/model_version을 사용한다. 현 모델 CSV(review_id,aspect,score)는 명시적 모델 버전·score-sign.v1 변환으로 지원한다. 모델 추론·truth 사용은 하지 않는다.
- 퍼널은 제공된 전체 입력 이력 내 동일 세션·상품만 연결한다. 임의의 전환 마감시간을 넣지 않는다. 운영상 재계산 기간은 이번 배치 계산과 구분한다.
- 부분 재처리는 전체 입력을 계산한 뒤 선택 날짜·상품·모델 결과만 기존 완료 묶음에 교체한다. 원천 입력 일부를 읽는 최적화·Silver 부분 병합·자동 DAG는 포함하지 않는다.
- 공통 코드 정상·격리 정책은 유지하고 Gold A의 연결/분석 입력 오류는 전체 갱신을 중단한다.


## 작업 결과: Gold A 잔여 명세 구현

- **기존 집계:** rating_sum·low_rating_rate 출력, 평균 4자리/비율 6자리 HALF_UP, PASS인 상품 기준정보로 article_id/product_code 연결. 리뷰 별칭은 명시적 JSONL 매핑만 허용하며 연결 실패는 중단한다. 기존 상품 연결 없는 실행은 호환용으로 유지한다.
- **퍼널:** funnels.py 하나에 세션·상품 상세와 첫 조회일 집계를 구현. 반복 조회·담기 없는 구매·다음 날 성공 결제를 처리하며 소요 시간·임의 만료시간은 추가하지 않는다. 입력 전체 이력을 계산한다.
- **속성:** reviews.py에 모델 버전별 review_id/aspect/sentiment 집계, 동일 분석 중복 제거·충돌/미등록 키 검사. 현 score_batch.py의 CSV 형식 지원 및 score-sign.v1 정책 기록. 결과 없는 리뷰는 중립으로 처리하지 않고 완료 여부 UNVERIFIED 기록.
- **부분 재처리:** 전체 입력 재계산 후 선택 날짜·상품·모델의 기존 행을 제거하고 새 결과로 교체. 0건 제거·타 범위 보존·이전 입력/출력 이력 보존. 시간별 전체 주문 지표는 선택 날짜 전체를 재계산한다. Silver 부분 처리·자동 DAG는 구현 범위가 아니다.
- **검증:** Silver+Gold A 테스트 28개 통과. 통합 시나리오 테스트 파일 1개 추가, 기존 리뷰 기대값 갱신. 일반 연결·품질 차단에 더해 상품 연결, 직접 구매, 늦은 결제, score CSV, 분석 충돌, 부분 교체·타 상품 보존·0건 제거·재실행 확인. git diff --check 통과.
- **검토 자료:** pipelines/gold_a/.local/demo-20261019/report.md. 문서 기준 합성 입력에서 6개 결과 생성 및 기대/실제 20항목 일치. input/, silver/, gold/, summary.json을 같은 실행 폴더에 보존한다. 이 자료는 커밋하지 않는다.
- **근거:** 사용자가 작성·승인한 Gold A 명세, db/schema 상품·거래 정의, review-analysis/deploy/README.md·score_batch.py의 CSV/점수 의미와 review-simulator taxonomy.py의 11개 라벨.
- **한계:** 로컬 Python JSONL 실행 검증이다. 실제 AWS·거래 CDC·실제 상품 매핑·모델 추론/완료 목록·Parquet/Glue 타입·Spark/Airflow 운영·동시 쓰기 잠금은 별도다. 부분 교체는 기존과 같은 전체 출력 범위 내에서 수행하며 자동 영향 범위 탐색·Silver→Gold 자동 재처리는 아니다.
- **제출:** 로컬 Gold A 커밋까지만 진행한다. 선행 Silver PR #21의 최신 로컬 변경 반영·머지 이후 Gold A PR 차이를 확인해야 하며 push·PR·머지는 별도 승인 대상이다.
