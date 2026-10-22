# 작업 지시서: agent/review-fixes

> 상태: 완료 · 브랜치: `agent/review-fixes` · 다음 작업: 없음 (리뷰 반영)

## 목표

인프라 담당이 이미 머지된 `agent/reliability`(PR #14)와 `agent/tools`(PR #30)에 남긴 리뷰 지적 4건을 고친다. 새 기능은 만들지 않는다.

## 먼저 읽을 것

- `agent/reliability/README.md`, `agent/tools/README.md`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 없음

## 만드는 것

- `agent/reliability/reliability_queries.sql`, `test_reliability.py`, `README.md`: 표가 비어 있으면 `NO_DATA`, 누락 검사의 한계 표시와 파티션 확인 쿼리(Q1b)
- `agent/tools/ledger_tools.py`: `malformed_summary`가 사유가 있는 `malformed_events`를 읽음, `ledger_reliability`에 완전성 표시·빈 파티션 목록·`NO_DATA`
- `agent/tools/guard.py`: 시각을 UTC로 통일
- `agent/tools/test_tools.py`, `README.md`

## 만들지 않는 것

- Kafka 끝 offset과 비교하는 완전성 검증(아직 안 함, README에 한계로 적음)

## 완료 확인

- [x] `python3 agent/tools/test_tools.py` 가 "모두 통과"를 출력한다 (시험 40건)
- [x] `python3 agent/reliability/test_reliability.py` 가 "모두 통과"를 출력한다
- [x] 비밀값, 계정 번호, 개인정보가 없다

## README 갱신

- `agent/reliability/README.md`, `agent/tools/README.md`의 한계 절

## 작업 결과

- **한 줄 요약:** 이미 머지된 신뢰성 쿼리와 조회 도구의 리뷰 지적 4건(빈 표가 정상으로 나옴, 누락 검사의 한계, 없는 `reason` 컬럼 조회, 시간대 처리)을 고쳤다.
- **무엇을 만들었나:** 위 파일들의 수정과 시험 추가.
- **왜 그렇게 했나:** ① 빈 표의 마지막 시각이 비어 있으면 `OK`로 나오는 것은 "관제가 살아 있다"고 잘못 말하는 것이라 `NO_DATA`로 구분했다. ② 누락 검사가 비어 있어도 전체가 다 있다는 뜻이 아니므로 결과에 한계를 적고, 메시지가 없던 파티션을 보여 준다. ③ Gold B 뷰(`malformed_messages`)에는 사유가 배열(`errors`) 안에만 있어서, 사유가 컬럼으로 있는 오류 단위 원장(`malformed_events`)에서 읽도록 바꾸고 같은 메시지는 한 번만 센다. ④ `+09:00`이 붙은 시각이 시간대가 빠진 채 9시간 다른 구간을 조회하던 것을 UTC로 바꿔서 통일했다.
- **입력과 출력:** 도구 입력의 시각은 시간대(`Z`, `+00:00`, `+09:00`)가 있어도 없어도 UTC로 받는다.
- **확인한 결과:** 조회 도구 시험 40건, 신뢰성 쿼리 시험이 모두 통과했다. 시간대 변환, 빈 표 `NO_DATA`, 빈 파티션 목록, 사유별 깨진 메시지 수를 확인했고, 구간 맨 앞·맨 뒤가 빠져도 누락 검사가 0줄인 한계도 시험으로 확인했다.
- **알려진 한계·남은 일:** 쿼리는 Athena에서 아직 돌려 보지 않았다(`date_diff`, 배열 처리). 완전성을 Kafka 끝 offset과 비교하는 검증은 아직 없다.
