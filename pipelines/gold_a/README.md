# Gold A: 주문·상품 판매·퍼널·리뷰 집계

## 구현된 결과와 한 행의 기준

| 데이터셋 | 한 행의 기준 | 결과 |
|---|---|---|
| order_sales_hourly | KST 1시간 | 주문 수·성공 주문 수·승인 금액 |
| product_sales_daily | KST 성공 결제일 × article_id | product_code, 성공 주문 수·판매 수량·주문상품 금액 |
| funnel_session_product | session_id × article_id | 첫 조회·담기·주문·성공 결제 시각, 도달 여부 |
| funnel_daily | 첫 조회 KST 날짜 × article_id | 단계별 방문 수와 전환율 |
| review_product_daily | 리뷰 작성 KST 날짜 × article_id | product_code, 리뷰 수·별점 합계·평균·1~2점 건수·비율 |
| review_aspect_daily | 리뷰 작성 KST 날짜 × article_id × aspect × model_version | 언급·긍정·중립·부정 리뷰 수·부정 비율 |

현재 실행은 Python 배치와 JSONL이다. Spark·Airflow·Parquet/Glue 스키마·실제 AWS 전체 연결까지 완료했다는 뜻은 아니다. 리뷰 모델을 실행하거나 truth 라벨로 판정을 대신 만들지 않는다.

## 입력과 상품 연결

| 입력 | 대표 manifest |
|---|---|
| 거래 | `<silver-root>/silver/transactions/current.json` |
| 클릭 | `<clicks-root>/silver/clicks/current.json` |
| 상품 | `<products-root>/silver/products/current.json` |
| 리뷰 | `<silver-root>/silver/reviews/scopes/<시작일>_<종료일>/current.json` |

manifest와 실제 dq_results가 전부 PASS·격리 0건이어야 한다. 필요한 파일 누락·연결 실패·분석 내용 충돌 시 갱신을 중단하고 기존 Gold 결과를 보존한다. PASS는 읽은 입력의 검사 통과이며 원천 입수 완전성·최신성을 보증하지 않는다.

판매는 article_id로 상품 기준정보와 연결한다. 리뷰는 product_id가 기준정보 article_id와 정확히 일치하는 경우만 직접 연결하며, 다른 값은 명시적 JSONL 매핑 `{ "product_id": "원천키", "article_id": "상품키" }`이 필요하다. 이름 유사도나 임의 변환을 사용하지 않는다. 연결 실패를 0건으로 숨기지 않는다.

기존 실행 호환을 위해 거래·기본 리뷰의 --products-root는 선택 옵션이다. 생략 시 기존 상품 키로 기본 집계하며 product_code는 추가하지 않는다. **아래 전체 명세 실행에는 --products-root를 전달한다.** 퍼널·속성 집계에는 상품 기준정보가 필수다.

## 실행: 동일한 Silver 루트에 각 데이터셋이 있는 경우

저장소 루트에서 실행한다. 아래 S와 G는 실제 로컬 Silver 출력 루트·Gold 출력 루트로 바꾼다. 상품 매핑이 필요 없으면 --mapping-path를 생략한다.

```powershell
python -m pipelines.gold_a.transactions --silver-root S --products-root S --output-root G
python -m pipelines.gold_a.reviews aggregate --silver-root S --products-root S --output-root G --mapping-path mapping.jsonl --start-date 2026-10-18 --end-date 2026-10-19
python -m pipelines.gold_a.funnels --clicks-root S --transactions-root S --products-root S --output-root G
python -m pipelines.gold_a.reviews aspects --silver-root S --products-root S --output-root G --mapping-path mapping.jsonl --analysis-path analysis.jsonl --model-version demo.v1 --start-date 2026-10-18 --end-date 2026-10-19
```

거래 입출력은 현재 로컬만 지원한다. 기존 리뷰·공용 읽기/쓰기는 S3를 지원하지만 이번 검증은 로컬이다. S3 사용에는 boto3·권한이 필요하며 동시 쓰기 잠금은 없다.

## 계산 기준

- 주문 수는 ordered_at, 성공 결제·승인 금액·상품 판매일은 completed_at의 KST 구간이다. 금액은 취소·환불 차감 전이며 주문 당시 단가를 사용한다.
- 같은 주문의 여러 실패 시도를 매출에 더하지 않는다. 한 주문에 성공 결제가 둘 이상이거나 성공 주문의 주문상품이 없으면 중단한다.
- product_code는 디자인 묶음 기준이며 지표가 아니다. 디자인 주문 수는 상품별 주문 수를 단순 합산하지 않는다.
- 리뷰는 created_at KST 작성일을 사용한다. rating_sum을 저장하며 평균은 소수 4자리, 비율은 소수 6자리 HALF_UP으로 계산한다. JSON에서는 숫자로 저장한다. DECIMAL 테이블 타입 선언은 최종 Parquet/카탈로그 연결 시 별도다.
- 분모가 0이면 NULL이다. 낮은 별점은 1~2점이며 AI 부정 판정과 다르다.

### 퍼널

동일 세션·상품의 첫 조회 이후 이벤트를 연결한다. 반복 조회는 이벤트로 보존하되 방문 수는 세션·상품당 1회다. 장바구니 없이 주문·결제한 방문도 주문·결제 도달로 인정한다. cart_order_sessions는 실제 담기→주문 순서가 있는 방문만 센다.

