# 리뷰 Bronze v2 전환

2026-10-24. 사용자가 v2는 기존 데이터에 컬럼을 추가한 완전 상위호환 저장소라고 확정하고 리뷰 입력 전환을 승인했다.

## 변경 범위

- 새 리뷰 입력은 `s3://clothes-query-datalake/bronze_v2/reviews/`를 사용한다.
- 기존 `review-data` 관리형 정책 한 개에 해당 prefix의 GetObject·ListBucket만 추가한다. 정책은 기존 Driver·Executor 역할에 이미 연결돼 있다.
- 전환 검증 동안 `bronze/reviews/` 읽기를 유지한다. Bronze 쓰기·삭제, 다른 v2 prefix, 정답표 접근은 추가하지 않는다.
- 리뷰 출력·Iceberg 모델 원본·Athena workgroup/결과·Pod Identity·이미지·노드 설정은 유지한다.
- 실제 고정 요청 JSON은 불변 실행 계약이므로 기존 요청을 덮어쓰지 않는다. 리뷰 담당자는 새 고정 요청에 v2 파일 목록을 넣어 전달한다.

## 배포 경계

`infra/bronze-v2-apply`의 시뮬레이터 생성 경로 변경은 별도 브랜치 작업이다. 이번 PR은 그 브랜치 전체를 병합하거나 시뮬레이터를 재배포하지 않는다. 파일 접근 성공만으로 새 생성기의 운영 배포나 전체 리뷰 DAG 성공을 주장하지 않는다.

## 검증

- Terraform 모듈 validate 및 mock plan 10개 통과.
- 실제 plan은 기존 정책 한 개의 in-place 변경뿐이다. 역할·attachment 신규 생성, 자원 삭제·교체, 노드 생성은 없다.
- 적용 후 재계획은 변경 없음이다. 두 역할의 v2/구 리뷰 읽기 허용, 원본 쓰기·삭제 및 무관한 경로 거부를 포함해 IAM 검사 24개가 통과했다.
- 실제 Driver·Executor Pod Identity로 v2 리뷰 prefix 목록, 존재 객체 HeadObject HTTP 200, 한 바이트 GetObject가 모두 성공했다. 본문은 출력하지 않았다.
- 두 검증 Pod는 삭제했다. Spark·업무 DAG는 실행하지 않았으며 원본 데이터·실행 요청을 수정하지 않았다.

## 후속

생성기의 새 파일 도착, 새 v2 고정 입력 요청과 기대 결과, 실제 리뷰 DAG 저장·공개까지 확인한 뒤 구 경로 읽기 권한을 제거한다. 기존 파일의 자동 이동이나 삭제는 수행하지 않는다.
