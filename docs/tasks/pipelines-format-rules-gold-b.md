# 작업 지시서: pipelines/format-rules-gold-b

> 상태: 진행 중 · 브랜치: `pipelines/format-rules-gold-b` (최신 `main` `fc594de`에서 갈라짐) · 다음 작업: Gold B 형식 검사 연결 (`pipelines/gold-b-format-check`)

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

- [ ] `python -m pytest -q pipelines` 통과 (Silver 포함)
- [ ] `validate()`가 내는 첫 오류가 바뀌지 않았는지
- [ ] Gold B 샘플 31개의 기대 오류와 규칙표 결과 비교 (다른 것은 이유 기록)
- [ ] `git diff --check`

## 작업 결과 (머지 전에 작성한다)
