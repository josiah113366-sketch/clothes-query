# Gold A: 주문·상품 판매·퍼널·리뷰 집계

## 구현된 결과와 한 행의 기준

| 데이터셋 | 한 행의 기준 | 결과 |
|---|---|---|
| order_sales_hourly | KST 1시간 | 주문 수·성공 주문 수·승인 금액 |
| product_sales_daily | KST 성공 결제일 × article_id | product_code, 성공 주문 수·판매 수량·주문상품 금액 |
| funnel_session_product | session_id × article_id | 첫 조회·담기·주문·성공 결제 시각, 도달 여부 |
| funnel_daily | 첫 조회 KST 날짜 × article_id | 단계별 방문 수와 전환율 |
| review_product_daily | 리뷰 작성 KST 날짜 × article_id | product_code, 리뷰 수·별점 합계·평균·1~2점 건수·비율 |
| review_aspect_daily | 리뷰 작성 KST 날짜 × article_id × aspect × model_version | 점수별 리뷰 수·점수 합계·평균 |

현재 실행은 Python 배치와 JSONL이다. Spark·Airflow·Parquet/Glue 스키마·실제 AWS 전체 연결까지 완료했다는 뜻은 아니다. 리뷰 모델을 실행하거나 truth 라벨로 판정을 대신 만들지 않는다.

## 입력과 상품 연결

| 입력 | 대표 manifest |
|---|---|
| 거래 | `<silver-root>/silver/transactions/current.json` |
| 클릭 | `<clicks-root>/silver/clicks/current.json` |
| 상품 | `<products-root>/silver/products/current.json` |
| 리뷰 | `<silver-root>/silver/reviews/scopes/<시작일>_<종료일>/current.json` |

기본 실행은 manifest와 실제 dq_results가 전부 PASS・격리 0건이어야 한다. 거래・퍼널의 `--scope-aware` 실행만 아래 범위별 보류 규칙을 적용한다. 필요한 파일 누락・연결 실패・분석 내용 충돌 시 해당 작업을 중단하고 기존 Gold 결과를 보존한다. PASS는 읽은 입력의 검사 통과이며 원천 입수 완전성・최신성을 보증하지 않는다.

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

거래 입출력과 범위별 갱신은 현재 로컬만 지원한다. 기존 리뷰・공용 읽기/쓰기는 S3를 지원하지만 이번 검증은 로컬이다. S3 사용에는 boto3・권한이 필요하다. 로컬 거래・퍼널 출력에는 단일 작성자 잠금을 적용하며 리뷰・S3 동시 쓰기 제어는 별도다.

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

**작성일 기준: KST.** 분석할 리뷰는 Silver의 review_date_kst 범위로 선택한다. SageMaker는 해당 리뷰의 ID·본문을 점수화하며 현재 출력 CSV에는 날짜가 없다. Gold A가 review_id로 원래 Silver 리뷰와 연결해 KST 작성일에 귀속한다. 22일 작성 리뷰를 23일에 분석해도 22일 집계다. 분석일·작업 출력 폴더·emitted_at을 작성일로 사용하지 않는다. Bronze의 UTC 폴더를 KST로 바꾸는 요구는 아니다.

