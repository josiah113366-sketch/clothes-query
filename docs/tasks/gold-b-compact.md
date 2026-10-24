# 작업 지시서: pipelines/gold-b-compact

> 상태: 완료 (#88, 2026-10-23 머지) · 브랜치: `pipelines/gold-b-compact` (`pipelines/gold-b-reprocess` 위에서 갈라짐, 최신 `main` #78까지 포함) · main 대상 PR 제출 (`pipelines/gold-b-reprocess` 머지 뒤) · 남은 일: DAG (재영 님)

## 목표

원장 시간 폴더 안의 작은 Parquet 파일을 하루 1회 하나로 합치는 **파일 합치기 잡**(6단계)을 만든다. 적재 잡과 수집기가 1분마다 파일을 만들어서, 합치지 않으면 한 시간 폴더에 60개 넘게 쌓이고 Athena 조회가 느려진다. Airflow DAG는 만들지 않는다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「저장」, 「처리 규칙」의 중복 제거(유입량은 중복을 지우지 않음), 6단계 체크리스트
- `pipelines/gold_b/ledger.py` (저장소), `pipelines/gold_b/jobs/reprocess.py` (같은 폴더를 바꾸는 다른 잡)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 원장 공통 도구(`ledger.py`)를 쓰므로 `pipelines/gold-b-reprocess` 위에서 갈라졌다. 커밋을 옮기지 않고, 최신 `main`을 병합한 재처리 브랜치를 이 브랜치에 병합했다 (2026-10-23). PR은 `pipelines/gold-b-reprocess`가 머지된 뒤에 머지한다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 정한 기본값 (설계에 없는 세부, 2026-10-21 사용자에게 알리고 진행)

1. **단위:** 끝난 UTC 하루를 받아 원장 4개(①②③④) × 24개 시간 폴더를 본다. 그 날 끝 + 10분이 안 지났으면 거부한다. `reprocess_events`는 파일이 적어서 합치지 않는다.
2. **대상:** 파일이 2개 이상인 폴더만 합친다.
3. **줄은 그대로:** 줄을 빼거나 고치지 않는다 (`loaded_at` 포함). `topic_messages`의 같은 위치 두 줄은 탐지가 보는 신뢰성 신호라서 중복도 남긴다.
4. **교체 순서:** 합친 파일을 먼저 쓰고, 줄 수를 확인한 뒤 원래 파일을 지운다. 합친 파일(`part-compact-…`)에 원래 파일 이름 목록을 적어 두어, 중간에 멈춘 뒤 다시 돌리면 남은 원래 파일을 다시 합치지 않고 지운다.
5. **동시 실행:** 재처리 잡과 같은 폴더를 동시에 건드리면 안 된다. 둘을 한 번에 하나씩 돌리는 것은 DAG가 맡는다. 적재 잡이 그 사이 새로 쓴 파일은 목록에 없어서 지워지지 않는다.

## 만드는 것

- `pipelines/gold_b/jobs/compact.py`: `run(day)` (하루 확인 → 폴더마다 남은 원래 파일 정리 → 합치기 → 줄 수 확인 → 원래 파일 지우기)
- `pipelines/gold_b/ledger.py`: 저장소에 파일 메타데이터 쓰기·읽기 (`write(..., metadata)`, `metadata(path)`)
- `pipelines/gold_b/tests/test_compact.py`: 합친 뒤 줄이 그대로인지, 안 끝난 날 거부, 중간에 멈춘 뒤 다시 돌리기
- `pipelines/gold_b/jobs/README.md`, `pipelines/gold_b/README.md`, 설계 문서 6단계 체크, `docs/BRANCHES.md` 한 줄

## 만들지 않는 것

- `dags/gold_b_compact.py` (하루 1회, 재처리와 한 번에 하나씩. 재영 님 규칙 확인 후)
- 실행 진입점(명령줄)과 배포

## 작업 순서

1. 계획 제시 (2026-10-21, 사용자가 남은 브랜치를 모두 만들어 달라고 요청)
2. 작업 지시서·브랜치 대장 커밋
3. 저장소 메타데이터, 합치기 잡, 시험, README 커밋
4. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경, 40개)
- [x] 재처리 브랜치 병합 뒤 `pipelines/gold_b/tests` 59개, `pipelines` 144개 통과 (실행 입구 시험 포함)
- [x] 재처리 브랜치(최신 `main` #78 포함)를 다시 병합한 뒤 `pipelines/gold_b/tests` 82개, `pipelines` 167개 통과 (수집기 시험 23개 포함)
- [x] 합친 뒤 폴더의 줄(`loaded_at` 포함)이 합치기 전과 같은지, 같은 위치 두 줄도 남는지
- [x] 중간에 멈춘 뒤 다시 돌려도 줄이 두 번 들어가지 않는지

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** 끝난 UTC 하루의 원장 시간 폴더마다 작은 Parquet 파일을 하나로 합치는 잡을 만들었다. 줄은 그대로 두고, 중간에 멈춰도 다시 돌리면 정리된다. DAG는 아직 없다.
- **무엇을 만들었나:**
  - `pipelines/gold_b/jobs/compact.py`: `run(day)`, `compact_folder`, `finish_previous`(앞선 실행이 남긴 원래 파일 정리)
  - `pipelines/gold_b/ledger.py`: 저장소가 Parquet 파일 메타데이터를 쓰고 읽음 (로컬·S3)
  - `pipelines/gold_b/tests/test_compact.py`(3개), `jobs/README.md` 합치기 절, `pipelines/gold_b/README.md`, 설계 문서 6단계 체크, `docs/BRANCHES.md` 한 줄
- **왜 그렇게 했나:**
  - 줄을 빼면 안 된다: `topic_messages`의 같은 위치 두 줄은 "Gold B가 같은 위치를 두 번 쌓음"을 잡는 신뢰성 신호이고, `loaded_at`은 그때 탐지가 본 숫자를 재현할 때 쓴다. 그래서 재처리 잡과 달리 같은 줄을 하나로 합치지 않는다.
  - 대신 합친 파일에 원래 파일 이름을 적어서, 원래 파일을 다 못 지우고 멈춘 경우를 다음 실행이 알아보고 지운다. 그래야 다시 돌려도 줄이 두 번 들어가지 않는다.
  - 메타데이터는 이름이 `part-compact-`인 파일에서만 읽는다. S3에서 파일마다 내려받지 않게 하려는 것이다.
  - 새 파일을 먼저 쓰고 줄 수를 확인한 뒤 지운다. 지운 뒤 멈추면 되살릴 수 없어서다.
- **확인한 결과:** Gold B 가상환경에서 `pipelines/gold_b/tests` 40개 통과 (테이블 정의 22 + 재처리 15 + 합치기 3). 합치기 전후 줄이 `loaded_at`까지 같고 같은 위치 두 줄도 남음, 파일 1개인 폴더는 그대로, 안 끝난 날은 거부하고 파일을 건드리지 않음, 원래 파일을 지우다 멈춘 뒤 다시 돌리면 줄이 두 번 들어가지 않고 그 사이 들어온 파일도 합쳐짐. `git diff --check` 통과.
- **알려진 한계·남은 일:**
  - `dags/gold_b_compact.py`(하루 1회, 재처리 잡과 한 번에 하나씩)는 재영 님 규칙을 확인한 뒤 만든다. 재처리와 동시에 돌면 같은 폴더가 꼬일 수 있어서 DAG에서 꼭 막아야 한다.
  - 지난날 폴더에 늦게 들어온 파일(늦은 결제, 백필)은 그 날을 다시 넘겨야 합쳐진다. DAG가 어제만 볼지 며칠을 볼지 정해야 한다.
  - 실제 S3에서는 돌려 보지 않았다.
- **보완 (2026-10-23): 재처리 브랜치 병합과 실행 입구**
  - 최신 `main`을 병합한 재처리 브랜치(poller 포함)를 병합했다. 충돌은 `ledger.py`(합치기의 메타데이터 쓰기와 재처리의 파일 목록 `any_name`이 같은 곳), `jobs/README.md`, `docs/BRANCHES.md`였고 양쪽을 모두 살렸다. 합치기는 원장 폴더만 다루므로 파일 목록은 지금처럼 `.parquet`만 본다.
  - 실행 입구 `python -m pipelines.gold_b.jobs.compact`를 더했다. 날짜를 주지 않으면 어제(UTC)를 합치고, 성공하면 0, 실패하면 1이다. S3 오류는 버킷 이름이 들어 있을 수 있어 종류만 로그에 남긴다.
  - `jobs/README.md`에 DAG 명세를 적었다: 하루 1번 UTC 00:30 이후, 한 번에 하나. 재처리 DAG와 같은 Airflow pool(슬롯 1개)에 넣자는 것은 제안이다.
  - 시험 2개를 더했다 (어제 기본값, 경로 없음·안 끝난 날 거부). `pipelines/gold_b/tests` 59개, `pipelines` 144개 통과.
