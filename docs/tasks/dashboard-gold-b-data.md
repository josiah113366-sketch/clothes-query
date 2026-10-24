# 작업 지시서: dashboard/gold-b-data

> 상태: 진행 중 · 브랜치: `dashboard/gold-b-data` (민혁 님 `dashboard/decorator`(#107) 끝 `e3d27d3`에서 만듦. #107 다음에 머지) · 담당: 은서 (`dashboard/TODO.md` B1) · 다음 작업: 구현 (2026-10-24 사용자: "일단 대시보드 연결부터 완성해줘")

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

- [ ] `python test_gold_b_data.py` 통과 (dashboard 폴더에서)
- [ ] `python test_approval_page.py` 통과 (기존 시험)
- [ ] 실제 Athena에서 세 SQL이 돈다
- [ ] `git diff --check`

## 작업 결과 (머지 전에 작성한다)
