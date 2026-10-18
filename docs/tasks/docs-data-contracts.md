# 작업 지시서: docs/data-contracts

상태: 완료 (로컬 초안 작성・확인) · 브랜치: `docs/data-contracts` · 합의・머지: 대기

## 목표

사용자 승인에 따라 공통 계약 문서와 형식 검사 YAML 초안을 별도 파일로 작성한다. 작업은 `docs/`에 한정하고 Silver・Gold A・Gold B 실행 코드는 연결하지 않는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `docs/BRANCHES.md`
- `db/schema/004_orders.sql`, `simulator/README.md`, `simulator/src/sim/behavior/sink.py`
- 사용자 제공 Gold B 설계와 결제・주문・주문상품 계약 정리

## 만드는 것

- `docs/contracts/README.md`: 데이터 의미와 역할, 경로 간 제안, 재처리・대조 방향. 폴더 README를 계약 본문으로 사용한다.
- `docs/contracts/format_rules.yaml`: 현 DDL 기반 단일 행 검사 규칙과 적용 전 합의할 변경안.
- 이 작업 지시서 1개, `docs/BRANCHES.md`의 docs 구역 한 줄.

## 작업 순서

1. 최신 `origin/main`에서 `docs/data-contracts` 생성.
2. 확정 원천 규칙과 합의 대기 제안을 구분해 두 파일 작성.
3. YAML 문법・원천 필드 대응과 문서 링크, 변경 범위를 확인.
4. 사용자 승인에 따라 문서 파일만 커밋・push하고 Draft PR로 검토 요청. 머지는 별도 승인 후 진행.

## 완료 확인

- [x] YAML을 안전한 로더로 읽을 수 있음.
- [x] 데이터셋 3개의 필드・필수 여부・타입・허용 값이 DDL과 대응함.
- [x] YAML 조건에서 참조한 필드가 존재하고 검사 ID가 중복되지 않음.
- [x] 미합의 UNKNOWN 허용안을 원천 규칙과 구분했으며 실행 코드에 연결하지 않음.
- [x] 문서 상대 링크와 diff 공백 검사 통과.
- [x] 변경 파일이 docs 영역에 한정됨. 기존 미추적 pipelines 내용은 보존.

## 작업 결과

- **무엇을 만들었나:** 계약 본문을 겸하는 README, YAML 초안, 작업 지시서. 브랜치 대장에 작업 등록.
- **왜:** 사람의 처리 약속과 프로그램의 단일 행 검사 규칙을 구분하면서 같은 변경에서 검토하기 위해.
- **입력과 출력:** 거래 DDL과 제공된 Gold B 설계 → 원천 확인 규칙, 합의할 변경안, 재처리・대조 접점.
- **확인한 결과:** 일회성 확인 명령으로 PyYAML 파싱, 3개 데이터셋・23개 컬럼의 DDL 대응, 조건 7개의 필드 참조와 ID 중복 여부, 문서 상대 링크 확인 통과. `git diff --check` 통과. 새 테스트 파일은 만들지 않음.
- **한계・다음 할 일:** 실제 데이터 검사기는 구현하지 않았음. 공통 형식・배포 위치・UNKNOWN 처리・내용 충돌・재처리 연결 합의 필요. Silver・Gold A 코드 변경 없음. 사용자 승인으로 Draft PR 검토를 요청하며 머지는 별도 승인 후 진행.
