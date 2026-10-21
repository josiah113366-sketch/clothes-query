# 작업 지시서: pipelines/gold-b-compact

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-compact` (`pipelines/gold-b-reprocess` 위에서 갈라짐) · 다음 작업: DAG (재영 님 규칙 확인 후)

## 목표

원장 시간 폴더 안의 작은 Parquet 파일을 하루 1회 하나로 합치는 **파일 합치기 잡**(6단계)을 만든다. 적재 잡과 수집기가 1분마다 파일을 만들어서, 합치지 않으면 한 시간 폴더에 60개 넘게 쌓이고 Athena 조회가 느려진다. Airflow DAG는 만들지 않는다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「저장」, 「처리 규칙」의 중복 제거(유입량은 중복을 지우지 않음), 6단계 체크리스트
- `pipelines/gold_b/ledger.py` (저장소), `pipelines/gold_b/jobs/reprocess.py` (같은 폴더를 바꾸는 다른 잡)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 원장 공통 도구(`ledger.py`)를 쓰므로 `pipelines/gold-b-reprocess` 위에서 갈라졌다. push는 #36과 재처리 브랜치가 머지된 뒤, 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
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

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경)
- [ ] 합친 뒤 폴더의 줄(`loaded_at` 포함)이 합치기 전과 같은지, 같은 위치 두 줄도 남는지
- [ ] 중간에 멈춘 뒤 다시 돌려도 줄이 두 번 들어가지 않는지

## 작업 결과 (머지 전에 작성한다)
