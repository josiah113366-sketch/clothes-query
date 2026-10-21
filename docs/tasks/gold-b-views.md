# 작업 지시서: pipelines/gold-b-views

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-views` (`pipelines/gold-b` 위에서 갈라짐) · 다음 작업: Athena 권한이 생기면 뷰 생성과 샘플 확인

## 목표

설계 문서에 있는 정리 뷰 3개(`payment_conflicts`, `payment_attempts`, `malformed_messages`)의 SQL을 `pipelines/gold_b/views/`에 파일로 남긴다 (3단계). Athena에서 만들고 샘플로 확인하는 것은 권한이 생긴 뒤에 한다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「탐지가 읽는 것」(뷰 SQL과 컬럼), 「처리 규칙」(중복 제거, 실패 원인 분류), 3단계 체크리스트
- `pipelines/gold_b/ddl/payment_events.sql`, `malformed_events.sql`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- #36이 머지 전이라 `pipelines/gold-b` 위에서 갈라졌다. push는 #36 머지 뒤 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 만드는 것

- `pipelines/gold_b/views/payment_conflicts.sql`, `payment_attempts.sql`, `malformed_messages.sql`: 설계 문서의 SQL을 그대로 옮김 (맨 위에 설명 주석 두 줄)
- `pipelines/gold_b/views/README.md`: 뷰 설명, Athena에서 만드는 순서, 처음 만들 때 확인할 것
- `pipelines/gold_b/tests/test_views.py`: 파일과 설계 문서의 SQL이 같은지
- `pipelines/gold_b/README.md`, 설계 문서 3단계 체크, `docs/BRANCHES.md` 한 줄

## 만들지 않는 것

- Athena에서 뷰 생성, 샘플 결과 확인 (Athena 권한, 재영 님)
- 탐지가 묶어 세는 SQL (탐지 규칙에서 정함)

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경)
- [ ] 뷰 파일 3개가 설계 문서의 SQL과 같은지
- [ ] Athena에서 뷰 생성과 샘플 확인 → **대기** (권한)

## 작업 결과 (머지 전에 작성한다)
