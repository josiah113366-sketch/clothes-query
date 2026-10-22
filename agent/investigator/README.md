# agent/investigator

**조사 에이전트의 뼈대**다. 이상(anomaly) 하나를 받아, 모델이 조회 도구를 골라 부르며 원인을 찾고, **근거가 붙은 원인 리포트**를 제출하게 하는 루프다.
진짜 모델(Bedrock)은 아직 연결하지 않았다. 모델은 함수 `converse` 하나로만 만나서, 지금은 가짜 모델로 시험한다.

## 쉬운 설명: 수사관과 조회 창구

- **탐지(`agent/detect`)**가 "15시 10분에 PG_A가 이상하다"고 사건 접수를 한다 (`gold_b.anomaly`).
- **조사 에이전트**가 사건 하나를 맡는다. 현장(데이터)을 직접 뒤지지 못하고, **조회 창구(`agent/tools`)에 질문 11개 중 하나씩만** 물을 수 있다.
- 수사관은 창구에서 받은 답으로 "원인은 결제 층이다, 근거는 이 조회 결과다"라는 **리포트**를 써서 낸다. 근거 없는 주장, 부르지 않은 도구를 근거로 댄 주장은 **되돌려 보낸다**(최대 2번).
- 채점관(`agent/eval`)이 나중에 이 리포트를 정답표와 비교한다.

## 한 바퀴의 흐름

```
이상 1건 → [모델] 도구를 고름 → [조회 창구] 울타리 검사 후 실행 → 결과를 [모델]에 돌려줌 → (반복) → submit_report → 리포트 검사 → 리포트
```

| 하는 일 | 코드 |
|---|---|
| 한 바퀴 돌리기 (모델 호출, 도구 실행, 결과 전달, 반복 한도) | `loop.py`의 `investigate()` |
| 모델에게 주는 원칙(읽기만, 근거 필수, 결제 장애면 재처리 권하지 않음, 오염은 재처리로 안 고쳐질 수 있음) | `prompt.py`의 `SYSTEM_PROMPT` |
| 리포트 형식과 검사(원인 층 4가지, 모든 주장에 근거, 부르지 않은 도구는 근거 불가) | `report.py`의 `check_report()`, `SUBMIT_REPORT_SPEC` |
| 조회 도구 11개와 울타리 | `agent/tools/` (PR 별도) |
| 시험 33건 | `test_investigator.py` |

## 리포트 형식 (제안)

