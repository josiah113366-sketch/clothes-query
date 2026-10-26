# Gold A 검증 인사이트 화면 반영

상태: 구현 완료, PR 검토·운영 배포 전

## 범위와 실행 출처

- PR #132의 `dashboard/gold-demo-mode` 기반 별도 PR. #131·#132는 수정하지 않는다.
- 5개 메뉴·사이드바·운영 공개 정책 유지. 기존 구매 퍼널과 리뷰 화면만 보완.
- 퍼널: `funnels-inc-1550c14fc8898fffea6ef8a5`, PARTIAL, **45/1,745파일**, 미처리 1,700파일.
- 리뷰: `reviews-gold-e2e-20261025T143914Z-f18302cd`, PASS, 리뷰 18,514건, 속성 점수 30,048건.
- 거래 시연 Gold는 별도 `trade-r6-demo30-20261024T083441Z` PARTIAL이다. 서로 다른 실행의 매출·퍼널을 결합하지 않는다.
- 이 플랫폼은 시뮬레이터 기반 데이터다. 아래는 실제 적재된 Gold의 관찰 결과이며 현실 고객 전체를 대표하지 않는다.

## 발표 핵심 설명

### ② 구매 전환 병목

퍼널 단위는 **세션×상품**이며 고유 고객·주문 건수가 아니다. 첫 조회일(KST) 코호트에서
조회 410,319 → 담기 29,501 → 주문 12,916 → 결제 12,117이 관찰됐다.
조회→담기는 7.19%, 담기 이후 주문 연결은 12,068/29,501 = 40.91%,
주문→결제는 93.81%다. 담기 이후 주문이 관찰되지 않은 17,433건은 후속 탐색 대상이다.
이는 PARTIAL 관측 범위의 연결 상태로, 최종 이탈·결제 실패를 입증하지 않는다.

### ③ 장바구니 미관찰 주문

같은 실행의 상세에서 `has_order AND NOT has_cart`가 848건이며 전체 주문 도달
12,916건 대비 **6.57%**다. 담기 이후 주문 연결 12,068건과 비교한다.
바로 구매 기능 사용 또는 이벤트 누락이라고 단정할 근거는 없다.
일반적으로 장바구니가 주문 뒤 관찰될 수도 있으므로 단순히 주문−경유 주문으로 미관찰을 계산하지 않는다.
화면은 동일 실행·상품·첫 조회일의 상세 합계와 일별 합계 5개가 모두 맞을 때만 비교를 표시한다.
불일치·빈 주문·알 수 없는 진행 상태·권한 실패는 분석 불가로 표시한다.

### ⑤ 리뷰 속성 불만: 비율과 규모 구분

모델 `2.4b_score_s2c · 1.0`, 리뷰 작성일 2026-10-21~24 KST.
냄새는 **104/145 = 71.72%**로 부정 비율이 높지만 분석 점수 표본이 작다.
사이즈·핏은 **1,023/5,582 = 18.33%**로 부정 건수가 더 많다.
두 관점은 조사 우선순위를 다르게 제시한다. 모델 판정과 표본 구성의 영향이 있을 수 있으며
상품 문제의 원인이나 모델 정확성을 입증하지 않는다. 속성 점수는 리뷰 수와 다르다.
화면은 기간·상품·모델을 고른 후 다시 합산하고 동일 속성 순서로 비율·건수를 나란히 보여준다.

## 발표 자료용 보존 분석 (새 차트 추가 없음)

### ① 언제 활발한가

퍼널 첫 조회 관찰 범위: 2026-10-21 10:50:42.476600 ~ 2026-10-22 08:59:59.387305 KST.
22시 첫 조회 46,341건, 첫 주문 1,553건, 첫 결제 1,492건.
18~23시가 첫 조회의 65.68%, 첫 주문의 66.26%다.
이는 각 세션×상품의 **첫 발생 시각** 분포이며 모든 클릭 이벤트의 시간대 분포가 아니다.
S3 수집 UTC 폴더 날짜와 구분한다. 관측되지 않은 시간대의 활동이 없다고 단정하지 않는다.

### ④ 관심 상품과 결제 상품

같은 퍼널 실행에서 조회 상위 article `0110065001`: 조회 89, 결제 도달 1.
결제 상위 `0578487011`: 조회 27, 결제 도달 8.
`0734511002`: 조회 72, 주문·결제 도달 0.
조회 30회 이상 1,492상품 중 결제 도달 0은 961상품(64.41%).
표본 크기·상품별 관찰 기간·후속 이벤트 누락 가능성 때문에 상품 성과의 확정 순위로 일반화하지 않는다.
이는 결제 도달 수 순위이며 별도 거래 Gold의 실제 매출 순위가 아니다.

