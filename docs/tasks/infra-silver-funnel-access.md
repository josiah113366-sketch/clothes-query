# Silver·Gold A 퍼널 실행 권한 보완

상태: 2026-10-24 요청된 퍼널 S3·Glue·Driver RBAC 적용 완료. 업무 재실행은 담당자가 같은 고정 입력으로 진행하며 인프라에서 trigger하지 않았다.

## 확인한 실행과 범위

Airflow `silver_gold_a_funnels`의 `manual__funnels-full-20261024T070901Z`는 failed 상태였다. 실제 요청 JSON의 업무 run_id는 `funnels-full-20261024T070901Z`였다. 두 Glue 표 `gold_a.funnel_daily_runs`·`gold_a.funnel_session_product_runs`는 기존에 존재했고 Location도 퍼널 runs 경로여서 DDL을 다시 실행하지 않았다.

기존 namespace `pipelines`, 세 `silver-gold-a-*` ServiceAccount와 AWS 역할·Pod Identity·업무 이미지·자원을 유지한다. 기존 거래·R6 정책을 수정하지 않고 명시적 `enable_funnel_access` 옵션으로 IAM inline policy 3개를 추가했다.

- Driver·Executor: `bronze_v2/clickstream/` GetObject와 prefix 제한 ListBucket. S3A 폴더 확인용으로 끝 `/`를 뺀 정확한 객체의 GetObject도 허용한다.
- Driver·Executor: `silver/runtime/clicks/`, `gold_a/runtime/funnels/`의 Get/Put·멀티파트 조회/중단·목록. bucket 위치 및 bucket multipart 목록은 기존 허용을 유지한다.
- 삭제는 위 출력의 magic 작업 객체와 `funnel_rollback_run_ids`로 승인한 실행의 `part-*.parquet`만 허용한다. 퍼널이 함께 생성하는 공통 `silver/runtime/trade/runs/<동일 run_id>/`의 실패 Parquet도 같은 제한을 적용했다. 이전 정상 실행·current/manifest·Bronze·Iceberg 삭제 권한을 넓히지 않는다.
- Driver만 기존 두 Gold A 표의 Glue 조회·CreatePartition. catalog/database 상위 리소스도 포함하며 표 생성·스키마 변경·Executor Glue 권한은 추가하지 않는다.
- `pipelines/silver-gold-a-driver` Role에 pods·configmaps의 deletecollection 규칙 1개만 추가했다. services·PVC·Secret·클러스터 범위 또는 Executor의 collection 삭제는 허용하지 않았다. 재생성 도구에도 같은 규칙을 반영했다.

## 적용과 확인

최신 main 포함과 실패 실행의 활성 Spark Pod 0개를 확인한 뒤 계획을 검토했다. 최초 계획은 IAM policy 3개 create뿐이었다. 공통 Silver 중간 산출물의 실행별 정리는 후속 정책 2개 update로 보완했고, 기존 역할·trust·association·기존 정책·노드 구성은 변경하지 않았다. 각 적용 후 plan 변경 0을 확인했다. Driver Role은 기존 UID·rules·resourceVersion을 대조한 JSON patch로 갱신했다.

Spark 준비 도구 테스트 26개, 전체 Terraform 24개 root·23개 suite·106개 mock plan 검사가 통과했다. 마지막 실행별 정리 경로 보완 뒤 관련 Spark 접근 suite도 다시 확인했다. 실제 IAM 허용·차단 및 kubectl auth can-i로 Driver pods/configmaps collection 정리 허용과 Secret/PVC/Executor 거부를 확인했다. S3 데이터 쓰기·삭제나 업무 재실행은 하지 않았다.

## 새로 받은 최종 운영 명세와 구분

추가 문자에 포함된 리뷰 원문 `bronze/reviews/`, 리뷰 출력 두 루트, Iceberg 최신 점수 조회·점수 고정 쓰기, 리뷰 Gold 표 2개와 대시보드 Gold A 조회는 이번 퍼널 정책에 섞어 적용하지 않았다. 이 항목들은 이제 구체적인 경로·표 명세를 받았으므로 후속 연결이 가능하다.

기존 `clothes-query-dev-athena-review-score`는 ENABLED이고 결과 위치는 `athena-results/review-score/`다. 실제 최신 뷰와 `silver/review_aspect_scores_iceberg`의 Iceberg 원본도 존재한다. 리뷰 원문을 `bronze_v2/reviews/`로 자동 변경하지 않는다. Driver에는 읽기 전용 모델 원본과 UNLOAD 대상 쓰기가 필요하고 Executor에는 고정 점수 파일 읽기만 필요하다. 기존 MERGE용 광범위 정책을 Spark 역할에 그대로 붙이지 않는다.

대시보드 조회 코드는 미커밋·미배포 상태라는 담당자 전달이 있어 PR과 실제 쿼리 연결은 후속이다. 현재 대시보드는 승인 화면과 같은 Pod·`approval-dashboard` 역할을 사용하므로 Gold A 읽기를 기존 역할에 추가하는지, 조회 실행 환경을 따로 분리하는지 명세를 구분해야 한다. 리뷰·재처리의 고정 실행 요청 JSON과 기대 결과는 실제 업무 검증 전에 담당자가 확정한다. 업무별 실행 주기는 수동을 유지한다.
