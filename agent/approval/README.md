# agent/approval

재처리 **승인의 백엔드 규칙**이다. 대시보드(승인 화면)는 여기 함수를 부르기만 한다. 규칙 전체 설명은 [docs/design/agent/approval-flow.md](../../docs/design/agent/approval-flow.md).

## 쉬운 설명: 결재 서류

재처리는 "원장을 다시 만드는" 일이라 함부로 시작하면 안 된다. 그래서 서류 한 장(요청 번호 `request_id`)을 만들고, 사람이 도장(승인)을 찍어야 일이 시작된다. 이 파일은 서류 담당자다. 도장을 찍은 사람이 누구인지 적고, 같은 서류에 도장을 두 번 찍지 못하게 하고, 오래된 서류는 무효로 하고, 도장이 찍히면 Airflow에 작업을 시킨다.

## 어느 부분이 어느 코드인가

| 하는 일 | 코드 |
|---|---|
| 요청 만들기(REQUESTED) | `request_reprocess()` |
| 승인(APPROVED)하고 DAG 호출 | `approve()` → `start_run()` |
| 거절(REJECTED) | `reject()` |
| 요청의 현재 상태 계산(만료 포함) | `derive_state()`, `latest_row()` |
| 승인자 검사 | `check_actor()` |
| Airflow 호출(토큰 → dagRuns) | `AirflowClient.trigger()` |
| 설정(만료 60분, 재시도 2번, 규칙 → DAG) | `ApprovalConfig` |

## 화면에서 부르는 방법

```python
from approval import AirflowClient, ApprovalConfig, ApprovalError, approve, reject, request_reprocess

cfg = ApprovalConfig()                       # 규칙 -> DAG ID는 은서·현지 님과 정한 뒤 채운다
airflow = AirflowClient(url, user, password) # 접속 정보는 Kubernetes Secret에서 읽는다(코드에 넣지 않는다)
try:
    approve(request_id, actor=<로그인 이메일>, now=<UTC 현재>, query=io.query, write=io.write, trigger=airflow.trigger, cfg=cfg)
except ApprovalError as e:
    show_error(e.message)                    # e.code로 화면을 나눈다(BAD_STATE, ACTOR_REQUIRED, DUPLICATE_REQUEST 등)
```

`query`/`write`는 `agent/detect/athena_io.py`의 `AthenaIO.query`/`.write`와 같은 모양이다(대시보드는 전용 workgroup을 쓴다).

## 시험

```
python3 agent/approval/test_approval.py
```

## 알아야 할 것 (한계)

- **진짜 Athena·Airflow로는 돌려 보지 않았다.** sqlite 가짜 표와 가짜 Airflow로만 시험했다.
- **재처리 DAG ID가 정해지지 않았다.** 현지 님 제안 `silver_gold_a_reprocess`(R6)만 넣어 두었고, Gold B 재처리 DAG ID는 은서 님 답을 기다린다(None이면 요청을 거절한다).
- Airflow 접속 Secret의 키 이름(주소, 사용자, 비밀번호)은 인프라 담당 확인이 필요하다. 이 코드는 값을 인자로 받는다.
- 만료 60분, 재시도 2번은 팀 공지의 제안값이다(재시도 2번만 은서 님 동의).
- **화면 코드(`approval.py` 페이지)는 아직 없다.** 대시보드 담당과 정한 뒤 `dashboard/` PR로 올린다. 대시보드 이미지에 이 폴더를 함께 넣어야 한다.
- 같은 이상에 대한 중복 요청 검사는 최근 6시간의 REQUESTED 줄만 본다.