```
{report_id, anomaly_id, cause_layer, conclusion, claims: [{text, kind, evidence: [{tool}]}], trace, problems?}
```
- `cause_layer`: `PAYMENT` / `INGEST` / `DATA_QUALITY` / `UNKNOWN`(증거가 부족하면 억지로 고르지 않음)
- `trace`: 어떤 도구를 어떤 인자로 불렀고 성공·오류·거절이었는지 (조사 과정 기록)
- `problems`: 2번 되돌려도 검사를 못 통과한 경우에만 붙는다. 채점에서 근거 없는 주장으로 센다.
- `claims[].kind`: `FACT`(확인된 사실: 도구 결과로 확인했고 **근거 필수**) / `ASSUMPTION`(추정: 도구로 확인 못 한 해석, 근거는 있으면 적음). 같은 시기에 변한 지표는 조사 단서일 뿐 원인으로 단정하지 않고 추정으로 적는다. 대시보드(PR #31)의 "확인된 사실 / 추정" 구분과 맞춘 것이다.
- **조회와 제출을 한 응답에 같이 요청하면 제출은 받지 않는다**(재영 님 리뷰). 모델이 이번 조회 결과를 보기 전에 낸 리포트이기 때문이다. 조회 결과를 전달한 **다음 응답**부터 제출할 수 있다. 되돌림 한도에 걸려도 받지 않는다.
- 사실이 하나도 없이 원인 층을 고르면 되돌려 보낸다(증거가 부족하면 `UNKNOWN`으로 낸다).
- `agent/eval`의 `score_reports()`가 같은 형식을 읽는다 (`anomaly_id`, `cause_layer`, `claims[].evidence`). 근거 연결 점수는 **확인된 사실(`FACT`)만** 센다(추정은 근거가 없어도 감점하지 않는다).

## 실제 모델 연결 (이 브랜치에서 추가)

| 파일 | 하는 일 |
|---|---|
| `bedrock_io.py` | Bedrock Converse 호출(`converse` 함수). 서비스 계정 권한(boto3) 또는 API 키(내 컴퓨터 시험용)로 부름. 429·5xx는 3번까지 재시도. 모델이 지원하지 않으면 `toolResult.status`를 뺌 |
| `run_investigation.py` | Airflow가 5분마다 한 번 실행. 아직 조사 안 한 OPEN 이상을 찾아 조사하고 `agent.investigation_reports`, `agent.investigation_runs`에 새 줄로 쌓음 |
| `try_model.py` | 진짜 모델 시험대. 가짜 원장(sqlite)에 만든 시나리오 4개(결제·적재·데이터 품질·정상)로 돌려 층 판별·호출 수·거절 수·토큰을 출력 |
| `Dockerfile` | 이미지 제안. 빌드 위치는 `agent` 폴더 |

환경 변수(비밀값 없음): `ATHENA_WORKGROUP`, `BEDROCK_MODEL_ID`, `AWS_REGION`(기본 ap-northeast-1), `INVESTIGATE_MAX`(기본 3), `INVESTIGATE_LOOKBACK_HOURS`(기본 24). `AWS_BEARER_TOKEN_BEDROCK`은 내 컴퓨터 시험에서만 쓴다.

### 모델 고르기 전에 확인할 것

| 확인 | 이유 |
|---|---|
| 모델 ID 또는 추론 프로필 ID가 맞는가 (예: `jp.`, `apac.` 접두) | 도쿄에서 모델 ID만으로는 안 불리는 모델이 있다 |
| 도구 호출(tool use)을 지원하는가 | 지원하지 않으면 조사 루프가 돌지 않는다 |
| 도쿄 가격을 확인했는가 | 가격표는 지역마다 다르다 |
| `toolResult.status`를 지원하는가 | 지원하지 않는 모델은 코드가 자동으로 뺀다 |

모델 후보 비교는 한국어 글 생성 벤치마크가 아니라 **도구 호출 시험**으로 해야 한다: `try_model.py --scenario all --repeat 3`.

## 실행

```
cd agent/investigator
python3 test_investigator.py     # 가짜 모델·가짜 원장 시험 (표준 라이브러리만 사용)
python3 test_bedrock_io.py && python3 test_run_investigation.py && python3 test_try_model.py

# 내 컴퓨터에서 진짜 모델 시험 (키는 환경 변수로만. 파일이나 채팅에 적지 않는다)
# 환경 변수 AWS_BEARER_TOKEN_BEDROCK, BEDROCK_MODEL_ID를 정한 뒤:
python3 try_model.py --scenario all --repeat 3
# 시나리오: basic(pg·lag·dup) / hard(falsealarm·nodata·mixed) / all(여섯 개). hard의 정답은 시험대 제작자의 판단이다
# 모델이 쓴 결론과 주장(사실/추정)을 눈으로 보려면 --show
python3 try_model.py --scenario hard --repeat 3 --show
```

## 알아야 할 것 (한계)

- **진짜 모델로는 아직 돌려 보지 않았다**(`bedrock_io.py`도 가짜 클라이언트로만 시험함). 시험은 정해 둔 순서대로 도구를 부르는 가짜 모델이라 **배관(도구 호출·결과 전달·리포트 검사)만 확인**한다. 모델이 도구를 잘 고르고 원인을 잘 맞히는지는 Bedrock을 연결한 뒤 정답표로 채점해야 안다.
- **모델 ID, Athena 권한은 정해지지 않았다.** 실제 Athena에도 아직 돌려 보지 않았다(`agent` 표 DDL이 PR로 올라가 있고 생성 전).
- 지시문(`prompt.py`)은 **제안**이다. 실제 모델의 답을 보고 고쳐야 한다.
- 반복 한도(10회), 되돌리는 횟수(2번)는 임의 값이다.
- 이 폴더는 **조사까지만** 한다. 재처리 요청, 승인 화면, Airflow 호출은 없다(에이전트는 읽기 전용).
- **`agent/tools`가 먼저 머지되어야 한다.** 이 폴더가 `agent/tools`를 불러 쓴다.
- 리포트를 어디에 저장하는지(표, 파일)와 승인 화면이 무엇을 읽는지는 **미정**이다.
