# 작업 지시서: agent/detect-athena

> 상태: 완료 · 브랜치: `agent/detect-athena` (`agent/detect-skeleton`(PR #29) 위에 쌓음) · 다음 작업: 규칙 R6(Silver 총액 검사 결과), Airflow DAG 연결

## 목표

판정 잡이 Athena와 실제로 만나게 한다: `query(sql)`, `write(표, 줄)`을 진짜(Athena)로 만들고, 5분마다 한 번 실행하는 진입점과 컨테이너 이미지 틀을 만든다. 진짜 Athena 실행, Airflow DAG, 이미지 저장소(ECR) 등록은 만들지 않는다.

## 먼저 읽을 것

- `agent/detect/README.md` (판정 잡 설명)
- `docs/design/agent/anomaly-answer-key.md` (이상 이력과 재처리 기록 설계)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 쓰기 방식(`INSERT INTO`)과 표 3개의 시간 폴더(`dt`, `hour`) 가정은 **제안 그대로 시작**한다. 인프라·Gold B 담당 답을 받아 고친다.

## 만드는 것

- `agent/detect/athena_io.py`: Athena 쿼리 보내기·기다리기·결과 변환, `INSERT INTO` 쓰기, 쓸 수 있는 표 3개와 컬럼 타입(`TABLE_SPECS`)
- `agent/detect/run_job.py`: 5분마다 한 번 실행하는 진입점
- `agent/detect/Dockerfile`, `requirements.txt`: 이미지 틀
- `agent/detect/test_athena_io.py`: 가짜 Athena 클라이언트 시험
- `agent/detect/job.py`: 같은 순찰을 다시 돌려도 이상 줄이 두 번 쌓이지 않게 함
- `agent/detect/README.md` 갱신: 실행 방법, 필요한 권한, 쓰기 방식 제안

## 만들지 않는 것

- 진짜 Athena 실행 확인 (표가 Athena에 올라온 뒤)
- Airflow DAG, 이미지 저장소(ECR) 등록과 배포 (인프라 담당)
- 규칙 R6 (Silver 품질 결과)

## 완료 확인

- [x] `python3 agent/detect/test_athena_io.py` 가 "모두 통과"를 출력한다 (시험 20건)
- [x] `python3 agent/detect/test_job.py` 가 "모두 통과"를 출력한다 (시험 40건)
- [x] 비밀값, 계정 번호, 개인정보가 없다 (역할은 이름도 적지 않고 필요한 권한만 적음)

## README 갱신

- `agent/detect/README.md`의 "Athena 연결과 실행"과 "알아야 할 것" 절

## 작업 결과

- **한 줄 요약:** 판정 잡이 Athena로 쿼리하고 이력을 쓰는 연결 코드와 실행 진입점, 이미지 틀을 만들었다.
- **무엇을 만들었나:** `athena_io.py`, `run_job.py`, `Dockerfile`, `requirements.txt`, `test_athena_io.py`와 `job.py`의 중복 쓰기 방지.
- **왜 그렇게 했나:** 판정 잡은 `query`와 `write` 두 함수로만 바깥과 만나게 만들어 두었으므로, 이 두 함수만 Athena용으로 만들면 된다. 쓰기는 허용된 표 3개와 컬럼 목록만 받아 이름은 검증하고 값은 이스케이프해서 잘못된 입력이 쿼리로 새지 않게 했다. 시각은 문자열이 아니라 `TIMESTAMP` 타입으로 쓴다(Gold B 담당 요청).
- **입력과 출력:** 환경 변수 `ATHENA_WORKGROUP`(필수), `ATHENA_DATABASE`(기본 `gold_b`). 출력은 순찰 결과 요약 JSON 한 줄.
- **확인한 결과:** 가짜 Athena 클라이언트 시험 20건과 판정 잡 시험 40건이 모두 통과했다. 쿼리 상태 대기, 결과 타입 변환과 페이지 넘김, 실패·시간 초과 오류, 작은따옴표 이스케이프, 허용되지 않은 표·컬럼 거절, 큰 쓰기의 분할, 진입점 동작을 확인했다.
- **리뷰 반영(재영 님 #29 지적):** 저장 도중 실패 후 재시도에서 이상 줄이 중복되던 것을 고쳤다. 같은 순찰 번호로 이미 쓴 줄은 다시 쓰지 않고, 순찰 기록은 한 줄만 쓰고, 재판정 순찰 번호를 요청·교체 구간으로 고정했고, Airflow 논리 시각(`JUDGE_TICK`)으로 순찰 번호를 고정할 수 있게 했다. 실패를 흉내 낸 시험 9건을 더했다.
- **알려진 한계·남은 일:** 진짜 Athena에서는 아직 실행하지 않았다(표가 올라온 뒤 문법과 `INSERT`를 확인). 표 정의(시간 폴더 가정), 쓰기 방식은 Gold B·인프라 담당과 확정해야 한다. 이미지 저장소와 Airflow DAG 연결은 인프라 담당 몫이다.
