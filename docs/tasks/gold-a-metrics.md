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
