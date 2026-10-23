# 작업 지시서: agent/conclusion-check

> 상태: 완료(가짜 모델 시험까지, 진짜 모델 확인은 사용자 PC에서) · 브랜치: `agent/conclusion-check` (`agent/bedrock`(PR #54) 위에 쌓음) · 다음 작업: 진짜 모델로 `--scenario hard` 재확인

## 목표

진짜 모델 시험에서 Haiku가 `mixed` 시나리오(PG 장애 + 성공 결제 중복)에서 **중복을 확인하는 도구를 부르지 않고 결론에 "원본 데이터에 오염이 없습니다"라고 단정**했다(3번 모두). 원인 층은 맞았지만 리포트에 틀린 문장이 들어갔다. 리포트 검사가 사실(FACT) 항목의 근거만 보고 결론 문장은 보지 않아서 통과됐다. 이를 막는다.

## 만드는 것

- `agent/investigator/report.py`: 결론과 사실(FACT) 문장에서 "없다/정상이다" 단정을 찾아, 그것을 확인하는 도구를 부르지 않았으면 되돌려 보내는 검사(`unsupported_denials`, `DENIAL_RULES`)
- `agent/investigator/prompt.py`: 규칙 4(PG 장애일 때도 다른 이상이 없다고 단정하지 않고 `duplicate_success_orders`로 확인), 규칙 8(확인한 것만 쓴다)
- 시험 추가(`test_investigator.py`), `try_model.py` 출력에 검사를 못 넘긴 점 표시

## 만들지 않는 것

- 의미를 이해하는 검사(낱말 규칙이라 놓치거나 필요 없이 걸리는 문장이 있을 수 있다)

## 완료 확인

- [x] `python3 agent/investigator/test_investigator.py` 등 시험 4파일이 모두 통과한다
- [ ] 진짜 모델로 `--scenario hard --repeat 3 --show`를 다시 돌려 `mixed`의 결론이 달라졌는지 본다 — 아직

## 작업 결과

결론·사실 문장의 근거 없는 단정을 되돌려 보내는 검사를 추가했다. 되돌림은 기존 한도(2번)를 따른다.
