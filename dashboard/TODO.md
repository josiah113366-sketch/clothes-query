# dashboard baseline 이후 할 일

`dashboard/baseline` 브랜치의 결과(Role 2개, 화면 11개, 더미 데이터, 계정 3개 로그인)를 **출발점(baseline)** 으로 두고, 이후 진행해야 할 일을 영역별로 정리한 문서다.
틀만 잡아 두었고, **담당자·상태·메모는 각 담당자가 채운다.** 항목이 끝나면 상태를 바꾸고, 새로 생긴 일은 해당 영역에 한 줄 추가한다.

- 상태: `대기` / `진행 중` / `완료` / `보류`
- "선행 조건"은 이 일을 시작하기 전에 필요한 입력이다 (다른 영역의 확정 사항 등).
- 작업을 시작할 때는 `docs/tasks/`에 작업 지시서를 만들고, `docs/BRANCHES.md` 대장에 한 줄 추가한다.

## baseline에 들어 있는 것

| 구분 | 내용 |
|---|---|
| Role | 상품 관리(`product`), 데이터 관리(`data`). 화면 단위로 구분. 관리자 계정은 둘 다 가짐 |
| 상품 관리 화면 | 통합 조회, 주문·매출, 상품 판매, 구매 퍼널, 리뷰·속성 분석 (Gold A 설계 기준) |
| 데이터 관리 화면 | 파이프라인 상태, 결제 관제, 형식 오류, 이상탐지, 원인 리포트(임시), 재처리 이력 (Gold B 설계 기준) |
| 데이터 | 전부 더미. 실데이터 조회 함수를 `data.py`의 `_REAL`에 등록하면 먼저 쓰고, 없거나 실패하면 더미로 대체 |
| 로그인 | `AUTH_MODE=local`(고정 계정 3개, 아이디·비밀번호), `oidc`(선택), `dev`(Role 직접 선택) |
| 배포 | 포함하지 않음. 추후 `infra/platform/dashboard/` |

## 1. 데이터 연결 — Gold A (상품 관리 화면)

| # | 할 일 | 선행 조건 | 담당 영역 | 담당자 | 상태 | 메모 |
|---|---|---|---|---|---|---|
| A1 | Gold A 6개 테이블(`order_sales_hourly`, `product_sales_daily`, `funnel_session_product`, `funnel_daily`, `review_product_daily`, `review_aspect_daily`)의 Athena 조회 함수를 만들어 `_REAL`에 등록 | Gold A 테이블 생성, Glue DB·테이블 이름 확정 | `gold-a` / `dashboard` | | 대기 | |
| A2 | 실제 상품 목록으로 상품 선택(`data.PRODUCTS`)과 이름 표시를 교체 | 상품 기준정보(`article_id`, `product_code`, 이름) 조회 방법 | `dashboard` | | 대기 | |
| A3 | 리뷰 `product_id` ↔ `article_id` 연결 확인 (임시 ID를 `article_id`로 쓰지 않음) | 상품 연결 검증 결과 | `silver` / `gold-a` | | 대기 | 노션: 연결 검증 후 사용 |
| A4 | 모델 버전 목록(`MODEL_VERSIONS`)을 실제 값으로 | 분석모델 버전 기록 위치 | `review-model` | | 대기 | |
| A5 | 통합 조회의 "데이터 상태"(처리 완료 범위, 품질 결과)를 실행 기록에서 읽도록 연결 | Gold A 실행 기록 테이블 | `gold-a` | | 대기 | |
| A6 | Gold A 지표 중 대시보드에서 **무엇을 어떻게 표현할지** 확정 (기획서 "대시보드에서 표현할 사항 결정 필요") | 부서별 요구 정리 | | | 대기 | |

## 2. 데이터 연결 — Gold B (데이터 관리 화면)

| # | 할 일 | 선행 조건 | 담당 영역 | 담당자 | 상태 | 메모 |
|---|---|---|---|---|---|---|
| B1 | Gold B 원장·뷰(`bronze_lag_snapshots`, `payment_attempts`, `malformed_events`, `malformed_messages`, `reprocess_events`)의 Athena 조회 함수를 `_REAL`에 등록 | Gold B 적재 운영, Athena 접근 권한 | `gold-b` / `dashboard` | | 대기 | 시각은 UTC 저장 |
| B2 | `gold_b.anomaly` 컬럼 확정 후 이상탐지 화면 맞춤 | 탐지 담당의 표 정의 | `agent` | | 대기 | 지금 컬럼은 임시 |
| B3 | 신뢰성 점검 3종(오프셋 빈틈, 중복, 적재 정지) 결과를 실제 점검 쿼리에서 읽도록 연결 | 점검 쿼리 Athena 실행 | `agent` / `gold-b` | | 대기 | |
| B4 | 파이프라인 상태의 "평소 범위" 기준(`NORMAL_MAX_SEC`, 현재 1,020초)과 경고 규칙 확정 | 실측 지연 분포 | `gold-b` / `agent` | | 대기 | 15분 파일 주기 톱니 |
| B5 | 형식 오류 화면의 현재 `rule_version` 선택 방식 확정 | 공통 규칙 YAML 버전 운영 방식 | `gold-b` | | 대기 | |

## 3. 원인 리포트 / 승인