## 읽기 전용 재현 SQL

아래 SQL은 검증 시점 전체 코호트다. 화면은 같은 SQL에 **선택한 기간·상품 조건**을 적용한다.

```sql
-- ②·③: 동일 실행의 도달 수·경로 (원본 세션 ID 반환하지 않음)
SELECT count_if(has_view) AS views, count_if(has_cart) AS carts,
       count_if(has_order) AS orders, count_if(has_paid) AS paid,
       count_if(ordered_after_cart) AS cart_orders,
       count_if(has_order AND NOT has_cart) AS cart_unobserved_orders,
       100.0 * count_if(has_order AND NOT has_cart)
         / nullif(count_if(has_order), 0) AS cart_unobserved_pct,
       min(first_view_at_kst) AS first_view_min, max(first_view_at_kst) AS first_view_max
FROM gold_a.funnel_session_product_runs
WHERE run_id = 'funnels-inc-1550c14fc8898fffea6ef8a5';

-- ①: 각각의 첫 발생 시각(KST), 서로 다른 이벤트의 분포를 따로 읽음
SELECT 'first_view' AS event, substr(first_view_at_kst,12,2) AS hour_kst, count(*) AS n
FROM gold_a.funnel_session_product_runs
WHERE run_id = 'funnels-inc-1550c14fc8898fffea6ef8a5'
GROUP BY 2
UNION ALL
SELECT 'first_order', substr(first_order_at_kst,12,2), count(*)
FROM gold_a.funnel_session_product_runs
WHERE run_id = 'funnels-inc-1550c14fc8898fffea6ef8a5' AND has_order
GROUP BY 2
UNION ALL
SELECT 'first_paid', substr(first_paid_at_kst,12,2), count(*)
FROM gold_a.funnel_session_product_runs
WHERE run_id = 'funnels-inc-1550c14fc8898fffea6ef8a5' AND has_paid
GROUP BY 2;

-- ④: 같은 코호트의 관심·결제 도달 상품 (조회 순위는 ORDER BY views DESC)
SELECT article_id, sum(view_sessions) AS views, sum(cart_sessions) AS carts,
       sum(order_sessions) AS orders, sum(paid_sessions) AS paid
FROM gold_a.funnel_daily_runs
WHERE run_id = 'funnels-inc-1550c14fc8898fffea6ef8a5'
GROUP BY article_id ORDER BY paid DESC, views DESC LIMIT 12;

-- ⑤: 모델별 속성 부정 수와 비율. 모델을 섞지 않는다.
SELECT model_version, model_version_no, aspect,
       sum(scored_review_count) AS scores,
       sum(score_neg2_count + score_neg1_count) AS negative,
       100.0 * sum(score_neg2_count + score_neg1_count)
         / nullif(sum(scored_review_count), 0) AS negative_pct
FROM gold_a.review_aspect_daily_runs
WHERE run_id = 'reviews-gold-e2e-20261025T143914Z-f18302cd'
GROUP BY model_version, model_version_no, aspect
ORDER BY negative_pct DESC;
```

## 검증 및 적용

- 기존 34개 + 지표·화면 회귀 8개 = **42개 통과**.
- Windows Streamlit AppTest 실제 Athena 두 화면: 오류·예외 0건. 퍼널 848/12,916=6.57%와 PARTIAL 경고, 리뷰 냄새 104/145·사이즈/핏 1,023/5,582·30,048점수 및 PASS 표시를 확인했다. 이는 로컬 렌더링 검증이며 운영 배포 검증은 아니다.
- PR #131 IAM 적용 → #132 반영 → 이 PR 반영 순서. 이 PR은 #132에 대한 추가분만 담는 종속 PR이다.
- 추가 IAM·Spark 이미지·DAG 변경 없음. 운영 반영은 기존 대시보드 이미지 빌드·배포 경로를 이용한다.
- current·checkpoint·완료 manifest 및 원본 고객 행을 변경하거나 저장하지 않는다.

## 작업 결과

구매 퍼널의 관찰 경로 비교와 리뷰 속성 비율·건수 비교를 기존 화면 안에 추가했다.
숫자는 Athena 집계에서 계산하며 발표 수치를 코드 상수로 쓰지 않는다.
시간대·인기 상품은 위 읽기 전용 SQL과 해석으로 보존했다.
운영 배포·기존 PR 머지는 이번 작업에 포함하지 않는다.
