# Gold B query roles

기존 EKS의 agent namespace에서 실행할 판정·조사 Pod 전용 IAM 역할, Pod Identity association, Athena workgroup을 준비한다. workgroup별로 기존 데이터 S3의 분리된 결과 prefix를 강제한다. 기존 Bronze Sink·개발자 사용자/그룹·Glue DB/table은 변경하지 않는다.

데이터 권한은 gold_b/ 읽기, Glue gold_b 메타데이터 읽기, 자기 결과 prefix 읽기·쓰기다. ground_truth/ 객체와 해당 prefix 목록은 명시적으로 Deny한다. 조사 역할에 업무 데이터 쓰기는 주지 않는다. 판정 이력 쓰기는 detection_write_prefixes에 명시한 경로만 허용하며 초기에는 비어 있다. 객체 삭제·카탈로그 수정·관리자·다른 역할 AssumeRole 권한은 부여하지 않는다. Athena StartQueryExecution 자체를 SELECT-only로 제한하는 기능은 아니다.

namespace/ServiceAccount/업무 Pod는 이 AWS 전용 모듈에서 만들지 않는다. [호출 스택](../../stacks/gold-b-access/README.md)을 사용한다. 실제 데이터 조회, Lake Formation/KMS/네트워크의 추가 제한, 뷰 의존성과 실제 역할의 금지 경로 접근 거부는 적용 후 검증 대상이다.
