# R6 실행 결과 공개

상태: 코드 구현·로컬 검증 완료 · PR 제출 준비

## 승인 범위

- 기존 금액 검사 결과를 밀리초 TIMESTAMP와 정확한 UTC 문자열로 공개한다.
- silver.silver_runs / silver.order_amount_checks와 수동 DAG를 연결한다.
- 저장·파티션 등록 후 완료 목록 공개, 직렬화·중복 방지·실패 재개를 검증한다.
- 공통 시간 규약·결제 UPDATE는 이번에 변경하지 않는다.
- 결제 UPDATE, 원본 복구·재처리 DAG, DAG 4개 분리, 리뷰·전체 Gold A 공개는 전체 목표에 남긴다.

## 작업 결과

- 기존 PR #87의 미커밋 v2 문서 수정은 stash `runtime-followup bronze-v2 docs before r6 publication`에 보존했다. 새 브랜치는 최신 main 기반 pipelines/r6-publication이다.
- Glue 정의와 권한은 배포 전에 확인한다. 주현 담당의 실행 순차 소비·탐지 상태 코드는 수정하지 않는다.
- `pipelines/r6_publication.py`: 금액 검사 공개 투영, 고정 manifest 검증, Glue 파티션 불변 등록, 조건부 S3 직렬화·중복 방지·실패 재개 및 완료 목록을 구현했다. 강제 종료 소유권 복구는 이전 프로세스 종료를 확인한 운영자만 명시적으로 수행한다.
- `pipelines/silver/`의 DDL 두 개와 기존 README에 공개 타입·위치·조회·권한을 정리했다. 새 계약 문서는 만들지 않았다.
- 기존 수동 DAG에 공개 태스크와 실패 watcher를 연결했다. 기존 PR #87에서 검증했던 인프라 자원 정렬도 동일하게 적용했다. DAG 4개 분리는 구현한 것으로 표시하지 않는다.
- 실제 Parquet 기반 정밀도·금액·MISMATCH/대기/빈 실행·순서·재시도·강제 종료 복구와 가짜 Glue/S3 검증을 수행한다. 운영 Python 3.10/PyArrow 25와 로컬 Python 3.12에서 실행하며 Airflow 이미지에서 DAG 파싱·Pod 렌더링·실패 watcher를 확인한다.
- 이번 작업에서는 공통 시간 파서·YAML·지문·Gold B·탐지 코드를 수정하지 않았다. 구현 결과 검수 후 기능/DDL·DAG·운영 명세를 구분해 커밋하고 PR로 제출한다. 실제 Glue/Athena 배포·새 ECR 발행·운영 Trigger는 후속이다.
- 검증 완료: Python 3.12 공개/공통 규칙/시각/거래 회귀 70개, 운영 Python 3.10·PyArrow 25 공개 시험 16개, 실제 Airflow 이미지의 DAG 파싱·Pod 렌더링·실패 watcher 2개 통과. Ruff(py310)·git diff --check 통과. Windows 기본 임시 폴더 권한으로 회귀 13개가 초기 설정 오류였으며 작업 폴더의 basetemp를 지정한 재실행에서 모두 통과했다.
- 현재 AWS에는 silver DB가 없는 것을 읽기 전용 확인했다. 실제 Athena 조회 성공으로 표시하지 않으며 DDL/권한 연결과 새 이미지 배포 후 운영 검증이 남아 있다.
