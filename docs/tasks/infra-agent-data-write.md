# 조사 저장소 분리·판정 쓰기 권한

상태: 완료 (실제 적용·PR #50 검토 대기, 업무 테이블 연동 후속)

## 요청과 범위

후속 답변으로 조사 리포트·실행 기록을 Glue DB `agent`, S3 `agent/<표>/`로 분리한다. 판정 역할은 `gold_b/anomaly/`, `gold_b/detection_runs/`, `gold_b/reprocess_events/`에만 데이터 쓰기를 허용한다. 기존 쿼리 결과 쓰기 경로·Gold B 읽기·ground_truth 명시 거부를 유지한다. 테이블 DDL·파티션·조사 표 이름·업무 SQL은 담당자 입력 대기다.

최신 main에서 시작해 이미 적용된 `infra/gold-b-access-prep`를 반영했다. team-access와 Gold B 문서 항목 충돌은 양쪽 모두 보존했다. 기존 Gold B state를 그대로 사용하며 다른 state에 역할을 중복 정의하지 않는다.

## 완료 확인

- fmt/validate·Gold B mock 검사와 계획에서 Glue DB 1개 추가·기존 inline policy 2개 수정만 허용한다.
- role/workgroup/Pod Identity는 교체하지 않는다. 기존 인프라·업무 데이터는 변경하지 않는다.
- IAM simulation으로 조사 agent 쓰기 허용/Gold B 쓰기 거부, 판정 세 경로 허용/다른 Gold B·agent 쓰기 거부, ground_truth 명시 거부를 확인한다.
- 실제 업무 Athena INSERT는 테이블 DDL이 확정된 뒤 검증한다. S3 작은 합성 데이터도 이번에는 쓰지 않는다.

## 작업 결과

2026-10-21 fmt/validate와 Gold B mock 13건을 통과했다. 기존 역할/association/workgroup을 보존하고 Glue DB agent 1개 추가·inline policy 2개 변경만 있는 저장 계획을 적용했다. 실제 bucket LOCATION과 DB 생성을 확인했고 후속 plan은 변경 없음이다. 비공개 입력에 조사 DB 활성화·agent/ 쓰기·판정 세 경로 쓰기를 지속 저장했다.

IAM simulation 32건에서 조사 agent 읽기/쓰기·Gold B 읽기만, 판정 세 경로 쓰기·다른 Gold B/agent 쓰기 거부, 각자 쿼리 결과만 읽기/쓰기, ground_truth 명시 거부를 확인했다. simulation은 실제 Pod/Athena 업무 SQL 검증을 대신하지 않는다. 이번에는 Pod를 띄우거나 S3 테스트 객체·테이블·업무 INSERT를 만들지 않았다. 표 DDL과 partition 생성 필요 권한은 실제 SQL을 받은 뒤 연결한다.

기존 개발자/ECR 준비는 독립 브랜치 infra/agent-development-access의 로컬 커밋에 보존했다. 이 브랜치는 Gold B 준비 PR 이후의 후속 변경이며 push·PR 생성·승인·머지는 하지 않았다. 이 후속 변경 이전의 Gold B 코드로 다시 apply하면 쓰기가 회수될 수 있으므로 이후 plan에는 현재 코드와 비공개 입력을 함께 사용한다.

게시 정리: 선행 #40과 본 브랜치에 최신 main을 반영하고 root 14개·mock suite 12개/plan 68건의 격리 전체 검사를 통과했다. 사용자 요청으로 push하고 [PR #50](https://github.com/josiah113366-sketch/clothes-query/pull/50)을 #40 브랜치 대상으로 생성했다. #40 머지 후 base를 main으로 바꾼다. 개발 접근은 별도 PR #49다. 승인·머지는 팀원이 진행하며 이번 게시 작업에서 추가 AWS 변경은 하지 않았다.
