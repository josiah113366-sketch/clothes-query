# Gold B DB와 원장 표 등록

상태: 완료 (실제 적용·정의 검증, PR·머지 없음)

## 요청과 범위

2026-10-22 사용자 요청으로 pipelines/gold_b/ddl의 database.sql은 실행하지 않고, Terraform으로 gold_b DB를 먼저 준비한 뒤 나머지 5개 테이블을 Athena에 등록한다. 기존 agent DB와 별개다. 업무 DDL은 수정하지 않으며 데이터 INSERT·업무 표 #53·뷰 생성·권한 변경·PR 머지는 포함하지 않는다.

## 완료 확인

- 실제 plan이 기존 자원 변경 없이 Glue DB 생성 1개인지 확인한다.
- DB location과 DDL의 S3 bucket/prefix가 일치하는지 확인한다.
- 적용 후 5개 테이블 컬럼·자료형·파티션·프로젝션 속성을 원문과 대조한다.
- 이미 같은 이름 표가 있으면 구조를 먼저 비교하고 ALTER/DROP하지 않는다.
- DB 사후 plan 변경 없음과 데이터 미입력을 기록한다. 기존 작업 브랜치와 분리해 보존하며 자동 머지하지 않는다.

## 작업 결과

최신 main 9db1dd2에서 별도 브랜치를 만들고 독립 gold-b-catalog 스택을 추가했다. 기존 storage state의 버킷을 읽어 gold_b/ location을 지정했으며 접근 권한 스택·agent DB·데이터 버킷과 state key를 분리했다. prevent_destroy를 설정했다. 실제 plan은 Glue DB 생성1·수정0·삭제0이었고 해당 저장 계획만 적용했다.

database.sql을 제외한 현재 main의 원본 DDL 5개를 Athena에서 실행해 다음 표를 등록했다. SQL 파일 내용은 수정하지 않았다.

| 표 | 데이터 컬럼 수 | 파티션 |
|---|---:|---|
| payment_events | 12 | dt, hour |
| topic_messages | 5 | dt, hour |
| bronze_lag_snapshots | 8 | dt, hour |
| malformed_events | 9 | dt, hour |
| reprocess_events | 12 | 없음 |

등록 후 Glue 메타데이터의 컬럼 이름·자료형·Parquet input format/SerDe·파티션·프로젝션 속성과 S3 위치를 원본과 대조했다. Athena는 표 Location 끝 슬래시를 제거해 저장하므로 디렉터리 URI의 끝 슬래시를 정규화해 비교했고, storage.location.template은 원문 그대로 일치함을 확인했다. 최초 payment_events 등록 뒤 이 표기 차이에서 멈췄으며, DB를 다시 적용하거나 표를 변경하지 않고 이미 등록된 첫 표를 비교한 뒤 나머지 4개를 이어 등록했다.

Terraform fmt/validate와 인증 없는 격리 catalog/access mock plan 15건을 통과했다. 실제 사후 DB plan은 변경 없음이다. 업무 데이터 INSERT·샘플 입력·S3 원본 수정·ALTER/DROP·크롤러·권한 추가·#53의 판정/조사 표/뷰 생성은 하지 않았다. Athena DDL 실행 이력과 조회 결과 파일은 운영 기록이다. 실행 근거와 소스 파일 hash는 Git 제외 .cache/gold-b-catalog-plan-summary.json 및 .cache/gold-b-catalog-apply-summary.json에 보관했다.

코드·기록은 infra/gold-b-catalog 브랜치에 보존하며 push·PR·승인·머지는 하지 않았다. 기존 infra/agent-runtime-connections 작업도 별도 브랜치에 그대로 남아 있다.