DAG에서 모델 작업과 Silver 입력 실행·KST 날짜 범위를 연결해 전달해야 한다. 이 자동 실행/완료 연결은 후속이며 [공통 날짜 계약](../../docs/contracts/README.md#리뷰-분석-날짜-계약--kst-작성일-2026-10-22-결정)을 따른다.

입력은 JSONL `review_id, aspect, score, model_version` 또는 실제 score_batch.py의 CSV `review_id,aspect,score`다. CSV에는 --model-version으로 출처 버전을 명시한다. score는 정수 -2,-1,0,1,2만 허용하며 bool·실수·누락을 거부한다. sentiment만 있는 기록에서 점수를 추정하지 않는다. 모델 추론은 이 코드의 역할이 아니다.

점수 기준은 review-analysis/README.md, docs/absa-label-guide.md 3-1, deploy/score_batch.py 프롬프트를 따른다. +2 분명한 만족, +1 약한 만족, 0 보통·혼재, -1 약한 불만, -2 분명한 불만이다. 라벨 가이드의 3분류 파생 기준은 미정이므로 부호로 긍정/중립/부정을 자동 생성하지 않는다.

선택한 모델 버전만 집계하며 속성은 현재 가이드 v3의 11개다. 같은 review_id/aspect/model_version의 같은 score는 한 번, 다른 score는 충돌로 실행 중단한다. 기타 메타데이터 차이를 점수 충돌로 간주하지 않는다.

### review_aspect_daily 점수 명세

한 행·고유 키는 review_date_kst × article_id × aspect × model_version이다. product_code는 디자인 묶음 기준이다.

| 컬럼 | 타입 | 정의 |
|---|---|---|
| review_date_kst | DATE | 리뷰 작성 KST 날짜 |
| article_id | STRING | 검증된 상품 키 |
| product_code | BIGINT | 디자인 묶음 키 |
| aspect | STRING | 분석 속성 |
| model_version | STRING | 모델 버전 |
| scored_review_count | BIGINT | 해당 속성 점수가 있는 고유 리뷰 수 |
| score_neg2_count | BIGINT | -2점 리뷰 수 |
| score_neg1_count | BIGINT | -1점 리뷰 수 |
| score_zero_count | BIGINT | 0점 리뷰 수 |
| score_pos1_count | BIGINT | +1점 리뷰 수 |
| score_pos2_count | BIGINT | +2점 리뷰 수 |
| score_sum | BIGINT | 점수 합계 |
| average_score | DECIMAL(10,4) | score_sum / scored_review_count, 소수 4자리 HALF_UP |

점수별 5개 건수의 합은 scored_review_count, 점수×건수의 합은 score_sum이다. 여러 날짜의 평균은 score_sum 합계 / scored_review_count 합계로 구한다. 여러 속성의 건수를 전체 리뷰 수로 합치지 않는다. 기존 mentioned/positive/neutral/negative_review_count·negative_rate는 출력하지 않는다.

미언급·미분석은 0점이 아니다. manifest analysis_coverage에 속성 결과 유무를 기록하되, 없는 경우 미언급·미분석을 구분할 수 없어 완료 상태는 UNVERIFIED다. 실제 모델 배치 완료·실패 목록 연결은 별도다.

manifest inputs에 aspect_schema=score.v1, score_policy=integer-minus2-plus2.v1을 기록한다. 기존 3분류 결과에는 원점수 정보가 없으므로 **원래 모델 점수 입력으로 같은 범위를 전체 재집계한 뒤** 부분 재처리를 사용한다. 부분 재처리 전에 버전·필수 점수 컬럼·구형 컬럼 혼입을 검사한다. 구형 결과가 0건이어도 버전으로 차단한다. 전체 재집계 완료 전에는 이전 current.json을 보존한다.

## 출력 읽기

### 후속 고려사항: 리뷰 재생성 시 정상 0건 처리

**상태: 잠재적 예외 상황 · 현재 구현 우선순위에서 제외**

현재 리뷰 시뮬레이터는 같은 날짜에 리뷰가 1건 이상 생성되면 S3의 `part-00000.jsonl`을 덮어쓴다. 하지만 정상적으로 생성 작업을 완료했어도 결과가 0건이면 파일을 쓰지 않아 기존 리뷰 파일이 남을 수 있다. 저장 동작 근거는 [LakeSink.close](../../review-simulator/src/rsim/review/sinks.py)다.

발생 조건은 해당 날짜의 기존 파일이 있고, 같은 날짜를 다시 생성했으며, 새 생성 결과가 정상 0건인 경우다. 이는 시뮬레이터로 시연 데이터를 다시 만드는 경우의 고려사항이며, 저장된 원문을 다시 읽어 계산하는 Silver·Gold A 재처리와는 별개다. 현재 실제 문제가 발생한 것은 아니다.

추후 재생성 기능을 사용할 때 다음 처리를 확인한다.

- 정상 0건이면 생성기가 관리하는 기존 파일을 비우거나 제거한다.
- 생성 실패 시에는 기존 파일을 유지한다. 전체 생성 실패를 정상 0건으로 오인하지 않도록 완료 여부를 구분한다.
- 수동 추가 리뷰 등 다른 파일은 보존한다.
- 수정 후 Silver가 이전 리뷰를 남기지 않고 정상 0건으로 반영하는지 확인한다. 파일 제거 방식은 Silver의 입력 없음 보호와 구분할 완료 증거가 필요하다. 빈 파일 또는 완료 기록 등 구체적 계약은 담당자와 정한다.

담당: 시뮬레이터 담당자가 저장 동작 확인·수정, Silver 담당자가 입력 및 결과 반영 확인. 현재는 실제 리뷰 상품 연결, 모델 점수 결과 연결, Silver·Gold A 검증을 먼저 진행한다. 이 기록은 후속 검토용이며 저장 동작 변경을 승인하거나 구현한 것은 아니다.

### 대표 출력 위치

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
- 퍼널 교체 날짜는 첫 조회일이다. 다음 날 결제 때문에 매출일과 첫 조회일 양쪽을 각각 갱신해야 할 수 있다. 이 --replace 기능 자체는 자동 영향 범위 탐색을 하지 않으며 아래 --scope-aware와 구분한다.
- 리뷰는 최초 실행과 같은 --start-date/--end-date를 유지하고 교체 옵션으로 그 안의 일부를 선택한다. 겹치는 scopes 자동 병합은 없다.
- 속성 집계는 선택한 model_version만 교체하며 다른 버전은 보존한다. 기본 전체 실행은 명시한 한 모델 버전의 결과를 만든다.
- previous_result에 보존된 이전 결과의 파일·입력 이력을 남긴다. 동시 실행 잠금·이력 압축·자동 재처리 DAG·Silver→Gold 자동 실행은 별도다.

## 오류 발생 시 범위별 갱신 보류

**상태: 결정・로컬 구현.** 사용자 승인으로 거래・퍼널에 `--scope-aware`를 추가했다. 기본 실행의 전체 차단은 유지하며 옵션을 명시한 실행에서만 범위별 보류를 사용한다. 실제 AWS・대시보드・자동 재실행 연결은 별도다.

먼저 거래 Silver와 클릭 Silver를 필요한 전체 입력으로 `--input-complete`와 함께 실행한다. 이것은 입수 범위를 확인한 실행자의 선언이며 자동 Kafka 위치 검증이 아니다. 상품 기준정보는 기존 PASS 검사를 통과해야 한다. 이후 다음처럼 실행한다.

```powershell
python -m pipelines.gold_a.transactions --silver-root S --products-root S --output-root G --scope-aware
python -m pipelines.gold_a.funnels --clicks-root S --transactions-root S --products-root S --output-root G --scope-aware
```

전체 공급 이력을 다시 계산하고 오류 범위만 동결하므로 --replace 옵션과 함께 사용하지 않는다. 보류 중인 결과를 기본 실행으로 덮어쓸 수 없고, 같은 옵션으로 전체 입력을 재처리해야 한다.

### 영향 범위 찾기

충돌한 모든 후보와 이전 집계에 반영한 기록을 함께 확인한다. payment_id → 후보별 order_id → 주문상품・세션・결제 시각을 따라가며, 관련 범위의 합집합을 보류한다. 정상 Silver 출력에서 제외된 오류 기록과 이전 입력도 원본 참조로 찾아야 한다.

| 결과 | 결제 충돌의 갱신 보류 단위・추적 기준 |
|---|---|
| order_sales_hourly | 후보 및 이전 반영 기록의 completed_at KST 시간대. 한 행에 주문 수・성공 주문 수・승인 금액이 함께 있으므로 우선 해당 시간 행 전체를 보류한다. 주문 생성 수 자체는 ordered_at 기준이며 결제 충돌과 직접 영향이 다르다. |
| product_sales_daily | 성공 가능성이 있는 후보 및 이전 반영 기록의 KST 결제일 × 관련 주문의 article_id. 상태가 다르면 성공 후보도 빠뜨리지 않는다. |
| funnel_session_product | 관련 주문의 session_id × article_id. 연결 가능한 모든 후보와 이전 연결을 확인한다. |
| funnel_daily | 영향받은 세션・상품의 첫 조회 KST 날짜 × article_id. 해당 일별 집계 전체를 보류하며 결제일과 같다고 가정하지 않는다. |
| review_product_daily・review_aspect_daily | 현재 입력 의존 관계에서는 결제 충돌만으로 보류하지 않는다. 별도 리뷰・상품 연결・분석 오류가 있으면 해당 의존 관계로 범위를 판정한다. |

예: O1의 상품 A 결제 P1이 10월 19일 10시로 충돌하고, 세션 S1의 첫 조회일이 10월 18일이면 19일 10시 매출 행・19일 상품 A 판매・S1/상품 A 퍼널・18일 상품 A 일별 퍼널을 보류한다. 완료 시각이 10시와 11시로 충돌하면 양쪽 시간대를, 주문 키가 다르면 양쪽 주문의 상품・세션을 포함한다.

기존 --replace 시간별 지표 교체는 날짜 단위다. --scope-aware는 별도 처리로 시간 행별 보류・교체를 구현한다. 현재는 결제 오류를 중심으로 범위를 좁히며, 같은 주문의 생성 시간 행도 보수적으로 보류한다. 주문/주문상품 자체 오류・후보 정규화 실패・키/시각/이전 참조 복원 불가 시 관련 거래 또는 퍼널 묶음 전체를 보류한다.

### 갱신과 보류 기록

- 입력 파일・Kafka 위치 등 읽은 범위와 필요한 참조 데이터가 완전하다고 확인한 정상 범위만 교체한다. 오류 기록이 없다는 사실만으로 입수 완전성을 보장하지 않는다.
- 보류 범위는 문제 결제를 제외한 불완전한 합계로 교체하지 않는다. 마지막 정상 결과를 유지하고, 이전 결과가 없으면 결과 없음・갱신 보류로 제공한다. 0건・0원으로 채우지 않는다.
- 키・시각・이전 반영 범위 등을 복원하지 못하면 관련 집계 작업의 요청 범위 전체를 보류한다. 범위를 임의로 좁히지 않는다.
- 보류 기록은 기존 manifest의 held_scopes에 기록한다. 각 항목의 table・key・reason・order_ids・error_refs로 범위와 근거를 나타내며, key={}는 해당 테이블 전체 보류다.

| manifest에 기록할 정보 | 용도 |
|---|---|
| 대상 테이블・보류 범위 | 어떤 날짜・시간・상품・세션의 결과가 최신이 아닌지 확인 |
| 보류 상태・이유 | 데이터 없음과 오류로 인한 미갱신을 구분 |
| 오류 기록 참조・추적 키 | Silver 오류 및 모든 원본 후보로 연결. 원문 전체를 복사하지 않음 |
| 마지막 정상 실행 ID・출력 참조・갱신 시각 | 유지한 숫자의 출처와 최신성 확인. 기존 결과가 없으면 없음으로 기록 |

정상 범위의 새 숫자・보류 범위의 이전 숫자・held_scopes를 같은 공개 묶음으로 저장한다. 일부 범위가 보류 중이면 status=PARTIAL이다. 이전 결과가 없는 보류 범위는 행을 만들지 않고 previous_result_available=false・last_normal_result=null로 나타낸다. 기존 결과가 있으면 last_normal_result에 정상 실행 ID・공개 시각・출력 참조를 보존한다. held_context에는 미해결 영향 후보를 보존한다. 조회 측은 숫자와 상태를 함께 읽어야 하며 대시보드 반영은 아직 없다.

결과 공개 실패 시 이전 current.json을 유지하고 가능한 경우 failed-runs/에 실패 유형을 기록한다. 로컬 거래・퍼널은 .writer.lock으로 같은 출력의 동시 실행을 거부한다. 프로세스 강제 종료 후 남은 잠금은 실제 실행이 없는지 확인하고 수동 정리하며 자동으로 탈취하지 않는다. 리뷰・S3 잠금은 별도다.

### 복구와 확인

1. 충돌 후보 중 임의의 첫 행을 고르지 않고 올바른 입력 또는 처리 규칙을 확정한다. Bronze 원본을 직접 수정하는 방식으로 복구하지 않는다.
2. Silver를 재처리하고 관련 오류가 해소됐는지 확인한다.
3. 현재 후보와 이전 반영 기록에서 찾은 영향 범위 전체를 다시 계산한다. 기존 금액에 차액을 더하지 않는다.
4. 해당 범위의 입력 완전성・품질・고유 키・지표 계산을 확인한 뒤 결과 교체와 보류 해제를 함께 공개한다. 다른 오류가 남은 범위는 계속 보류한다.

기존 테스트 파일에서 오류 상품 보류・정상 상품 갱신, 이전 결과 없는 범위의 0 오표시 방지, 충돌 시간대 합집합, 첫 조회일 퍼널 보류, 추적 불가 시 전체 보류, 반복 실행・복구・공개 실패・동시 작성 거부를 확인한다.

수정한 전체 입력으로 Silver를 재실행한 뒤 같은 --scope-aware 명령을 실행한다. 남은 오류가 없으면 전체 계산 결과로 교체하고 held_scopes를 비워 PASS로 공개한다. 자동 실행・대시보드 표시 연결과 복구 소요 시간은 보장하지 않는다. 현재 전체 입력을 읽으므로 실제 데이터로 실행 시간을 측정한다.

## 조사 에이전트와의 조회 계약

**상태: 제안・담당자 합의 전.** Gold A는 Silver를 읽어 집계하며 Gold B를 집계 입력으로 읽지 않는다. Gold B 기반 탐지가 사건을 발견하면 조사 에이전트가 Gold B・Gold A・Silver를 각각 조회하는 방향이다. 아래는 전달/조회 접점이며 에이전트 구현 완료나 Gold B 필드 보존 합의를 뜻하지 않는다.

| 제공 주체 → 조회 주체 | 필요한 정보・용도 | 확인할 계약 |
|---|---|---|
| 탐지/Gold B → 조사 에이전트 | 사건 ID・pg・장애 시작/종료・근거 결제 payment_id/order_id | 실제 원장/뷰 필드명, order_id 보존, 사건 종료 전 조회 기준 시각. 세부 필드는 Gold B/에이전트 담당자와 합의 |
| Gold A → 조사 에이전트 | hour_start_kst・order_count・paid_order_count・approved_amount | 시각 구간은 시작 포함/끝 제외. 주문 수는 ordered_at, 성공 수/승인 금액은 completed_at. 환불 차감 전 승인 금액임을 표시 |
| Gold A 품질 → 조사 에이전트 | status・held_scopes・published_at・마지막 정상 결과 참조 | PARTIAL의 보류 범위는 최신 숫자로 해석하지 않음. 이전 결과 없음은 0으로 대체하지 않음 |
| Silver 결제 상세 → 조사 에이전트 | order_id・payment_id・attempt_no・status・pg・완료 시각 | 장애 중 실패한 주문의 후속 성공을 같은 order_id로 연결. 조사 구간 이후의 재시도도 명시한 관찰 종료까지 확인 |
| Silver 주문상품 → 조사 에이전트 | order_id・article_id・quantity・unit_price | 영향 주문을 상품에 연결. 격리/보류 주문은 정상 상세에 없을 수 있으므로 DQ・오류 참조도 확인 |
| 실행/입수 기록 → 조사 에이전트 | 경로별 읽은 원본 범위・조회 기준 시각・관찰 종료 시각・사용 규칙 버전 | 입수 대기/미확인과 실제 실패를 구분. 자동 원천 범위 확인은 아직 없으며 실행자 선언을 증명으로 취급하지 않음 |

장애 시각을 UTC 또는 시간대가 명시된 ISO 값으로 전달하고 Gold A 조회 시 KST로 맞춘다. 예: 10:15~10:45 장애에 시간별 10:00~11:00 집계를 보여줄 경우 확장한 구간을 표시한다. 시간 집계만으로 30분의 정확한 승인 금액을 만들어 내지 않으며, 정확한 구간 계산은 Silver 상세 조회가 필요하다.

PG 장애 구간과 전체 승인 금액 변화를 나란히 보고, 해당 PG에서 실패한 고유 주문의 재시도 성공 여부를 별도로 조사한다. Gold A 시간 집계에는 PG/order_id 차원을 추가하지 않는다. 이 결과를 PG 장애 때문에 잃은 매출로 단정하거나 실패 시도 수를 영향 주문 수로 표시하지 않는다. 관찰 종료까지 성공이 보이지 않는 주문은 미관측/미성공 상태이며 영구 실패로 단정하지 않는다. 매출 증감의 비교 기간・탐지 임계값・자동 알림은 별도 합의 대상이다.

이번 작업은 조회 계약을 문서에 남기는 데 한정한다. Gold B를 읽는 조사 함수・에이전트/DAG・대시보드 연결・재처리 승인 실행은 추가하지 않는다.

## 검토·검증 결과

기존 연결 테스트와 통합 시나리오 파일 하나에서 6개 데이터셋, 다음 날 결제, 직접 구매, 모델 점수 변환, 연결 실패·내용 충돌, 부분 교체·타 상품 보존·0건 제거·반복 실행을 검증한다.

코드 위치: transactions.py(판매), reviews.py(기본/속성 리뷰·검색), funnels.py(퍼널), __init__.py(입출력·상품 연결·부분 교체). 별도 설계 MD를 추가하지 않고 이 README와 기존 작업 지시서에 기록한다.
