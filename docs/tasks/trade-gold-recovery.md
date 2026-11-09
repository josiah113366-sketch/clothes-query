# 전체 거래의 시험 데이터 분리와 Gold 공개 복구

40분 전체 거래 실행 `trade-reconcile-20261026024447`은 성공했으나 Gold 매출은 이전 1건·7,900원을 유지했다. `PREVIOUS_UNRESOLVED_SCOPE`가 전체 범위를 보류했고, 격리 35건 중 34건이 기존 오류 주입 시험과 일치했다.

## 확인한 원인

- PG_C 결제 시험: 30개 결제 키, 활성 오류 30건.
- 형식 오류 시험: 주문 1개·주문상품 1개 키, 활성 오류·의존성 보류 4건.
- 나머지 1건: 주문상품이 없는 주문. 영향 후보에는 유효한 주문 생성 시각 `2026-10-20T08:39:15.432897Z`만 있고 상품·결제는 없다.
- 시험 주문상품은 RDS에서 복구했지만 기존 Silver 계약은 주문상품 UPDATE를 지원하지 않아 해당 UPDATE와 과거 오류가 활성 오류로 남았다. 이 변경은 CDC 계약을 임의로 확대하지 않는다.
- 대시보드의 Athena 조회·배포는 정상이었다. 실행 ID가 흐름도 세부 설명에만 있어 별도 표로 노출한다.

## 사용자가 선택한 처리 기준

확인된 시험 데이터만 집계에서 분리하고, 실제 오류 범위만 보류한다. 원본·기존 Silver·오류 증거는 보존한다. 오류 분류 전체나 접두어로 제외하지 않는다.

## 복구 실행

`python -m pipelines.trade_gold_recovery --config-uri s3://<bucket>/pipelines/requests/trade-recovery/<run>/request.json`

기존 완료 Silver Parquet으로 Gold만 다시 계산한다. 새 run_id를 사용하며, 이전 Gold가 정확히 같은 Silver snapshot을 참조해야 한다. Silver manifest/completed/current 일치, SHA256, 정책 SHA256, 제외 오류 건수 34건을 검증한다.

설정 키:

| 키 | 의미 |
| --- | --- |
| job / mode | `trade` / `audited_gold_recovery` |
| run_id / output_root | 새 실행 ID와 기존 데이터 루트 |
| source_manifest / source_sha256 | 고정된 거래 Silver 완료 manifest와 해시 |
| policy_uri / policy_sha256 | 승인된 정확한 시험 키 목록과 해시 |
| previous_gold_sha256 | 복구 전 Gold current의 해시 |

정책은 `version=1`, `approval=exclude-confirmed-synthetic-tests-only`, `source_run_id`, `records`(dataset/key/evidence), `expected_excluded_active_errors`를 가진다. 운영 대상 UUID는 공유 코드에 넣지 않고 고정 요청 파일에 저장한다.

## 보류·공개 보호

- 주문상품 누락의 검증 가능한 주문·결제 시각을 모두 KST로 변환한다.
- 시간별 매출은 해당 시간대, 상품별 매출은 상품을 특정할 수 없어 해당 날짜 전체 상품을 보류한다.
- 키·시각·시간대가 불명확하거나 다른 오류 유형·범위 메타데이터 한도 초과이면 전체 보류를 유지한다.
- 보류 범위는 이전 값, 나머지 범위는 새 집계를 사용한다. 중복 집계 키를 검증한다.
- 원래 Silver의 `INCOMPLETE` 상태는 바꾸지 않는다. Gold의 `PARTIAL`과 제외 정책·오류 증거를 함께 남긴다.
- 제외 오류의 복사본은 새 Gold 실행 아래 `audit/excluded_test_errors/`에 보존한다.
- 계산 시 current를 변경하지 않는다. 정상 카탈로그 공개 후 기존 processing lease·ETag 조건부 쓰기로 Gold current를 갱신한다. 원본 오류를 삭제하거나 PASS로 덮지 않는다.

## 검증 및 범위

- 정확한 UUID 한정·잘못된 정책 거부·KST 날짜 경계·알 수 없는 범위의 전체 보류·변조된 출처/정책 공개 거부를 시험한다.
- 실제 Spark에서 날짜 전체 상품 보류가 그 날짜의 모든 상품을 보존하고 다른 날짜는 갱신하는지 S3 쓰기 전 self-check한다.
- 기존 리뷰 Gold-only 및 일반 거래 경로의 정책은 바꾸지 않는다. 이 기능은 명시적으로 실행하는 복구 도구다. 정기 전체 배치에 동일 분리 정책을 적용하려면 별도 실행 계약 연결이 필요하다.
- 기존 판정 DAG 일시정지는 유지한다. 재활성화하지 않는다.
- 자동 머지·자기 승인 없이 팀 리뷰 후 main 반영한다.

## 실제 검증 결과 (2026-10-26 KST)

- `trade-gold-recover-20261026t045917z`: Job 13:59:59 시작, 14:04:33 성공.
- 기준 Silver는 기존 `trade-reconcile-20261026024447`을 유지한다. 새 Gold가 해당 Silver를 `silver_run_id`로 명시한다.
- 시간별 집계 108행, 주문 집계 112,182건, 상품별 집계 140,807행.
- 시간별 승인금액과 상품별 금액 합계 모두 10,838,840,300원. 대시보드 실제 역할·기본 조회 코드로 확인했다.
- 보류는 10/20 KST 17시와 10/20 전체 상품 날짜 범위다. 해당 범위는 이전 결과 유지, 나머지는 새 결과다. 전체 품질 PASS로 표시하지 않는다.
- S3 `gold_a/runtime/trade/runs/<run_id>/infra-recovery-verification.json`에 검증 근거를 보존한다.
- 임시 노드 2대는 종료 후 자동 축소되어 총 3대로 복귀했다.
- 상품 조회 한도 보완 #137은 별도 팀원이 main에 머지·배포했다. 본 브랜치에 최신 main을 반영해 중복 수정하지 않았다.
- 실행 기록을 표로 보여주는 UI 보완은 본 PR main 반영 후 배포할 부분이다. 기존 흐름도 상세·매출 조회는 이미 새 실행을 읽는다.
