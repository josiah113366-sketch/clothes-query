# 작업 지시서: agent/detect-skeleton

> 상태: 완료 · 브랜치: `agent/detect-skeleton` · 다음 작업: `agent/skeleton`

## 목표

5분마다 실행되는 **판정 잡의 틀**을 만든다: 원장을 읽어 규칙 R1·R3·R4로 판정하고, 이상 이력에 회차별로 새 줄을 쌓고, 재처리로 교체된 시간대를 다시 판정한다. Athena 연결, Airflow 작업, 에이전트 본체는 만들지 않는다.

## 만드는 것

- `agent/detect/rules.py`: 규칙 3개(순수 함수), 임계값 `Config`, `anomaly_id`, 이상 줄 만들기
- `agent/detect/job.py`: 순찰 한 바퀴(`run_once`), 재판정(`redetect`)
- `agent/detect/test_job.py`: sqlite 가짜 원장 시험
- `agent/detect/README.md`

## 만들지 않는 것

- 실제 Athena 읽기·S3 Parquet 쓰기 연결 (접근 권한이 생긴 뒤)
- 5분마다 실행하는 Airflow 작업, 재처리 다음의 재판정 이어 붙이기 (플랫폼 담당과 협의)
- 이상 구간 합치기(`episode_*`)

## 완료 확인

- [x] `python3 agent/detect/test_job.py` 가 "모두 통과"를 출력한다 (시험 19건)
- [x] 비밀값, 계정 ID, 개인정보가 없다(가짜 데이터만 사용)

## README 갱신

- `agent/detect/README.md` 신규

## 작업 결과

- **한 줄 요약:** 5분마다 도는 판정 잡의 틀(순찰 한 바퀴, 회차별 이상 이력 쌓기, 재처리 뒤 재판정과 해결 여부 확인)을 만들었다.
- **무엇을 만들었나:** `agent/detect/`의 `rules.py`, `job.py`, `test_job.py`, `README.md`.
- **왜 그렇게 했나:** 바깥과는 `query`, `write` 함수 두 개로만 만나게 해서, 가짜 데이터로 먼저 시험하고 Athena는 나중에 이 두 함수만 바꿔 연결하도록 했다. 이상 이력은 덮어쓰지 않고 회차(`run_id`)별로 쌓는다(설계 문서의 결정). 재처리 뒤 재판정은 Gold B 담당과 합의한 임시 방식(5분마다 `reprocess_events` 확인)을 썼다.
- **입력과 출력:** 입력은 원장 4개와 정리 뷰 2개, `reprocess_events`. 출력은 `anomaly`, `detection_runs`(제안), `reprocess_events`의 `REDETECTED`·`VERIFIED` 줄.
- **확인한 결과:** sqlite 가짜 원장에서 시험 19건이 모두 통과했다. 장애 시작 5분 뒤에는 3분 대기 때문에 안 잡히고 10분 뒤 잡힘, 지연·깨진 메시지·측정 줄 없음 탐지, 옛 규칙 버전은 세지 않음, 같은 순찰을 두 번 돌지 않음, 재처리 후 이상이 그대로면 `STILL_OPEN`·사라지면 `RESOLVED`, 옛 이상 줄이 지워지지 않음.
- **알려진 한계·남은 일:** Athena·Airflow 미연결. `detection_runs` 필요 여부, 이상 구간 합치기, 임계값, `FAILED` 요청 처리는 미정이다.
