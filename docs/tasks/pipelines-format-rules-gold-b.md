# 작업 지시서: pipelines/format-rules-gold-b

> 상태: 진행 중 · 브랜치: `pipelines/format-rules-gold-b` (최신 `main` `013264d` 위. 작업 중 #45·#55가 머지되어 그 위로 옮김) · 다음 작업: Gold B 형식 검사 연결 (`pipelines/gold-b-format-check`)

## 목표

Silver와 Gold B가 같이 쓰는 공통 형식 규칙(`docs/contracts/format_rules.yaml`)과 검사 코드(`pipelines/format_rules.py`)에 Gold B가 필요한 것을 더한다. 첫 번째로 주문상품 단가 하한을 5,900원으로 맞춘다.

## 사용자 결정 (2026-10-22)

- 주문상품 단가(`unit_price`) 최솟값을 1에서 5,900으로 바꾼다 (상품 시드 가격 규칙, Gold B 설계).
- 공통 규칙은 Silver와 Gold B가 같은 파일을 같이 쓴다. Gold B 전용 규칙 파일을 따로 만들지 않는다.
- push와 PR은 사용자가 한다. 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 정한 기본값 (설계에 없는 세부, PR에서 현지 님 확인)

1. **회원(`members`)은 DB 정의(`db/schema/001_member.sql`)를 옮긴다.** 규칙표의 원칙(원천 정의를 그대로 옮김)과 같다. Silver `members.py`보다 엄격한 점: 성별·가입 경로·연령대 허용 값, `member_id` UUID 형식, 탈퇴 시각 ≥ 가입 시각, 개인정보 컬럼 금지.
2. **클릭(`clickstream`)은 시뮬레이터 `ClickEvent`를 옮긴다.** ID 3개는 UUID, `event_type`은 `view`·`cart_add`, `article_id`는 숫자 10자리(상품 시드 검사: 숫자로만, 길이가 모두 같음).
3. **리뷰(`reviews`)는 Silver가 지금 받는 `review.v2` 작성 이벤트를 옮긴다.** 리뷰 컬럼은 민혁 님 확정 전이다.
4. **개인정보 컬럼이 들어오면 그 컬럼 이름으로 `INVALID_VALUE`.** 오류 사유 네 가지 체계를 유지한다.
5. **오류를 전부 돌려주는 `errors()`:** 필드마다 첫 오류 하나 → 금지 필드 → 조건 검사 순서다. 오류가 난 필드를 쓰는 조건 검사는 건너뛴다(같은 원인으로 오류가 겹치지 않게). `validate()`는 `errors()`의 첫 오류를 내므로 Silver가 보는 결과는 그대로다.
6. 데이터셋마다 원천(`source`)을 적을 수 있게 한다. 적지 않은 데이터셋은 맨 위 `source`를 따른다.

## 이번에 하지 않는 것

- 시각 형식을 지문 함수(#55)와 같은 모양으로 좁히기, 모르는 실패 코드 허용 → 현지 님과 정한 뒤
- Silver의 회원·클릭·리뷰 검사를 규칙표로 바꾸기 → 현지 님 코드
- Gold B 형식 검사 코드(JSON 파싱, `__op` 처리, 지문, 원문 가리기) → `pipelines/gold-b-format-check`
- 판정 잡의 규칙 버전 설정(`agent/detect/rules.py`의 `format_rule_version`) → 주현 님께 0.2.0을 알림

## 만드는 것

- `docs/contracts/format_rules.yaml`: 버전 0.2.0, Gold B 사용 승인, `unit_price` 5,900, 회원·클릭·리뷰 규칙
- `pipelines/format_rules.py`: `errors()`, 참/거짓 타입, 문자열 모양(`pattern`), 금지 필드(`forbidden_fields`), 데이터셋별 원천
- `pipelines/tests/test_format_rules.py`: 공통 검사기 시험
- `pipelines/silver/tests/test_transactions.py`: 단가 5,900에 맞춘 시험 데이터, 버전 문자열
- `docs/contracts/README.md`: 바뀐 범위·단가·검사 함수 설명
- `docs/BRANCHES.md` 한 줄

## 작업 순서

1. 작업 지시서·브랜치 대장 커밋
2. 단가 5,900·버전 0.2.0·계약 문서·Silver 시험 데이터 커밋
3. `errors()` 커밋
4. 새 규칙 종류와 회원·클릭·리뷰 규칙, Gold B 사용 승인 커밋
5. 시험 실행, Gold B 샘플 대조, 작업 결과 기록

## 완료 확인

- [x] `python -m pytest -q pipelines` 통과 (Silver 포함, 86개)
- [x] `validate()`가 내는 첫 오류가 바뀌지 않았는지 (12,621개 행 비교, 차이 0)
- [x] Gold B 샘플 31개의 기대 오류와 규칙표 결과 비교 (30개 중 28개 같음, 다른 2개는 아래 이유)
- [x] `git diff --check`

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** 공통 형식 규칙을 0.2.0으로 올렸다. 주문상품 단가 하한을 5,900원으로 맞추고, Gold B 사용을 승인하고, 회원·클릭·리뷰 규칙과 오류를 전부 돌려주는 `errors()`를 더했다. Silver가 보는 결과는 단가 하한 말고는 그대로다.
- **무엇을 바꿨나:**
  - `docs/contracts/format_rules.yaml`: 버전 0.2.0, `runtime_connected.gold_b: true`, `order_items.unit_price` 최솟값 5,900, 데이터셋 `members`·`clickstream`·`reviews` 추가(각자 `source` 표시), 맨 위 설명 주석
  - `pipelines/format_rules.py`: `errors()`, `validate()`는 `errors()`의 첫 오류, 참/거짓 타입(`boolean`), 문자열 전체 모양(`pattern`), 금지 필드(`forbidden_fields`), 데이터셋별 원천(`source`) 읽기와 정의 검사
  - `pipelines/tests/test_format_rules.py`(새 파일, 공통 검사기 시험 28개)
  - `pipelines/silver/tests/test_transactions.py`: 단가 5,900에 맞춘 시험 데이터(단가 500→5,900, 기본 주문 총액·결제 금액 1,000→11,800, 1,200→12,000, 차이 −200은 유지), 버전 문자열 0.2.0, #55 지문 시험의 결제 금액 기대값
  - `docs/contracts/README.md`: 범위(회원·클릭·리뷰 추가), Gold B 사용 승인, 단가 5,900 문장, 검사 함수와 새 규칙 종류 설명
- **왜 그렇게 했나:**
  - 단가 5,900: 상품 시드의 가격 규칙(5,900원 이상, 끝자리 900원)이라 그보다 낮은 단가는 데이터가 깨진 신호다. DB 정의(0보다 큼)보다 좁은 업무 기준이라 규칙표 그 줄에 주석으로 남겼다.
  - `validate()`를 `errors()`의 첫 오류로 바꿔 검사 규칙이 한 곳에만 있게 했다. 두 함수가 따로 있으면 Silver와 Gold B의 판단이 갈라질 수 있다.
  - 오류가 난 필드를 쓰는 조건 검사를 건너뛴다: 상태 값이 틀린 결제에 "실패인데 실패 코드 없음"까지 붙이거나, 읽을 수 없는 시각을 비교하다 멈추지 않게 하려는 것이다.
  - 회원은 Silver 코드가 아니라 DB 정의를 옮겼다. 규칙표의 원칙이 "원천 정의를 그대로 옮김"이고, Silver `members.py`는 성별·가입 경로·연령대 허용 값과 UUID 형식을 보지 않는다.
  - 개인정보 컬럼은 값 없이 필드 이름으로 `INVALID_VALUE`: 오류 사유 네 가지 체계를 유지하고, 원장에 값이 남지 않게 했다.
- **확인한 결과:**
  - PC Python 3.12로 `python -m pytest -q pipelines` 86개 통과 (최신 `main` `013264d` 위).
  - 바꾸기 전 검사기(`main`)와 바꾼 검사기에 Silver 데이터셋 3개의 행 12,621개(필드 1~3개를 망가뜨린 행)를 넣어 `validate()` 결과를 비교했다. 예외 종류·필드·사유·규칙 ID·메시지가 다른 행은 0개였다.
  - Gold B 샘플 30개(JSON이 깨진 1개는 Gold B 쪽 처리라 제외)를 `errors()`로 검사했다. 28개가 샘플의 기대 오류와 같았다. 다른 2개: `unknown_failure_code`(규칙표가 아직 실패 코드 5개만 받음, 미정 항목), `member_with_pii_column`(샘플의 사유가 비어 있었고 이번에 `INVALID_VALUE`로 정함).
  - 작업 중 `main`에 #45·#55가 머지되어 브랜치를 그 위로 옮겼다. 합친 상태에서 #55가 넣은 지문 시험 1개가 기본 결제 금액(11,800) 때문에 실패해서 기대값을 맞췄다.
  - `git diff --check` 통과. Ruff는 이 PC에 없어 돌리지 않았다.
- **알려진 한계·남은 일:**
  - 현지 님 합의가 필요한 것: 단가 하한 5,900(계약 문서에 "별도 합의 없이 넣지 않는다"고 적혀 있었음), 회원 규칙을 DB 정의 기준으로 한 것, 리뷰를 review.v2 기준으로 옮긴 것, 개인정보 컬럼 사유.
  - 다음 버전으로 미룬 것: 시각 형식을 지문 함수와 같은 모양으로 좁히기, 모르는 실패 코드 받아들이기.
  - Silver의 회원·클릭·리뷰는 아직 자체 코드로 검사한다. 규칙표로 바꾸면 사유가 달라지는 곳이 있다: 시각을 읽지 못할 때(Silver `TYPE_MISMATCH`, 규칙표 `INVALID_VALUE`), 탈퇴했는데 탈퇴 시각이 없을 때(Silver `INVALID_VALUE`, 규칙표 `MISSING_FIELD`), 리뷰 필수 문자열이 없을 때(Silver `INVALID_VALUE`, 규칙표 `MISSING_FIELD`).
  - 판정 잡 설정(`agent/detect/rules.py`의 `format_rule_version = "0.1.0"`)을 0.2.0으로 바꿔야 한다 (주현 님).
  - Gold B 샘플의 `member_with_pii_column` 기대 사유는 Gold B 형식 검사 브랜치에서 `INVALID_VALUE`로 고친다.
  - `docs/BRANCHES.md`의 `pipelines` 표 중간에 빈 줄 두 개가 있어(`main`에 이미 있음) 그 아래 줄이 표로 보이지 않는다. 다른 줄을 건드리지 않으려고 이 PR에서는 고치지 않았다.
