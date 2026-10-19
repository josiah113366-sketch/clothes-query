# 작업 지시서: agent/skeleton

> 상태: 완료 · 브랜치: `agent/skeleton` (`agent/tools-draft` 위에 쌓음) · 다음 작업: Bedrock 연결(`converse` 구현)

## 목표

조사 에이전트의 **뼈대**를 만든다: 이상 하나를 받아 모델이 조회 도구를 부르며 조사하고, 근거가 붙은 원인 리포트를 제출하는 루프. 모델은 함수 하나로만 만나게 해서 가짜 모델로 시험한다. 실제 Bedrock 호출, 승인 화면, 재처리 요청은 만들지 않는다.

## 먼저 읽을 것

- `docs/design/agent/anomaly-answer-key.md` (PR #28): 이상 이력, 정답표, 채점
- `agent/tools/README.md` (PR #30): 조회 도구 11개와 울타리

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 리포트 형식(`anomaly_id`, `cause_layer`, `claims`)은 **제안 그대로 시작**한다. 리뷰에서 의견을 받아 고친다.
- 브랜치는 `agent/tools-draft`(PR #30) 위에 쌓는다. tools가 먼저 머지되어야 한다.

## 만드는 것

- `agent/investigator/loop.py`: 조사 루프 `investigate(anomaly, converse, execute, ...)`
- `agent/investigator/prompt.py`: 지시문
- `agent/investigator/report.py`: 리포트 형식, 검사, 제출 도구 정의
- `agent/investigator/test_investigator.py`: 가짜 모델 시험
- `agent/investigator/README.md`

## 만들지 않는 것

- Bedrock을 실제로 부르는 `converse` 구현, 모델 ID, 권한 (→ 다음 브랜치)
- 승인 화면, 재처리 요청·승인 쓰기, Airflow 호출
- 리포트 저장

## 완료 확인

- [x] `python3 agent/investigator/test_investigator.py` 가 "모두 통과"를 출력한다 (시험 22건)
- [x] `agent/eval`의 `score_reports()`가 이 리포트를 읽어 층 판별·근거 연결을 계산한다 (확인함)
- [x] 비밀값, 계정 ID, 개인정보가 없다

## README 갱신

- `agent/investigator/README.md` 신규

## 작업 결과

- **한 줄 요약:** 이상 하나를 받아 모델이 조회 도구를 불러 조사하고, 근거가 붙은 리포트를 내는 조사 루프의 뼈대를 만들었다.
- **무엇을 만들었나:** `agent/investigator/`의 `loop.py`, `prompt.py`, `report.py`, `test_investigator.py`, `README.md`.
- **왜 그렇게 했나:** 모델 호출을 함수 하나(`converse`)로만 만나게 해서 가짜 모델로 먼저 시험하고, 나중에 Bedrock을 이 함수에만 연결한다. 에이전트가 근거 없이 결론을 내거나 부르지 않은 도구를 근거로 대지 못하게 리포트를 검사해 되돌린다. 읽기 전용이라 재처리를 요청하는 도구는 아예 없다.
- **입력과 출력:** 입력은 이상 한 줄(`anomaly`)과 모델 함수, 조회 실행 함수. 출력은 리포트(원인 층, 결론, 주장과 근거, 조사 기록). 정답 관련 값은 모델에 보내지 않는다.
- **확인한 결과:** 가짜 모델 시험 22건 통과(정상 흐름, 근거 없는 리포트 거절, 울타리·없는 도구·인자 누락 처리, 글만 쓴 경우, 한도 초과, 소비 지연·성공 결제 중복 흐름). `agent/eval`의 `score_reports()`가 이 리포트를 읽는 것을 따로 확인했다.
- **알려진 한계·남은 일:** 진짜 모델로 돌려 보지 않았다(시험은 배관만 확인). `converse`의 Bedrock 연결, 모델 ID, 권한, 지시문 조정, 리포트 저장 위치, 승인 화면 연결은 남았다. `agent/tools`(PR #30)가 먼저 머지되어야 한다.
