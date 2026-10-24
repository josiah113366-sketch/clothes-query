# 대시보드 리뷰 v2 읽기

2026-10-24 요청: `clothes-query-dev-dashboard` 사용 대시보드에 `s3://clothes-query-datalake/bronze_v2/reviews/` 읽기를 추가한다.

해당 이름은 Athena workgroup이며 실행 신원은 `dashboard/approval-dashboard` ServiceAccount에 연결된 `clothes-query-dev-approval-dashboard` 역할이다. 기존 inline 정책 `dashboard-reads-and-reprocess-event-writes`의 source 읽기 목록에 해당 prefix만 추가한다.

- S3 GetObject: `bronze_v2/reviews/*`.
- S3 ListBucket: prefix가 `bronze_v2/reviews/*`에 일치하는 요청만 추가 허용한다.
- 원본 PutObject·DeleteObject, 구 리뷰 경로, 다른 Bronze prefix, Glue 테이블 권한은 추가하지 않는다.
- 기존 Athena workgroup·결과 경로, 승인 기록 쓰기, ground_truth 명시적 차단, 역할 신뢰·Pod Identity는 유지한다. Pod/이미지/노드를 재시작하거나 늘리지 않는다.

실제 Terraform 계획은 기존 정책 한 개 update뿐이었고 적용 후 재계획은 변경 없음이다. 모듈 validate·mock plan 4개, IAM 허용/차단 12개를 통과했다. 실제 Dashboard Pod Identity의 STS 역할을 대조한 뒤 v2 prefix 목록·존재 객체 HeadObject HTTP 200·한 바이트 GetObject가 성공했다. 본문은 출력하지 않았다. 원본 쓰기/삭제나 Pod 재시작은 없었다.
