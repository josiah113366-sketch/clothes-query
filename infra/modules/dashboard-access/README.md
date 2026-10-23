# 승인 대시보드 접근

기존 EKS의 dashboard/approval-dashboard Pod Identity, 전용 Athena workgroup과 S3 결과 경로를 준비한다. gold_b.anomaly_current 및 기반 anomaly, agent.investigation_reports, gold_b.reprocess_events 메타데이터·원본을 읽는다. 업무 쓰기는 gold_b/reprocess_events/에만 허용하며 객체 삭제·Glue DDL·Bedrock·다른 결과 경로·ground_truth 접근은 허용하지 않는다.

2026-10-23 모델 패치노트 조회를 위해 `model_registry_prefix`(기본 `review-score/model-registry/releases/`)의 GetObject와 제한된 목록 조회를 추가한다. 이 경로 쓰기·삭제·모델 가중치 읽기는 추가하지 않는다. 기존 역할·workgroup·Pod Identity는 같은 dashboard-access state에서 관리한다. 상세 배포·검증은 [작업 기록](../../../docs/tasks/infra-dashboard-runtime-connect.md)을 참고한다.

IAM은 REQUESTED/APPROVED 같은 행의 값을 검사하지 않는다. 상태 전이·승인자 검증·중복 방지는 앱 담당자가 구현한다. Airflow 인증은 IAM 정책과 별개이며 Kubernetes Secret으로 공급한다. Simple Auth의 user 역할은 특정 DAG만 허용하는 경계를 제공하지 않는다. 모듈은 기존 workload 역할이나 dashboard 앱을 변경하지 않는다.
