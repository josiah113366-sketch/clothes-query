# Silver·Gold A 접근 재확인과 리뷰 권한 보완

상태: 2026-10-24 퍼널 정확한 객체 접근 확인, 리뷰 권한 적용 및 실제 최신 점수 읽기 성공. 업무 DAG 재실행·전체 리뷰 가공은 미실행.

## 퍼널 접근 오류의 현재 상태

사용자가 다시 전달한 실행은 `silver_gold_a_funnels`의 `manual__funnels-full-20261024T070901Z`였다. Airflow에는 기존 failed 상태가 남아 있었고 새 퍼널/리뷰 실행은 없었다. 현재 역할에 퍼널 정책은 존재하고 리뷰 정책은 없음을 AWS에서 확인했다.

오류 대상으로 전달받은 고정 클릭 객체에 현재 Driver·Executor 각각의 실제 Pod Identity로 HeadObject를 실행했다. 두 역할 모두 HTTP 200이고 객체 크기도 동일했다. IAM 시뮬레이션도 둘 다 allowed였다. 대시보드에서 이미 사용하는 Python 이미지를 기존 노드의 작은 임시 Pod에 재사용했으며 Spark나 새 노드를 만들지 않았다. 확인 Pod 2개는 UID 대조 후 삭제했고 원본은 변경하지 않았다. 따라서 그 객체의 기존 403은 현재 권한에서 재현되지 않는다. 과거 failed 실행 상태가 자동으로 success로 바뀌지는 않는다.

Driver의 namespace pods/configmaps deletecollection은 앞선 [퍼널 보완](infra-silver-funnel-access.md)에서 적용·확인했다. 기존 이미지·세 실행 계정·AWS 역할·trust·Pod Identity는 유지한다.

## 리뷰 권한 적용

미적용이던 리뷰 항목을 `enable_review_access` opt-in으로 연결했다. 역할의 기존 inline policy 총량은 Driver 7,955 bytes여서 더 큰 inline 정책을 계속 붙이지 않고 별도 관리형 정책 2개를 사용한다. 계획은 새 정책 2개와 기존 역할 attachment 3개 create뿐이었고 기존 자원 update/delete는 없었다. 적용 후 spark-access plan 변경 0을 확인했다.

| 역할 | 추가 범위 |
|---|---|
| Driver·Executor | `bronze_v2/reviews/` 및 전환 기간의 `bronze/reviews/` 읽기·목록, 리뷰 Silver/Gold 출력 읽기·쓰기·멀티파트·목록·magic 임시 파일 정리, 고정 점수 파일 읽기 |
| Driver만 | 기존 리뷰 Athena workgroup 실행·상태·결과·취소, 최신 뷰와 기반 표의 Glue 조회, 점수 Iceberg 데이터·메타데이터 읽기, Athena 결과·고정 점수 prefix 읽기/쓰기, 리뷰 Gold 표 2개 조회·파티션 등록 |

확정 경로와 workgroup은 다음과 같다.

- 운영 원문: 최신 계약에 따라 `bronze_v2/reviews/`로 전환한다. v2는 기존 데이터에 컬럼을 추가한 완전 상위호환 저장소다. 전환 검증 동안 `bronze/reviews/` 읽기도 유지한다. 아래 초기 읽기 검증은 구 경로 기준이며 v2 실제 DAG 성공을 뜻하지 않는다.
- 출력: `silver/runtime/reviews/`, `gold_a/runtime/reviews/`. control/current/completed를 포함하되 기존 정상 결과 삭제를 허용하지 않는다.
- 최신 뷰: `clothes_query_dev_review_score.review_aspect_scores_latest`, 기반 표 `review_aspect_scores`.
- Iceberg 읽기: `silver/review_aspect_scores_iceberg/`. Put/Delete·Glue 스키마 변경은 허용하지 않는다.
- workgroup: `clothes-query-dev-athena-review-score`, 결과: `athena-results/review-score/`.
- 실행별 고정 점수: `pipelines/input-manifests/review-scores/<run_id>/`. Driver가 조회 결과를 고정하고 Executor가 읽는다.
- Driver 공개 표: `gold_a.review_product_daily_runs`, `gold_a.review_aspect_daily_runs`. 기존 gold_runs·refresh_holds 및 Silver/R6 권한은 유지한다.

`review_rollback_run_ids`는 현재 빈 집합이다. 리뷰 고정 요청의 업무 run_id를 받아 승인한 뒤 그 실행의 최종 part-*.parquet 실패 정리를 추가할 수 있다. 현재 magic 작업 객체 정리는 가능하며 이전 정상 결과·Bronze·Iceberg·고정 점수 원본 삭제는 허용하지 않는다.

## 실제 검증

- 기존 거래·퍼널 및 새 리뷰 경계를 포함한 Terraform 24개 root·23개 mock suite, 108개 plan 검사 통과.
- IAM 허용/차단 72개 확인. Executor Athena·Iceberg 원본 접근과 두 역할의 Iceberg 쓰기/삭제·정답표 접근, 임의의 정상 리뷰 결과 삭제는 거부됐다.
- 판정 역할의 R6 완료/검사 데이터와 재처리 이벤트 읽기 유지, 조사 역할의 Silver 직접 읽기 거부를 함께 확인했다.
- 실제 Driver 신원의 작은 Pod에서 최신 점수 뷰 SELECT·결과 읽기, 기존 리뷰 Gold 표 2개 Glue 조회 성공.
- 같은 신원으로 운영 리뷰 원문·Iceberg의 목록·존재 객체 일부 읽기 성공. 비어 있는 리뷰 출력·점수 고정 prefix는 목록 허용만 확인했고 실제 쓰기 성공으로 표시하지 않았다.
- 확인 Pod는 삭제했다. 원본·승인·업무 출력 쓰기/삭제, Athena UNLOAD 점수 고정, Spark 실행·DAG trigger는 하지 않았다. SELECT 결과만 기존 Athena 결과 경로에 저장했다.

## 담당자에게 전달할 실행 조건

기존 이미지 digest와 계정을 유지한다. 리뷰 요청 JSON의 `analysis_view.workgroup`에는 위 기존 workgroup을 사용한다. 고정 실행 요청·날짜·업무 run_id·기대 결과를 확정한 뒤 실제 리뷰 가공/UNLOAD·공개를 검증한다. 실패 Parquet 정리 범위에는 그 업무 run_id가 필요하다. 퍼널은 전달된 클릭 객체 접근이 통과했으므로 기존 고정 입력으로 담당자가 재실행할 수 있다. 새 업무 run_id를 쓰면 실행별 정리 허용 목록도 맞춰야 한다.

대시보드에는 별도로 요청된 상태 표 6개의 읽기를 적용했고 실제 조회가 통과했다. 모든 Gold A 지표 표·원본을 읽도록 확장한 것은 아니다. 화면 코드·쿼리의 추가 의존성과 전체 운영 성공 기준은 권한 적용과 구분한다.
