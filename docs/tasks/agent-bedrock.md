# 작업 지시서: agent/bedrock

> 상태: 완료(가짜 클라이언트 시험까지) · 브랜치: `agent/bedrock` · 다음 작업: 실제 Bedrock·Athena 확인, Airflow DAG 연결(인프라 담당)

## 목표

조사 루프의 `converse` 자리에 **진짜 Bedrock 호출**을 꽂고, 조사를 5분마다 한 번 실행하는 진입점을 만든다. 리포트와 실행 기록은 `agent` 표에 새 줄로 쌓는다.

## 만드는 것

- `agent/investigator/bedrock_io.py` + `test_bedrock_io.py`
- `agent/investigator/run_investigation.py` + `test_run_investigation.py`
- `agent/investigator/try_model.py` + `test_try_model.py` (진짜 모델 시험대)
- `agent/investigator/Dockerfile`, README 보강

## 만들지 않는 것

- 모델 ID 결정, 권한(IAM), Airflow DAG, 이미지 등록 (인프라 담당과 정함)
- 승인 화면, 재처리 요청

## 완료 확인

- [x] 시험 네 파일이 모두 통과한다 (`test_investigator`, `test_bedrock_io`, `test_run_investigation`, `test_try_model`)
- [x] 비밀값, 계정 ID, 엔드포인트가 코드·문서에 없다
- [ ] 진짜 Bedrock 호출 (내 컴퓨터, API 키) — 아직
- [ ] 진짜 Athena 쓰기 (`agent` 표 생성 후) — 아직

## 작업 결과

- 모델 호출 실패는 429·5xx·네트워크 오류만 3번 재시도하고, 오류 글에는 키와 요청 내용을 넣지 않는다.
- 이미 조사한 이상(오류 제외)은 다시 조사하지 않는다. 오류는 2번까지 다시 한다.
- 한 번 실행에서 조사하는 이상 수는 `INVESTIGATE_MAX`(기본 3)로 비용 상한을 둔다.