첫 조회일에 이후 주문·결제 도달을 귀속한다. 예: 18일 조회·19일 성공 결제는 18일 퍼널, 19일 매출이다. 제공된 전체 이력을 사용하며 임의의 전환 만료 시간을 넣지 않는다. 운영상 늦은 결제 반영 기간·스케줄은 별도이며 본 코드는 입력 범위 밖의 미래 결제를 추정하지 않는다. 조회 없는 주문은 매출에는 포함되지만 조회 기반 퍼널에는 포함되지 않는다.

### 리뷰 분석 결과

명세 입력은 JSONL `review_id, aspect, sentiment, model_version`이다. 감성은 긍정/중립/부정, 속성은 현재 라벨 가이드 v3의 11개다. 선택한 모델 버전만 집계한다. 동일 리뷰·속성·모델 버전의 완전히 같은 행은 한 번, 내용 충돌은 실행 중단이다.

실제 review-analysis/deploy/score_batch.py 출력 CSV `review_id,aspect,score`도 지원한다. --model-version으로 출처 버전을 명시하며 -2/-1→부정, 0→중립, 1/2→긍정의 score-sign.v1 변환을 manifest에 기록한다. 모델 추론은 이 코드의 역할이 아니다.

분모는 해당 속성이 언급된 고유 리뷰 수다. 여러 속성 건수를 합쳐 전체 리뷰 수로 표시하지 않는다. 분석 결과 없는 리뷰를 중립으로 세지 않는다. manifest analysis_coverage에 속성 결과가 있는/없는 리뷰 수를 기록하되, 없는 경우 미언급·미분석을 구분할 수 없어 완료 상태는 UNVERIFIED다. 모델 배치의 완료·실패 목록 연결은 별도다. 지퍼 독립 라벨은 없으므로 품질·내구성 비율을 지퍼 비율로 표시하지 않는다.

## 출력 읽기

| 결과 묶음 | 대표 manifest |
|---|---|
| 주문·상품 판매 | `G/gold_a/transactions/current.json` |
| 방문별·일별 퍼널 | `G/gold_a/funnels/current.json` |
| 기본 리뷰 | `G/gold_a/review_product_daily/scopes/<시작일>_<종료일>/current.json` |
| 속성 리뷰 | `G/gold_a/review_aspect_daily/scopes/<시작일>_<종료일>/current.json` |

outputs가 가리키는 완료 파일만 읽는다. runs/scopes 전체를 합치지 않는다. inputs에서 Silver 원본 묶음·품질 결과·상품 매핑·모델 버전 등을 추적한다. 파일 저장이 모두 완료된 뒤 current.json 한 개로 공개하며 중간 실패 때 이전 결과가 남는다. 이전 결과는 최신 입력을 반영했다는 뜻이 아니므로 inputs를 확인한다.

## 날짜·상품 부분 재처리

전체 결과를 먼저 만든 다음 위 실행 명령에 다음 옵션을 추가한다.

```powershell
--replace-start-date 2026-10-19 --replace-end-date 2026-10-19 --article-id 0001
```

- 같은 출력 범위의 기존 current.json을 기준으로 선택 날짜·상품만 새 결과로 교체한다. 다른 날짜·상품은 보존한다.
- 재계산된 대상이 0건이면 기존 대상 행을 제거한다. 단순 추가/행 단위 덮어쓰기와 다르다.
- 입력은 전체 참조가 포함된 최신 Silver 묶음이다. 부분 원천 읽기 최적화나 Silver 부분 병합이 아니다.
- 시간별 주문·매출은 상품 차원이 없으므로 선택 날짜 전체를 다시 계산한다. 상품별 판매는 선택 상품만 바뀐다.
- 퍼널 교체 날짜는 첫 조회일이다. 다음 날 결제 때문에 매출일과 첫 조회일 양쪽을 각각 갱신해야 할 수 있다. 자동 영향 범위 탐색은 하지 않는다.
- 리뷰는 최초 실행과 같은 --start-date/--end-date를 유지하고 교체 옵션으로 그 안의 일부를 선택한다. 겹치는 scopes 자동 병합은 없다.
- 속성 집계는 선택한 model_version만 교체하며 다른 버전은 보존한다. 기본 전체 실행은 명시한 한 모델 버전의 결과를 만든다.
- previous_result에 보존된 이전 결과의 파일·입력 이력을 남긴다. 동시 실행 잠금·이력 압축·자동 재처리 DAG·Silver→Gold 자동 실행은 별도다.

## 검토·검증

기존 연결 테스트와 통합 시나리오 파일 하나에서 6개 데이터셋, 다음 날 결제, 직접 구매, 모델 점수 변환, 연결 실패·내용 충돌, 부분 교체·타 상품 보존·0건 제거·반복 실행을 검증한다.

코드 위치: transactions.py(판매), reviews.py(기본/속성 리뷰·검색), funnels.py(퍼널), __init__.py(입출력·상품 연결·부분 교체). 별도 설계 MD를 추가하지 않고 이 README와 기존 작업 지시서에 기록한다.
