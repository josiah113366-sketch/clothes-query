# Gold B 조회 뷰 배포

상태: 배포·실제 판정 ServiceAccount 조회 검증 완료 (2026-10-23)

18:05 판정 작업 두 시도가 gold_b.payment_attempts TABLE_NOT_FOUND로 exit=1 종료했다. Glue의 원장·판정 객체 8개는 존재했으나 조회 뷰 3개는 없었다. main 044dae2의 pipelines/gold_b/views SQL과 설계 문서 일치 검사 5개를 통과한 뒤 payment_conflicts → payment_attempts → malformed_messages 순서로 Athena에 생성했다.

기존 객체가 없는지 확인했고 CREATE OR REPLACE를 CREATE VIEW로 실행해 동시에 팀원이 만든 뷰를 덮어쓰지 않도록 했다. 원장·업무 행은 변경하지 않았다. Glue VIRTUAL_VIEW 3개와 Athena DDL 성공을 확인했다.

실제 agent/detection-job ServiceAccount로 읽기 전용 검증 Pod를 만들었다. STS 신원을 검증하고 판정용 workgroup에서 SELECT * LIMIT 0으로 뷰 3개와 source 메타데이터 조회 권한을 확인했다. 각 뷰 컬럼은 9/9/10개였다. 만든 검증 Pod는 UID와 소유 라벨 대조 후 삭제했다. 업무 더미 이벤트나 원장 행은 만들지 않았고, 실제 조회 이력·결과는 운영 검증 기록으로 유지한다.

업무 규칙 정확성이나 새 판정 실행 성공은 이 스키마/권한 검증과 별개다. 다음 정기 실행의 결과와 Airflow S3 로그 쓰기를 이어 확인한다.

후속 자연 예약 실행 19:55/20:00/20:05 KST의 agent_detection_5min 상태가 모두 success임을 확인했다. 추가 수동 실행을 만들거나 업무 코드를 바꾸지 않았다. 새 scheduler가 20:05:39 KST에 작업 로그를 S3에 업로드한 것까지 확인해 실제 로그 쓰기 경로도 검증했다. 이 성공은 배포·연결 성공이며 Gold B 상시 적재 원장의 데이터 정확성 검증을 대체하지 않는다.
