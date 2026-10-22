# 파티션 프로젝션 첫 쓰기 확인

2026-10-22 PR #53의 고정 커밋 57361337fcf91f2b76dc78ac3683f9a0cd65ef7a에서 detection_runs DDL을 읽어, 표 이름과 S3 위치만 격리된 시험 대상으로 바꿨다. dt 문자열 날짜 파티션·TIMESTAMP·Parquet/SNAPPY·프로젝션 속성은 보존했다.

실제 agent/detection-job ServiceAccount Pod에서 기존 판정 workgroup으로 합성 1행 INSERT INTO 후 run_id/dt 조건 SELECT가 성공했고 한 행을 읽었다. 기존 역할만 사용했으며 별도 Glue 파티션 생성 권한을 추가하지 않았다. 따라서 이 DDL 형식은 파티션 프로젝션이라는 이유만으로 INSERT가 막히지 않는다.

시험 표는 업무 표와 다른 이름이며 S3는 gold_b/detection_runs/_infra_projection_probe/<시험 식별자>/ 전용 경로였다. 업무 이상·순찰 기록을 만들거나 실제 원장을 읽지 않았다. 시험 Pod·표·임시로 만든 빈 gold_b DB와 소유 테스트 객체/쿼리 결과 버전 7개를 정리했다. 쿼리 실행 이력과 플랫폼 감사 기록은 남는다. 추가 권한 정책은 생성하지 않았다.

이 결과는 다른 3개 표·뷰·업무 SQL·writer 재시도/중복 방지 검증을 대신하지 않는다. gold_b DB/업무 표가 준비됐다는 뜻도 아니다. dt 단독 파티션 등 최종 표 계약은 DDL 담당자가 확정하고 인프라는 그 정의를 배포한다. 비공개 실행 근거는 .cache/athena-projection-probe-summary.json에 보관한다.
