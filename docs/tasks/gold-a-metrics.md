상태: 완료 · main 대상 PR 제출 보류

# Gold A 지표 분리

브랜치: `pipelines/gold-a` (기존 `gold-a/metrics`에서 이름 변경). 최초 생성 시 최신 `main`에서 선행 Silver 커밋을 포함했다. 선행 Silver 브랜치는 `pipelines/silver`다. Silver 브랜치가 먼저 반영되면 이 브랜치의 PR 차이는 Gold A 파일과 이 작업 문서만 남는다.

## 범위

### 2026-10-22 main 통합 정리

- 사용자 요청으로 기존 구현을 최신 origin/main(9db1dd2)과 로컬 통합했다. #34가 main이 아닌 Silver에 머지됐던 Gold A 코드와 후속 리뷰 KST 계약·정상 0건 재생성 고려사항을 보존했다.
- #35 Kafka 추적·#45 R6 고정 실행 기록·#55 공통 지문과 승인된 Silver 호출을 함께 보존했다. 기존 승인된 unit_price 5,900원·규칙 0.1.1을 통합하고 정상 테스트 입력을 일치시켰다. 검사 버전은 transactions.v8, 주문 합계 검사 버전 items-sum-v1, 지문 버전 payment-content.v1로 구분한다.
- 통합 검증: Silver·Gold A·거래 연결 테스트 55개 통과(11.27초). 각 단계의 29/30/36개 검증과 전체 통합 검증을 구분한다. 실제 AWS·DAG·A/B 대조 잡은 실행하거나 새로 구현하지 않았다.
- 추가 정책 변경은 하지 않았다. 시각 입력 형식·정밀도/오프셋 범위·UUID 표기·정수 저장 범위, Gold B UNKNOWN 정책·정리 뷰 지문 출력·버전 혼재·처리 완료 범위는 후속 합의/보완 대상이다.
- 자동 승인 검토가 명시적 push·머지 승인 부족으로 원격 반영을 거부했다. 로컬 정리와 검증까지 완료하고 원격 push·PR 생성·main 머지는 대기한다. 기존 브랜치와 커밋은 삭제하거나 재작성하지 않았다.
- 최신 Ruff 규칙과 충돌하던 기존 Gold A import 순서를 정리했다. 외부 manifest/결과 검증의 기존 ValueError 계약은 유지하도록 해당 TRY004에 이유를 붙였다. Silver 공통 입출력·거래·지문·Gold A Ruff 검사 및 전체 diff 공백 검사 통과. 통합본은 pipelines/gold-a에 모여 있으며 기존 3개 PR은 #35 → #45 → #55 순서로 반영한 뒤 Gold A의 main 대상 PR을 제출할 수 있다.

2026-10-22 사용자 승인: 리뷰 분석 입력 선택과 Gold A 집계는 KST 작성일 기준으로 명확히 한다. 기존 Silver UTC/KST 변환 및 날짜 경계 처리는 유지하고 공통 계약·Silver/Gold A README에 Bronze UTC 보관, SageMaker의 ID/본문 분석, 다음 날 분석 시 원래 작성일 귀속, DAG 입력 범위 연결 요구를 기록한다. 실행 코드·모델 담당 코드 변경 및 AWS 작업은 없다. 상대 링크·기존 함수와의 정합성·diff 공백을 확인하며 문서 변경만으로 새 테스트를 만들지 않는다.

### 2026-10-20 승인된 구현: CDC 연결과 범위별 갱신 보류

- **추가 승인: YAML 연결 후 연결 검증.** 선행 거래 Silver가 UUID・PG・상태 사유를 실제 YAML대로 검사하므로 기존 거래/시나리오 예시의 식별자와 PG 값을 원천 형식으로 수정했다. 금액・재시도・상품・퍼널・리뷰 기대값의 의미는 유지하며 운영 규칙 우회용 테스트 모드를 만들지 않는다. Gold A 계산 코드나 리뷰 입력 계약은 변경하지 않는다. 공통 계약 원본을 작업 브랜치에 포함해 기본 YAML 경로가 존재하게 한다.
- **YAML 연결 검증 결과:** 전체 테스트 46개 통과(11.19초). 기존 Gold A 매출・퍼널・리뷰 기대값과 오류 보류/복구 검증을 유지했다. 로컬 합성 입력으로 YAML 0.1.0의 버전/해시를 기록하고 PG_TIMEOUT 정상 → PG_NEW_ERROR 규칙 위반/보류 → 수정 후 PASS 복구를 실행했다. 자료는 pipelines/gold_a/.local/yaml-demo-20261020-4caf53/report.md와 단계별 manifest 사본이다. 실제 S3・Gold B・에이전트 실행 결과가 아니다.

