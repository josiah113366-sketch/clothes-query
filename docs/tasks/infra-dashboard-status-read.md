# 대시보드 파이프라인 상태 읽기

상태: 2026-10-24 요청된 읽기 정책 실제 적용 완료. 화면 구현·배포는 담당자 범위다.

## 요청과 실제 위치

사용자는 기존 대시보드 권한에 Glue DB silver·gold_a와 다음 표의 읽기, 지정한 S3 prefix의 GetObject·ListBucket을 요청했다.

| Glue 표 | S3 읽기 경로 |
|---|---|
| gold_b.bronze_lag_snapshots | gold_b/bronze_lag_snapshots/ |
| gold_b.topic_messages | gold_b/topic_messages/ |
| gold_b.payment_events | gold_b/payment_events/ |
| gold_b.malformed_events | gold_b/malformed_events/ |
| silver.silver_runs | silver/runtime/trade/catalog/completed/ |
| gold_a.gold_runs | gold_a/catalog/ 및 실제 channel 파티션 완료 목록 |

실제 Glue에서 표 6개가 존재함을 확인했다. `gold_a.gold_runs`의 논리 Location은 `gold_a/catalog`지만 현재 trade 파티션은 `gold_a/runtime/trade/catalog/completed/`를 가리킨다. Gold 공개 코드도 trade·funnels·reviews별 같은 구조를 사용한다. 따라서 해당 세 채널의 `catalog/completed/`만 추가했다. 표 조회 권한을 요청한 범위에 해당하며 채널의 전체 runtime이나 지표 결과를 읽도록 넓히지는 않았다. 버킷은 기존 `clothes-query-datalake`다.

## 적용

`enable_pipeline_status_reads`를 기본 false의 opt-in으로 추가하고 공유 dashboard-access 설정에서 활성화했다. 기존 `dashboard/approval-dashboard`의 `clothes-query-dev-approval-dashboard` 역할에 `pipeline-status-read-only` inline policy 하나를 추가한다.

정책은 지정한 표 6개와 catalog·관련 database의 Glue GetDatabase/GetTable/GetPartitions/GetPartition/BatchGetPartition, 지정 원본·완료 목록 9개 prefix의 GetObject와 prefix 제한 ListBucket만 포함한다. 새로운 S3 쓰기·삭제, Glue 파티션 등록·DDL, 정답표·Iceberg 접근을 추가하지 않는다. 기존 승인 기록·전용 Athena 결과 쓰기와 ground_truth 명시 거부는 보존한다.

최신 main 포함을 확인했고 plan은 새 inline policy 1개 create뿐이었다. 기존 역할·정책·trust·Pod Identity·workgroup·Secret·Pod·노드 변경은 없었다. 저장한 계획을 적용한 뒤 전체 dashboard-access 후속 plan 변경 0을 확인했다. 재배포·Pod 재시작은 하지 않았다. 사용 workgroup은 계속 `clothes-query-dev-dashboard`, Athena 결과 위치는 `athena-results/dashboard/`다.

## 검증과 한계

실제 역할의 새 GetObject 허용과 원본 Put/Delete·Glue CreatePartition/UpdateTable 거부, 기존 승인 기록·결과 저장 쓰기 보존을 IAM 시뮬레이션 53개로 확인했다. 실제 대시보드 Pod의 동일 역할로 표 6개 Athena 조회·결과 읽기가 모두 성공했다. S3 prefix 9개의 목록 조회와 객체가 존재하는 5개 prefix의 일부 바이트 읽기도 성공했다. 나머지 prefix는 비어 있어 객체 읽기 성공으로 표시하지 않았다. 원본·승인 데이터를 추가하거나 수정하지 않았으며 Athena 조회 결과만 기존 전용 경로에 저장했다.

Terraform fmt·24개 root validate와 23개 mock suite의 107개 plan 검사가 최종 통과했다. opt-in 기본 비활성화와 추가 정책의 읽기 작업·표 ARN·실제 완료 목록 범위를 확인했다.

기존 소스 읽기 권한과 함께 동작하는 추가 정책이며, 대시보드에 모든 Silver/Gold 지표 조회 권한이 생긴 것은 아니다. 새 화면의 실제 쿼리가 이 표 외의 테이블·뷰를 읽으면 해당 의존성을 별도로 확인해야 한다.
