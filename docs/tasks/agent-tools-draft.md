# 작업 지시서: agent/tools-draft

> 상태: 완료 · 브랜치: `agent/tools-draft` · 다음 작업: `agent/skeleton`

## 목표

조사 에이전트가 쓸 **읽기 전용 도구 11개와 SQL 울타리**를 만든다. 에이전트 본체(Bedrock 호출), 승인 화면, 탐지 잡은 만들지 않는다.

## 만드는 것

- `agent/tools/guard.py`: SELECT만, 허용된 표만, `LIMIT` 필수, 정답표·원문 차단, 시간 범위 한도
- `agent/tools/ledger_tools.py`: 도구 11개, 도구 목록(Bedrock 정의 모양), 실행 함수
- `agent/tools/test_tools.py`: sqlite 가짜 원장 시험
- `agent/tools/README.md`

## 만들지 않는 것

- Bedrock을 부르는 에이전트 본체, 승인 화면, 탐지 잡 (→ 이후 브랜치)
- Athena 실행 연결 (접근 권한이 생긴 뒤)

## 완료 확인

- [x] `python3 agent/tools/test_tools.py` 가 "모두 통과"를 출력한다 (시험 32건: 도구 결과와 울타리)
- [x] 모든 도구가 만든 SQL이 울타리를 통과한다
- [x] 비밀값, 계정 ID, 개인정보가 없다

## README 갱신

- `agent/tools/README.md` 신규

## 작업 결과

- **한 줄 요약:** 조사 에이전트가 쓰는 읽기 전용 도구 11개와, 위험한 SQL을 막는 울타리를 만들었다.
- **무엇을 만들었나:** `agent/tools/`의 `guard.py`, `ledger_tools.py`, `test_tools.py`, `README.md`.
- **왜 그렇게 했나:** 에이전트가 SQL을 직접 쓰면 정답표를 읽거나 표를 바꿀 위험이 있어서, 정해진 질문 11개만 부르게 했다. 시나리오 3개의 "다른 원인 지우기"에 필요한 조회를 시나리오별로 묶었다.
- **입력과 출력:** 입력은 도구 이름과 인자(시간 범위 UTC, PG·토픽 이름 등). 출력은 줄 목록(최대 200줄). 읽는 표는 Gold B 원장·뷰·`anomaly`·`reprocess_events`뿐이다.
- **확인한 결과:** sqlite 가짜 원장에서 시험 32건이 모두 통과했다(성공 결제 중복은 결제 시각이 구간 밖이어도 적재 시각으로 잡힘, 누락 2칸, 중복 1건, 멈춤 4분 STOPPED, 깨진 메시지 현재 규칙 버전만 계산 등).
- **알려진 한계·남은 일:** Athena에서는 아직 실행하지 않았다. 표·컬럼은 문서를 보고 가정했다. `raw_sample` 접근 여부, `detection_runs` 표 필요 여부, 한도 값(6시간·200줄)은 미정이다.