| # | 할 일 | 선행 조건 | 담당 영역 | 담당자 | 상태 | 메모 |
|---|---|---|---|---|---|---|
| C1 | **원인 리포트에 담을 내용 정하기** (현재 화면은 제안: 규칙, 원인 요약, 확인된 사실/추정, 영향 범위, 근거, 조치 진행, 다운로드) | 노션에 항목 없음. 조사 에이전트 출력 형식 | `agent` | | 대기 | `data.get_rca_reports()`, `pages_data/rca_report.py` |
| C2 | 확정한 내용으로 `get_rca_reports()`를 실데이터에 연결 | C1, 리포트 저장 위치 | `agent` / `dashboard` | | 대기 | |
| C3 | 슬랙 알림 연동 여부 결정 | C1 | `agent` | | 대기 | 노션: 대시보드와 슬랙으로 내보냄 |
| C4 | 재처리 **승인 화면** (승인/거절, 범위, 규칙 버전) | Airflow 버전·Auth Manager 결정 | `agent` / `infra` | | 대기 | 지금 화면은 읽기 전용 |
| C5 | 리뷰 원문 목록·LLM 요약 (조사 편의 기능) | 원문 조회 방식과 권한 결정. 원문은 내부용, 외부 서비스 반출 금지 | `dashboard` | | 대기 | 노션: 검토 단계 |

## 4. 화면·권한 정책

| # | 할 일 | 선행 조건 | 담당 영역 | 담당자 | 상태 | 메모 |
|---|---|---|---|---|---|---|
| D1 | 상품 관리 Role에 Gold B 장애 기록("관련 장애")을 보여줘도 되는지 결정 | | | | 대기 | 노션: Gold A가 Gold B 장애 기록을 함께 조회 |
| D2 | 계정 3개(상품 관리 / 데이터 관리 / 관리자) 구성 확정, 필요 시 Role 세분화 | 사용자 범위 | | | 대기 | 행 단위 제한이 필요해지면 도구 재검토 |
| D3 | 기간 기본값·최대 기간, 비교 기간(전주 대비 등) 표시 여부 | A6 | | | 대기 | |
| D4 | 판매 감소 자동 알림 등 Gold A 기반 추가 탐지 규칙 (집계 완료 범위, 비교 기간, 최소 데이터량, 감소 기준, 반복 알림 기준) | 탐지 담당과 협의 | `agent` | | 보류 | 노션: 검토 |

## 5. 로그인·보안 (실서비스)

| # | 할 일 | 선행 조건 | 담당 영역 | 담당자 | 상태 | 메모 |
|---|---|---|---|---|---|---|
| E1 | 실서비스 계정 파일(`accounts.json`) 생성과 Secret 보관, `LOCAL_ACCOUNTS_FILE`로 연결 | 배포 환경 Secret 관리 방식 | `infra` | | 대기 | 비밀번호는 Git·문서에 적지 않음 |
| E2 | **HTTPS(도메인·인증서)** 적용과 ALB 허용 IP 제한 | 도메인, 허용 IP | `infra` | | 대기 | HTTP로 열면 비밀번호가 평문 |
| E3 | 세션 만료 시간 추가 여부 결정·구현 | | `dashboard` | | 대기 | 지금은 브라우저를 닫으면 로그아웃 |
| E4 | 파드를 여러 개로 늘릴 때 로그인 실패 잠금 공유 방식(지금은 파드별) | 확장 계획 | `dashboard` | | 보류 | 처음엔 replicas 1 |
| E5 | 개인별 접속 기록이 필요하면 OIDC 전환 검토 | 감사 요구 | | | 보류 | 코드에는 `oidc` 모드가 남아 있음 |

## 6. 배포 (`infra/platform/dashboard/`)

| # | 할 일 | 선행 조건 | 담당 영역 | 담당자 | 상태 | 메모 |
|---|---|---|---|---|---|---|
| F1 | 이미지 빌드·ECR 등록, Dockerfile 작성 | 네임스페이스·ECR 저장소 확정 | `infra` | | 대기 | 초안: 프로젝트 파일 `dashboard-deploy-draft/` |
| F2 | Deployment/Service/Ingress(ALB) 작성 | F1, EKS 담당자와 방식(YAML 또는 Terraform) 합의 | `infra` | | 대기 | EKS는 노드 1대(24GiB 한도), Auto Mode |
| F3 | Athena/S3 읽기용 Pod Identity 역할 (읽기 전용, `gold_a/`·`gold_b/`만. `ground_truth/` 접근 금지) | A1, B1 | `infra` | | 대기 | |
| F4 | 환경변수·Secret 주입 (`AUTH_MODE=local`, `LOCAL_ACCOUNTS_FILE`, `DATA_SOURCE`) | E1 | `infra` | | 대기 | |

## 7. 품질·운영

| # | 할 일 | 선행 조건 | 담당 영역 | 담당자 | 상태 | 메모 |
|---|---|---|---|---|---|---|
| G1 | 의존성 버전 고정 (`requirements.txt`는 하한만 있음) | | `dashboard` | | 대기 | pandas 2.2.3·3.0.6에서 확인 |
| G2 | 실데이터 연결 후 응답 속도·캐시 시간(`_TTL_A`, `_TTL_B`) 조정, Athena 조회 비용 확인 | A1, B1 | `dashboard` | | 대기 | |

## 참고
- 설계 근거: 노션 「Gold A 설계 정리」, 「Gold B 칼럼 구성」, 「탐지·조사 에이전트 설계 및 프로토타입」
- 이 브랜치의 작업 지시서: [`docs/tasks/dashboard-baseline.md`](../docs/tasks/dashboard-baseline.md)
- 사용법과 로그인: [`README.md`](README.md)