- **실패 코드 규칙 정리 후 연결 검증:** Silver는 원천 5개 코드만 허용하도록 변경한다. 기존 거래 연결 테스트의 임시 TEMP 코드를 원천 허용값 PG_TIMEOUT으로 고쳐 정상 재시도 시나리오를 유지한다. Gold A 시나리오에서 미등록 코드 격리 → 기존 결과 유지 → 허용 코드 수정 후 재처리 PASS를 확인한다. UNKNOWN 분류 또는 Gold B 직접 조회는 구현하지 않는다. 공통 계약의 확장안은 docs/data-contracts에 별도 제안으로 보존한다.
- **실패 코드 최종 확인:** 전체 파이프라인 테스트 43개 통과(7.49초), diff 공백 검사 통과. 미등록 코드 때문에 발생한 불완전한 입력으로 기존 Gold 결과를 정상 숫자처럼 갱신하지 않는 것을 확인했다.

- **추가 승인: 금액 검사와 조사 에이전트 접점.** 선행 Silver에 주문상품 합계 검사를 연결한다. 불일치에서 기존 거래/퍼널 전체 보류, 수정 후 PASS 복구를 검증한다. Gold A README에 Gold B 기반 탐지 → 조사 에이전트 → Gold A/상세 Silver 각각 조회하는 계약 제안을 남긴다. Gold A가 Gold B를 읽는 함수는 추가하지 않는다. Gold B order_id 보존・사건 필드・관찰 종료/입수 범위・부분 시간대 조회는 담당자 합의 대상이다.
- **금액 검사 결과:** Silver・Gold A・거래 연결 테스트 40개 통과(7.12초), 변경 파일 import 정렬・diff 공백 검사 통과. 기존 테스트 파일에만 사례를 추가했다. 합성 입력으로 20,000/20,000/20,000 정상 → 주문/결제 21,000・상품 합계 20,000 불일치 → 수정 후 PASS 복구를 실행했다. 보고서는 pipelines/gold_a/.local/amount-demo-20261020-22ef20/report.md다. 입력 완전성 확인은 실행자 선언이며 실제 AWS 검증이 아니다. 코드와 문서는 로컬 수정 상태이고 push하지 않았다.
- **커밋/최신 main 반영:** 사용자 요청으로 Silver 구현・Gold A 구현・Gold A 실행/조회 계약 문서를 세 커밋으로 분리했다. Silver 변경은 pipelines/silver에도 별도 보존했다. main을 PR #32 병합 커밋 4c55fbc까지 fast-forward pull한 뒤 Gold A에 병합한다. BRANCHES.md 구조도 충돌은 시뮬레이터 이력과 두 파이프라인 항목을 함께 보존하고 합의된 브랜치명으로 해결한다. 원격 push는 하지 않는다. 병합 후 파이프라인 회귀 검증 결과는 아래 기록한다.
- **병합 검증:** 최신 main 파일과 충돌 해결 내용을 반영한 작업 폴더에서 Silver・Gold A・거래 연결 테스트 40개 통과(7.81초). 문서 충돌 표식 없음・diff 공백 검사 통과. 로컬 실행 자료는 ignored .local에 유지했다.

- **입력:** 원격 sim/cdc-orders의 펼쳐진 CDC 설정과 기존 로컬 Silver 계약을 비교한 뒤 선행 Silver와 후행 Gold A를 pipelines/gold-a 작업 폴더에서 함께 수정했다. 원격 브랜치 병합・push・PR 갱신은 하지 않았다.
- **구현:** 거래/퍼널 --scope-aware, 명시적 전체 입력 선언 검사, 현재/이전 후보와 미해결 후보의 영향 범위 합집합, 정상 범위 교체・보류 범위 이전 결과 유지, PARTIAL/held_scopes/held_context, 복구 후 전체 재계산・보류 해제. 기존 일반 실행은 엄격한 PASS 검사를 유지한다.
- **안전 장치:** 추적 불가・주문/항목 오류는 관련 묶음 전체 보류. 이전 결과 없음은 0으로 채우지 않는다. 보류 결과를 일반 실행으로 덮어쓰지 않는다. 로컬 거래/퍼널 단일 작성자 잠금, 실패 시 이전 포인터 유지와 실패 유형 기록.
- **범위:** 기존 소스와 기존 테스트 파일만 수정했다. 대시보드・AWS・자동 재처리 DAG・LSN 및 행별 Kafka offset 생성은 추가하지 않았다. 입력 완전성은 실행자 선언이며 자동 원천 범위 증명이 아니다.
- **실행 결과:** 합성 입력 정상 → 충돌 보류 → 수정/재처리를 실제 로컬 함수로 실행해 거래/퍼널 PASS → PARTIAL → PASS를 확인했다. 검토 자료는 pipelines/gold_a/.local/scoped-demo-20261020-0e6f8a/report.md와 단계별 manifest 사본이다. 실제 AWS 검증이 아니다.
- **검증:** Silver・Gold A・거래 연결 테스트 37개 통과(7.18초). 기존 테스트 파일만 보완했다. import 정렬 검사와 git diff --check 통과. 전체 Ruff에는 기존 공용 로더의 TRY004 4건이 남아 있으며 이번 변경과 무관한 예외 타입 변경은 하지 않았다. 기본 임시 폴더 권한 문제를 피하려고 ignored .local 아래의 고유한 --basetemp를 사용했다.

