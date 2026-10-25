# 작업 지시서: dashboard/gold-b-data

> 상태: 완료 (#110, 2026-10-24 머지) · 브랜치: `dashboard/gold-b-data` (민혁 님 `dashboard/decorator`(#107) 끝 `e3d27d3`에서 만들고, #107 머지 뒤 최신 `main` 병합) · 담당: 은서 (`dashboard/TODO.md` B1) · 다음 작업: 리뷰·머지 (사용자), 뷰 읽기 권한 (재영 님), 배포 (민혁 님) (2026-10-24 사용자: "일단 대시보드 연결부터 완성해줘")

## 목표

대시보드 데이터 관리의 Gold B 화면 중 아직 더미인 **결제 관제, 형식 오류, 재처리 이력**을 Athena의 Gold B 원장·뷰에 연결한다 (`dashboard/TODO.md` B1). 파이프라인 상태(③ Bronze 지연)는 #107이 이미 연결했다. 조회가 안 되거나 결과가 비면 지금처럼 더미로 대체한다 (`DATA_SOURCE=auto`).

## 먼저 읽을 것

- `dashboard/README.md`, `dashboard/TODO.md` (B1, F3), `dashboard/data.py` (`_REAL`, `dataset`, #107의 `_athena`·`_utc`·`_hour_partitions`·`_real_bronze_lag`)
- `pipelines/gold_b/ddl/`, `pipelines/gold_b/views/` (칸 이름, 시간 폴더 `dt`·`hour`)

## 정한 기본값 (설계에 없는 세부, 2026-10-24 사용자 "완성해줘")

1. **연결:** #107의 Athena 연결을 그대로 쓴다 (`_athena`, workgroup은 `DASHBOARD_ATHENA_WORKGROUP`, 없으면 `APPROVAL_ATHENA_WORKGROUP`). 지연과 같은 조건(workgroup이 있을 때)에서 `_REAL`에 등록한다.
2. **함수 3개와 읽는 범위:**
   - `get_payment_attempts(시간)`: `payment_attempts` 뷰의 최근 N시간(`completed_at`). 뷰가 원장 전체를 읽어서 시간 폴더 조건은 쓸 수 없다.
   - `get_malformed_events()`: ④ 최근 6시간. 시간 폴더 조건(#107의 `_hour_partitions`)을 같이 준다.
   - `get_reprocess_events()`: ⑤ 최근 7일 (`at`, 따옴표로 감쌈).
3. **칸·형식:** 더미 함수와 같은 칸. 시각은 UTC 시각, 숫자 칸은 숫자로 바꾼다 (`_athena`는 모두 글자로 준다).
4. **화면:**
   - 결제 관제: `payment_attempts`에는 `copies`가 없다 (#95 뒤 뷰가 Kafka 위치 순서로 마지막 이벤트를 고름). 목록·설명·더미에서 뺀다.
   - 결제 관제·형식 오류·재처리 이력의 "※ 현재는 더미 데이터입니다"는 그 화면 데이터가 더미일 때만 보인다.
   - 재처리 이력 설명을 메시지 단위 재처리(#99)에 맞춘다 (시간 폴더 전체가 아니라 그 시간대에 들어온 메시지의 옛 결과만 바뀜).
5. **권한:** 형식 오류(④)와 재처리 기록(⑤)은 지금 대시보드 역할로 읽을 수 있다. 결제 관제는 뷰 `payment_states`, `payment_attempts`의 Glue 읽기가 더 필요하다 (`pipeline-status-read-only` 정책에 없음, 재영 님께 요청). 없으면 결제 관제는 더미로 남는다.
6. **시험:** `dashboard/test_gold_b_data.py` (기존 시험과 같은 `check` 방식). 가짜 조회 함수로 SQL·칸·형식을 보고, 세 화면을 더미와 실제 모양 데이터로 연다.
7. **실제 Athena 확인:** 은서 님 AWS 자격으로 대시보드 workgroup에서 세 SQL을 SELECT로만 돌려 문법과 칸을 확인한다.

## 만들지 않는 것

- 파이프라인 상태(지연)·데이터 흐름 탭 (#107)
- 대시보드 역할 권한, 이미지 배포 (재영 님·민혁 님)
- B3 신뢰성 점검, B4 지연 경고 기준, B5 규칙 버전 고르기, 보류 결제 화면

## 이전 시도

최신 `main`에서 만든 첫 버전(로컬 브랜치 `dashboard/gold-b-data-v1`, push 안 함)은 #107과 같은 파일(`data.py`, 화면, README, TODO)을 고쳐 충돌하고 지연 연결이 겹쳐서 쓰지 않는다. #107 위에서 남은 세 화면만 다시 만든다.

## 작업 순서

1. 이 지시서, 브랜치 대장, TODO B1 담당
2. 조회 함수 3개와 등록
3. 화면 고치기와 시험
4. 실제 Athena에서 SQL 확인
5. README·TODO와 작업 결과

## 완료 확인

- [x] `python test_gold_b_data.py` 통과 (dashboard 폴더에서, 30개)
- [x] `python test_approval_page.py` 통과 (기존 시험, 28개)
- [x] 실제 Athena에서 세 SQL이 돈다
- [x] `git diff --check`

## 작업 결과 (머지 전에 작성한다)

### 만든 것

- `dashboard/data.py`: #107의 `_athena`·`_utc`·`_hour_partitions`를 그대로 써서 조회 함수 3개를 만들고, 지연과 같은 조건(workgroup 있음)에서 `_REAL`에 등록했다.
  - `get_payment_attempts(시간)`: `gold_b.payment_attempts` 뷰의 최근 N시간(`completed_at`)
  - `get_malformed_events()`: `gold_b.malformed_events` 최근 6시간(`MALFORMED_HOURS`), 시간 폴더 조건
  - `get_reprocess_events()`: `gold_b.reprocess_events` 최근 7일(`REPROCESS_DAYS`), `at`은 따옴표로
  - Athena 결과(모두 글자)를 시각은 UTC 시각, 위치·시도 번호는 숫자로 바꾸고 칸은 더미와 같게 돌려준다. 시험할 수 있게 `query`, `now`를 받는다.
  - 결제 시도 더미에서 `copies`를 뺐다 (뷰와 같은 칸).
- 화면: 결제 관제 목록·설명에서 `copies`를 뺐다. 세 화면의 "※ 현재는 더미 데이터입니다"는 더미일 때만 나오고, 실데이터면 읽은 범위를 적는다. 재처리 이력 설명을 메시지 단위 재처리(#99)에 맞췄다.
- `dashboard/test_gold_b_data.py` (30개): 가짜 `_athena`(값이 모두 글자인 표)로 SQL(표, 시간 폴더, 자정 넘김, 따옴표)·칸·형식·빈 결과, workgroup이 있을 때 등록, 조회 실패 시 더미 대체를 보고, 세 화면을 더미·실데이터 모양·실패 없는 결제로 연다 (`AppTest`). `streamlit_echarts`가 없는 PC에서는 그리기만 빈 함수로 대신한다.
- 문서: `dashboard/README.md` 배포 6번, `dashboard/TODO.md` B1 담당·F3 메모.

### 왜

- 지연(③)은 #107이 이미 연결했고, 같은 파일을 고치는 다른 브랜치를 따로 올리면 충돌한다. 그래서 #107 위에서 남은 세 화면만 더했다.
- `copies`는 #95 뒤 뷰에 없는 칸이라, 실데이터가 들어오면 결제 화면 목록이 멈춘다.

### 확인한 결과

- `python test_gold_b_data.py` 30개, `python test_approval_page.py` 28개 통과 (로컬 Python 3.12, streamlit 1.59.2).
- 코드를 일부러 틀리게 바꾼 8가지(결제 목록 `copies`, 시각 변환 두 곳 빠짐, `at` 따옴표 빠짐, 시간 폴더 조건 빠짐, 재처리 등록 빠짐, 더미 안내 항상/안 보임)를 시험이 모두 잡았다.
- 실제 Athena (은서 님 AWS 자격, 대시보드 workgroup, SELECT만): `payment_attempts` 뷰 474줄(10-20~21 시험 적재분, 성공 430·실패 44, 실패 원인 고객 39·PG 5), `malformed_events` 0줄, `reprocess_events` 0줄, 지연 150줄. 세 SQL 모두 문법·칸·형식이 맞다.
- #107 머지(`23e7009`, 한 커밋으로 합침) 뒤 최신 `main` 병합 (2026-10-24): 이 브랜치가 바꾸지 않은 파일은 `main` 그대로, 바꾼 9개 파일은 `main` 위에 이 브랜치 변경을 얹었다. 병합한 트리에서 `python test_gold_b_data.py` 30개, `python test_approval_page.py` 28개, `python -m pytest -q test_gold_a_io.py` 19개(#106 시험)가 통과했다. 이 PC에는 `streamlit_echarts`가 없어서 Gold A 시험은 저장소 밖 가짜 모듈을 `PYTHONPATH`에 두고 돌렸다.
- 대시보드 역할 권한 (IAM 시뮬레이션): 원장 `payment_events`·`malformed_events`·`reprocess_events`와 그 S3 폴더는 허용, 뷰 `payment_attempts`·`payment_states`는 거부.

### 알아 둘 것

- 팀 규칙상 결과가 비면 더미로 대체한다. 그래서 형식 오류(평소 0건)와 재처리 이력(요청이 없을 때)은 실데이터가 연결돼도 평소에 더미가 보일 수 있다 (화면 아래에 더미라고 적힘). 빈 결과를 그대로 보여 줄지는 민혁 님과 정할 일이다.
- 결제 관제는 최근 6시간만 읽어서, 적재 잡이 상시로 돌기 전에는 비어 있어 더미가 보인다.

### 다음 할 일

- 재영 님: 대시보드 역할에 뷰 `gold_b.payment_states`·`gold_b.payment_attempts`의 `glue:GetTable` 추가 (`pipeline-status-read-only` 정책).
- 사용자: PR #110 리뷰·머지 (#107 머지 뒤 최신 `main` 병합은 끝냄).
- 민혁 님: 머지 뒤 대시보드 이미지 재배포.
