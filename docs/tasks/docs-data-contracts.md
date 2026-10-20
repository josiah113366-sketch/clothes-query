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

- **2026-10-20 실행 연결 승인 반영:** 사용자 승인으로 source_rules_status=decided・version=0.1.0, runtime_connected를 silver=true/gold_b=false 경로별 상태로 변경했다. proposed_changes는 제안으로 유지한다. 공통 검사기는 pipelines/format_rules.py이며 거래 Silver에서 실제 실행하고 버전/해시/경로/규칙 ID를 기록한다. 계약 브랜치와 파이프라인 브랜치에 같은 원본을 보존한다. 로컬 파이프라인 46개 테스트가 통과했으며 운영/Gold B 적용 완료는 아니다. 기존의 문서 초안만 작성한 기록은 과거 작업 범위다.

- **2026-10-20 실패 코드 기준 보완:** 원천 DDL/YAML 5개 허용값을 현재 Silver 검사 기준으로 명시했다. 누락・비문자열・미등록・성공 코드 오류를 구분하는 표와 미등록 허용의 이점/위험을 추가했다. UNKNOWN은 원본 코드 대체가 아니라 Gold B 분류라는 제안이며 합의 전에는 실행하지 않는다. source_rules의 enum・runtime_connected=false는 유지했다. YAML 문법과 DDL 허용값 일치 확인 후 계약 브랜치 로컬 커밋으로 보존한다.

- **2026-10-20 문서 보완:** 계약 README 8절에 오류 영향 범위・범위별 갱신 보류・manifest 기록・복구 기준을 제안으로 추가하고, 5절 내용 충돌에서 연결했다. 기존 결제 보존 제안 수정은 유지했다. YAML・실행 코드 변경 없음. 문서 간 기준과 diff 공백을 확인하며 실제 부분 갱신 동작은 아직 구현하지 않는다.

- **무엇을 만들었나:** 계약 본문을 겸하는 README, YAML 초안, 작업 지시서. 브랜치 대장에 작업 등록.
- **왜:** 사람의 처리 약속과 프로그램의 단일 행 검사 규칙을 구분하면서 같은 변경에서 검토하기 위해.
- **입력과 출력:** 거래 DDL과 제공된 Gold B 설계 → 원천 확인 규칙, 합의할 변경안, 재처리・대조 접점.
- **확인한 결과:** 일회성 확인 명령으로 PyYAML 파싱, 3개 데이터셋・23개 컬럼의 DDL 대응, 조건 7개의 필드 참조와 ID 중복 여부, 문서 상대 링크 확인 통과. `git diff --check` 통과. 새 테스트 파일은 만들지 않음.
- **한계・다음 할 일:** 실제 데이터 검사기는 구현하지 않았음. 공통 형식・배포 위치・UNKNOWN 처리・내용 충돌・재처리 연결 합의 필요. Silver・Gold A 코드 변경 없음. 사용자 승인으로 Draft PR 검토를 요청하며 머지는 별도 승인 후 진행.
