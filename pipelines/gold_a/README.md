# Gold A 기본 집계와 Silver 연결

## 목적과 범위

Silver가 완료한 결과 묶음 하나를 읽어 기존 주문·상품 판매·리뷰 지표를 만든다. `silver/pipelines`의 manifest·품질 결과 인터페이스를 사용한다.

| 기능 | 입력 | 결과 |
|---|---|---|
| 주문·상품 판매 | 거래 Silver current.json | order_sales_hourly, product_sales_daily |
| 상품별 일간 리뷰 | 요청 범위의 리뷰 Silver current.json | review_product_daily |
| 상품·기간·키워드 조회 | 같은 리뷰 Silver 결과 | 명시한 JSONL에 리뷰 목록 |

이번 변경은 기존 지표의 파일 연결과 품질 확인이다. 새 Gold A 명세의 product_code, rating_sum 출력, low_rating_rate, 퍼널, AI 속성 집계는 구현하지 않는다. 리뷰는 원천 product_id를 유지하며 임의로 article_id로 바꾸지 않는다.

## Silver 읽기 규칙

1. 아래 대표 manifest 하나를 먼저 읽는다. runs/ 전체를 합치지 않는다.
2. manifest.status=PASS인지 확인하고, 실제 dq_results가 전부 PASS·격리 0건인지 다시 검사한다.
3. 필요한 결과 파일이 모두 있고 읽을 수 있어야 계산한다. 리뷰는 요청 날짜·리뷰 키·별점·범위 전체 review_id 중복도 검사한다.
4. INCOMPLETE·품질 결과 누락·입력 읽기 실패 때 Gold A 갱신을 중단한다. 정상 행만 남았다는 이유로 완전한 집계를 만들지 않는다.

| 입력 | 대표 manifest |
|---|---|
| 거래 | `<silver-root>/silver/transactions/current.json` |
| 리뷰 | `<silver-root>/silver/reviews/scopes/<시작일>_<종료일>/current.json` |

리뷰 요청 범위는 Silver를 실행한 범위와 정확히 같아야 한다. 서로 다른 scopes를 자동 병합하거나 단일 날짜 manifest로 대체하지 않는다. 이전 고정 dt/year/month/day 파일 직접 읽기는 지원하지 않는다.

## 실행

저장소 루트에서 실행한다. 루트 경로는 해당 silver/ 또는 gold_a/ 폴더의 부모다.

```powershell
python -m pipelines.gold_a.transactions --silver-root <거래-Silver-출력-루트> --output-root <Gold-출력-루트>
python -m pipelines.gold_a.reviews aggregate --silver-root <리뷰-Silver-출력-루트> --output-root <Gold-출력-루트> --start-date 2026-10-08 --end-date 2026-10-08
python -m pipelines.gold_a.reviews search --silver-root <리뷰-Silver-출력-루트> --start-date 2026-10-08 --end-date 2026-10-08 --product-id <원천-상품-ID> --keyword 지퍼 --output pipelines/gold_a/.local/review-matches.jsonl
```

거래는 현재 로컬 입출력만 지원한다. 리뷰는 기존 로컬/S3 입출력을 유지하며 S3에만 boto3·권한이 필요하다. 이번 확인에서는 실제 AWS를 호출하지 않는다.

## Gold A 결과 읽기와 재실행

| 결과 | 대표 manifest |
|---|---|
| 주문·상품 판매 | `<output-root>/gold_a/transactions/current.json` |
| 상품별 리뷰 | `<output-root>/gold_a/review_product_daily/scopes/<시작일>_<종료일>/current.json` |

manifest의 outputs가 가리키는 파일만 읽는다. 거래는 두 데이터셋 JSONL, 리뷰는 실행 폴더 안의 KST year/month/day JSONL이다. inputs에는 사용한 Silver manifest·출력 파일 경로·검사 버전·품질 결과를 남겨 어떤 입력으로 계산했는지 추적한다.

모든 결과를 계산·저장한 뒤 current.json을 교체한다. 입력·계산·저장 실패 시 이전 대표 결과를 보존한다. 같은 입력을 재실행해도 집계 행·금액이 늘어나지 않는다. 실패한 실행의 미공개 파일은 남을 수 있지만 소비하지 않는다. 과거 실행 자동 삭제·동시 실행 잠금·겹치는 범위 병합·상품 부분 재처리는 제공하지 않는다.

기존 dt 결과 파일은 이동·삭제하지 않는다. 새로운 결과는 위 manifest로 읽어야 한다. 갱신이 막히면 이전 Gold A가 남으므로 소비자는 inputs를 보고 사용한 Silver 실행을 구분해야 한다. 실패 이력 자동 저장·알림은 이번 범위가 아니다.

## 계산 기준

- order_sales_hourly: KST 주문 시각의 주문 수, KST 성공 결제 시각의 성공 주문 수·승인 금액.
- product_sales_daily: KST 성공 결제일 × article_id의 성공 주문 수·판매 수량·주문상품 금액. 상품 ID 앞자리 0 보존.
- 금액은 취소·환불 차감 전이다. 현재 상품 가격으로 주문 당시 단가를 대체하지 않는다.
- review_product_daily: KST 리뷰 작성일 × 원천 product_id의 리뷰 수·평균 별점·1~2점 리뷰 수. 평가용 reviews_truth는 사용하지 않는다.
- 키워드 검색은 원문 부분 문자열 비교이며 검색 품질을 보증하지 않는다. 원문 출력은 .local/ 등 공개 저장소 밖에 둔다.
- PASS는 입력 검사 통과이며 원천 입수가 완전하거나 최신이라는 보증은 아니다. 실제 Bronze 연결·입수 범위 확인은 별도다.

## 검증

기존 두 테스트 파일에서 원본→Silver→Gold A 연결, 재실행, 품질 미완료 차단과 이전 결과 보존을 확인한다. 새 테스트 파일은 추가하지 않는다.
