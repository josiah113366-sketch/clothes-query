# 운영 대시보드의 검증된 퍼널 부분 결과 조회

상태: 운영 반영 준비

대상: `funnels-inc-1550c14fc8898fffea6ef8a5`. checkpoint·완료 manifest·고정 inventory 및 실제 대시보드 IAM의 S3 읽기 확인. Glue의 일별·상세·보류 파티션 확인. 처리 45/1,745파일, 미처리 1,700파일, PARTIAL/BACKFILL_IN_PROGRESS. 일별 105,038행, 상세 410,319행, 보류 64행.

변경: 운영 모드에서 정식 완료 Gold가 없을 때 기존 FunnelEvidence 검증을 재사용한다. manifest SHA·완료 기록·inventory 포함관계·Athena 3개 건수가 맞는 PARTIAL 백필 결과만 허용한다. 완료 공개 실행이 있으면 우선하며, 미공개 PASS를 운영 완료로 취급하지 않는다. 검증 실패는 오류 표시하고 더미로 대체하지 않는다.

일별 부분 조회만 기존 제한 100,000행 대신 250,000행까지 허용한다. 상세 원문은 기존 소량 조회 제한을 유지한다. PARTIAL / 백필 진행 중, 실제 run_id, 처리/미처리 범위를 기존 구매 퍼널 화면에 표시한다. 거래·리뷰·Gold B 코드와 집계 규칙은 변경하지 않는다.

금지 동작 없음: Spark/DAG 실행, 클릭 재처리, Gold/current/checkpoint 수정, gold_runs 등록, Terraform 적용, S3 대량 LIST를 수행하지 않는다. 코드에서 AWS는 GetObject와 Athena SELECT만 사용한다.

검증: 기존 관련 회귀 40개 통과. 운영 모드 실제 페이지 경고·처리 범위 렌더링 추가 검증. 기존 main의 Gold B 신뢰성 검사는 별도 실제 연결이므로 미설정 테스트의 더미 플래그를 구분하도록 테스트 기대값만 맞췄다.

배포: 전용 PR CI 확인 → main 머지 → 기존 Dashboard deploy → Argo CD → 실제 Pod 코드·IAM 조회·운영 화면 확인. 로그인 없이 실제 화면 확인 완료라고 보고하지 않는다.
