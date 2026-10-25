# Dashboard Gold A 조회 연결

## 목적과 범위

기존 `dashboard/approval-dashboard` 역할에 누락된 Gold A 조회 권한을 추가하고 화면의 Athena 연결 설정을 준비한다. 앱 코드·승인 쓰기·서비스계정·노드·Airflow는 변경하지 않는다.

## 변경

- dashboard-access: 기본 false인 `enable_gold_a_reads`를 추가하고 공유 배포 설정에서 true로 지정한다.
- 읽기 대상: `gold_a.gold_runs`, `order_sales_hourly_runs`, `product_sales_daily_runs`, `refresh_holds_runs`, `funnel_daily_runs`, `funnel_session_product_runs`, `review_product_daily_runs`, `review_aspect_daily_runs`.
- S3: `gold_a/runtime/<channel>/catalog/completed/` 및 각 채널의 해당 데이터셋 `runs/*/<dataset>/`만 읽는다. 제어 파일·임의 데이터셋·Silver 원본으로 확대하지 않는다.
- Deployment: Gold A Athena 모드, 기존 대시보드 전용 workgroup, gold_a DB를 지정한다. CPU 예약 조정 PR #114와는 별개다.

## 작업 결과

2026-10-25 도쿄 계정에서 Terraform fmt·validate·plan을 확인했다. 기존 리소스 변경 없이 `gold-a-metrics-read-only` 인라인 정책 1개만 생성했고 적용 후 plan 차이는 0이다. 기존 역할·Pod Identity·workgroup 및 승인 쓰기 정책은 그대로다.

실제 실행 중인 Dashboard Pod에서 Pod Identity 역할로 검증했다. Glue 테이블 8개 모두 조회 성공, 앱의 GoldAReader로 다음을 확인했다.

| 대상 | 결과 |
|---|---|
| 거래 | `trade-r6-demo30-20261024T083441Z`, 시간 지표 1행·상품 지표 1행·보류 2행 |
| 리뷰 | `reviews-v2-20261024T155307Z`, 상품별 집계 14,926행·보류 0행 |
| 리뷰 감성 | 0행. 점수 데이터의 부재이며 권한 오류는 아님 |
| 퍼널 | 완료 실행 없음, 앱 상태 `NO_RUN`. 실제 퍼널 산출물 조회는 완료 실행 생성 후 추가 검증 필요 |

IAM 시뮬레이션 10건을 확인했다. Gold A 읽기는 허용, Gold A 쓰기/삭제·제어 파일·Silver 업무 원본 읽기·Glue 파티션 생성은 거부, ground_truth 읽기는 명시적 거부다. 기존 승인 기록·Athena 결과 저장 쓰기는 유지됐다. 테스트는 조회 결과를 전용 Athena 결과 경로에 저장했으며 업무 데이터를 추가·변경하지 않았다.

Deployment는 YAML 파싱과 환경 변수·서비스계정 일치 확인, Kubernetes 서버 dry-run을 통과했다. 최신 origin/main은 작업 기준과 같으며 `git diff --check`도 통과했다.

## 남은 배포 단계

권한은 실제 AWS에 적용했다. 화면 환경 변수는 아직 live Pod에 반영하지 않았다. main 대상 PR을 팀원이 머지하면 기존 Dashboard Actions가 deploy/dashboard를 갱신하고 Argo CD가 배포한다. 이후 화면에서 실데이터 표시·보류 2건·퍼널 완료 실행 없음 상태를 확인한다. main/배포 브랜치 직접 수정·자동 승인·자동 머지는 하지 않는다.

머지 전에 기존 plan을 재사용하지 말고 최신 main 기준으로 plan을 재확인한다. 역할을 교체하거나 기존 승인 쓰기 정책을 삭제하지 않는다. 실조회에서 검증한 것은 거래·리뷰이며, 퍼널 완료 결과 및 감성 점수의 실제 데이터 생성은 별도 업무 실행에 달려 있다.
