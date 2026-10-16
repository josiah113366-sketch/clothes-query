상태: 완료

# Gold A 지표 분리

브랜치: `gold-a/metrics`. 최신 `main`에서 생성한 뒤 선행 `silver/pipelines` 커밋을 포함한다. Silver 브랜치가 먼저 반영되면 이 브랜치의 PR 차이는 Gold A 파일과 이 작업 문서만 남는다.

## 범위

- Silver 리뷰를 이용한 상품별 일간 리뷰 집계와 상품·기간·키워드 조회.
- 거래 Silver를 이용한 KST 시간별 주문·승인 금액과 결제일·`article_id`별 판매 수량·금액.
- 회원 Gold 분석은 제외한다. 실제 거래 Bronze 연결과 리뷰 AI 분석 결과 연결은 아직 없다.

## 완료 확인

`python -m pytest pipelines/gold_a/tests -q -p no:cacheprovider --basetemp pipelines/gold_a/.local/pytest-branchsplit`와 `python -m unittest pipelines.test_transactions_flow`를 실행한다.
