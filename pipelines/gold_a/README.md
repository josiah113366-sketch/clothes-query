# Gold A 리뷰 집계·원문 조회

선행 브랜치 `silver/pipelines`의 Silver 결과 `silver/reviews/dt=YYYY-MM-DD/part-00000.jsonl`을 입력으로 한다.

## 현재 구현 범위

| 기능 | 입력 | 결과 |
|---|---|---|
| 상품별 일간 리뷰 집계 | Silver 리뷰 | `gold_a/review_product_daily/dt=YYYY-MM-DD/part-00000.jsonl` |
| 상품·기간·키워드 조회 | Silver 리뷰 | 사용자가 지정한 JSONL 파일에 해당 리뷰 목록 |

모든 날짜는 KST 작성일이다. `review_product_daily`는 `product_id`별 리뷰 수, 평균 별점, 1~2점 리뷰 수를 남긴다. `product_id`는 현재 리뷰 시뮬레이터의 임시 값이므로 실제 거래 상품과 조인하기 전에는 매출과 연결하지 않는다. `reviews_truth/`의 시뮬레이터 라벨은 분석 결과로 사용하지 않는다.

## 실행

저장소 루트에서 실행한다. 루트 경로는 로컬 폴더 또는 `s3://버킷/접두사`다. S3를 쓸 때만 `boto3`와 읽기·쓰기 권한이 필요하다.

```powershell
python -m pipelines.gold_a.reviews aggregate --silver-root pipelines/silver/.local/lake --output-root pipelines/gold_a/.local/lake --start-date 2026-10-08 --end-date 2026-10-08
python -m pipelines.gold_a.reviews search --silver-root pipelines/silver/.local/lake --start-date 2026-10-08 --end-date 2026-10-08 --product-id W-0003 --keyword 지퍼 --output pipelines/gold_a/.local/zipper-results.jsonl
```

검색어는 원문의 **부분 문자열**로 비교한다(영문 대소문자 무시). `--product-id`를 빼면 모든 상품에서 찾는다. 검색 결과에는 리뷰 원문이 들어가므로 공개 저장소에 커밋하지 않는다. 명령은 콘솔에 원문 대신 결과 건수와 저장 경로만 출력한다.

`품질·내구성/부정`처럼 AI 속성·감성 조건을 붙이는 일은 분석 결과의 `review_id`·모델 버전·출력 경로가 결정된 다음 단계다. 키워드 검색이 충분한지도 소량의 수작업 확인 후 판단한다.

## 거래 지표 계산 규칙

`transactions.py`의 `build_gold(silver)`를 사용한다. 입력은 거래 Silver 결과다.

- `order_sales_hourly`: KST 주문 시각의 주문 수, KST 성공 결제 시각의 성공 주문 수·승인 금액.
- `product_sales_daily`: KST 성공 결제일 × `article_id`의 성공 주문 수·판매 수량·주문상품 금액.

이 금액은 취소·환불 차감 전 승인·상품 금액이다. 회원 분석·퍼널은 거래 계산 함수의 범위가 아니다.