- **2026-10-20 문서 보완:** Gold A README에 오류 영향 범위 추적・범위별 갱신 보류・manifest 기록・복구 확인을 제안으로 추가한다. 실행 코드・YAML・테스트는 변경하지 않는다. 현재 전체 작업 차단 및 날짜 단위 시간별 교체와 추가 설계의 차이를 명시한다. 문서 기준과 diff 공백만 확인하며 기능 구현 완료로 취급하지 않는다.

- Silver 리뷰를 이용한 상품별 일간 리뷰 집계와 상품·기간·키워드 조회.
- 거래 Silver를 이용한 KST 시간별 주문·승인 금액과 결제일·`article_id`별 판매 수량·금액.
- 회원 Gold 분석은 제외한다. 실제 거래 Bronze 연결과 리뷰 AI 분석 결과 연결은 아직 없다.

## 완료 확인

2026-10-21 문서 기록: Gold A README에 리뷰 시뮬레이터 재생성의 정상 0건 예외를 후속 고려사항으로 남겼다. 현재 우선순위에서 제외하고 Silver·Gold A 재처리와 구분한다. 정상 0건/생성 실패 구분, 생성기 관리 파일만 변경, Silver 입력 없음 보호와의 연결을 추후 확인한다. 실행 코드 변경은 없으며 상대 링크와 diff 공백만 확인한다.

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


## 승인된 수정 및 작업 결과: 리뷰 속성 점수 보존

- **이유:** 리뷰 분석 README·배포 코드의 기준 모델은 -2~2 점수 모델이다. 이전 score-sign.v1은 이를 3분류로 축약하고 차이를 잃었으므로 아래 결정으로 대체한다. 라벨 가이드의 3분류 파생 기준은 미정이다.
- **변경:** 기존 reviews.py의 CSV·JSONL 입력에서 score를 직접 검사한다. bool·실수·누락·범위 밖 점수와 sentiment만 있는 입력을 거부한다. 같은 키의 같은 점수는 중복 제거, 다른 점수는 충돌이다.
- **출력:** scored_review_count, 점수별 5개 건수, score_sum, average_score. 기존 3분류 건수·negative_rate를 제거한다. 테이블 그레인·상품/날짜/모델 키와 별점 집계는 유지한다.
- **전환:** inputs에 aspect_schema=score.v1을 기록하고 부분 교체 전에 기존 버전·점수 컬럼·구형 컬럼 혼입을 검사한다. 3분류 결과는 원점수로 전체 재집계해야 하며 임의 점수 복원은 하지 않는다.
- **파일:** reviews.py, 기존 tests/test_metrics_scenarios.py, Gold A README, 이 작업 지시서만 수정한다. 모델 담당 문서·원천 코드·공용 저장 모듈은 수정하지 않는다.
- **검증:** 아래 최종 검증 결과에 기록한다. 실제 모델 추론/AWS 입수 확인은 아니며 합성 점수 입력과 로컬 배치 검증이다.

- **최종 검증:** Silver·Gold A 테스트 30개 통과. 5단계 각각의 건수 보존·평균/합계, 같은 점수 중복·다른 점수 충돌, 잘못된 점수/감성 전용 입력 거부, 구형 결과의 부분 재처리 차단→전체 재집계→부분 재처리 가능 확인. 기존 거래·퍼널·리뷰 별점·품질 차단 검증도 통과. git diff --check 통과.
- **실행 예시:** .local/demo-score-20261019/report.md. 실제 모델과 같은 CSV 형식의 합성 점수 -2와 +1을 입력해 점수 건수 2, 합계 -1, 평균 -0.5 확인. 중복 재수신은 건수를 늘리지 않음. 예전 .local/demo-20261019/report.md는 과거 3분류 검증임을 표시하고 새 보고서로 연결함.
