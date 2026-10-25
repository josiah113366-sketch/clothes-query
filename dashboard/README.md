# 대시보드 (Streamlit) 초기 구성

두 Role로 화면을 나눈 Streamlit 앱. Gold A는 아래 설정으로 Athena에 연결하며, 미리보기 모드는 더미 데이터를 사용한다. **배포 소스(Dockerfile, k8s YAML)는 `infra/platform/dashboard/`에서 관리한다.**

## Gold A 실데이터 연결

- `GOLD_A_DATA_SOURCE=athena`, `GOLD_A_ATHENA_WORKGROUP=<대시보드 조회용 작업그룹>`, `GOLD_A_DATABASE=gold_a`, `AWS_REGION=ap-northeast-1`을 설정한다.
- 작업그룹이 있으면 기본 Athena 모드다. 명시적인 미리보기는 `GOLD_A_DATA_SOURCE=dummy`다. 기존 `DATA_SOURCE=dummy`도 모든 더미를 강제한다.
- `gold_a_io.py`가 `gold_runs`의 업무별 최신 COMPLETED 실행을 화면 재실행 때 한 번 선택한다. 각 지표의 `_runs` 테이블과 `refresh_holds_runs`는 그 run_id로 고정한다. 업무 간 완료 시점은 다를 수 있으며 화면 상단에 각각 표시한다.
- 실연결의 빈 결과·미공개·쿼리 오류는 더미 또는 정상 0건으로 바꾸지 않는다. PARTIAL에서는 같은 실행의 보류 목록을 표시한다. 보류 범위의 이전 결과 유무를 함께 확인해야 한다.
- 실제 상품 ID를 선택한다. 상품명은 현재 Gold 출력에 없으므로 ID를 표시한다. 리뷰 속성은 Gold에 공개된 점수별 건수를 사용하고, 모델 이름·번호가 다른 결과를 한 비율로 합치지 않는다.
- Gold 테이블 정의는 `pipelines/gold_a/tables.sql`이다. Iceberg 최신 모델 뷰는 리뷰 배치가 읽고, 대시보드는 해당 배치가 공개한 Gold 결과를 읽는다.
- 대시보드 역할에는 Athena 조회/상태/결과/취소, Glue DB·테이블·파티션 조회, 공개된 Gold 결과의 S3 읽기 권한이 필요하다. 작업그룹에 결과 저장 위치를 설정하고 그 위치의 쿼리 결과 쓰기·읽기 권한도 부여한다. KMS를 사용하면 해당 키 권한도 필요하다. 원본 변경·Glue 변경 권한은 필요하지 않다.
- 쿼리 완료 대기 한도 60초, 결과 100,000행 초과 시 오류로 알린다. 일부 행만 정상 결과로 표시하지 않는다.
- 통합 화면의 기존 Gold B 장애·처리 현황은 이번 연결 범위 밖이며 미리보기로 표시한다.
- 코드 반영만으로 운영 연결이 완료되지 않는다. 완료된 실제 배치 공개·카탈로그/권한·환경변수·대시보드 이미지 교체 후 실제 Athena 조회를 확인해야 한다.

| Role | 화면 | 데이터(노션 설계 기준) |
|---|---|---|
| product (상품 관리) | 통합 조회, 주문·매출, 상품 판매, 구매 퍼널, 리뷰·속성 분석 | Gold A: order_sales_hourly, product_sales_daily, funnel_daily/funnel_session_product, review_product_daily, review_aspect_daily |
| data (데이터 관리) | 파이프라인 상태, 결제 관제, 형식 오류, 이상탐지, 원인 리포트(임시), 감성분석 모델, 재처리 이력 | Gold B: bronze_lag_snapshots, payment_attempts, malformed_events/messages, anomaly(탐지 담당 정의), reprocess_events, 감성분석 모델 화면은 버전·패치노트를 S3 `review-score/model-registry/releases/`(`MODEL_REGISTRY_URI`)에서, 점수 현황은 athena-review-score 의 review_aspect_scores / review_score_log / silver_reviews_runs(상품·별점만)와 S3 실행 요약에서 읽는다(**더미 없음**, 못 읽으면 '미연결') |


두 Role을 모두 가진 사용자는 전체 화면을 본다.

## 폴더
- `app.py` 진입점. Role에 맞는 메뉴 구성
- `auth.py` 로그인/Role 판정 (`AUTH_MODE=dev|local|oidc`)
- `make_test_accounts.py` 테스트 계정 3개 생성 (local 모드용)
- `data.py` 데이터 조회 함수. Gold A Athena 경로와 기존 미리보기·모델 조회를 분리한다.
- `gold_a_io.py` 완료 실행을 고정해 읽는 Athena 어댑터. 시험: `python -m pytest dashboard/test_gold_a_io.py -q` (저장소 루트에서)
- `ui.py` 공통 선택 위젯(상품·기간)과 표시 도우미(비율 NaN 처리, 날짜 기준 안내, Gold A 결과 없음 안내), 지표 카드(`kpis`)·패널(`panel`)·앱 CSS
- `charts.py` 차트 도우미(streamlit-echarts): 선·막대·흐름·링 게이지·진행 막대. 색 규칙은 파일 맨 위
- `.streamlit/config.toml` 다크 테마와 차트 계열 색. `streamlit run`을 이 폴더에서 해야 적용된다
- `approval_io.py` 재처리 승인 화면의 연결·조회(진짜 Athena/Airflow 또는 연습용 가짜 저장소). 설명은 파일 맨 위, 작업 기록은 `docs/tasks/dashboard-approval-page.md`
- `pages_product/`, `pages_data/` 화면 파일

## 로컬 실행

### 방법 1. Python 직접 실행 (Windows PowerShell 기준)
```powershell
cd C:\workspace\e-commerce\clothes-query\dashboard
python -m venv .venv                 # 가상환경 (처음 한 번)
.\.venv\Scripts\Activate.ps1         # 가상환경 켜기 (터미널 열 때마다)
pip install -r requirements.txt      # 처음 한 번
streamlit run app.py                 # 브라우저가 http://localhost:8501 로 열림
```
- `AUTH_MODE` 기본값이 `dev`라 로그인 없이 열리고, 왼쪽 사이드바 "Role 선택(dev)"에서 Role을 바꿔 가며 화면을 확인한다.
- 코드를 저장하면 브라우저 우측 상단 "Rerun"으로 바로 반영된다.
- 종료는 터미널에서 Ctrl+C.
- 포트가 겹치면 `streamlit run app.py --server.port 8502`

### 계정으로 로그인 (AUTH_MODE=local)
상품 관리 / 데이터 관리 / 관리자 3개 계정으로 아이디·비밀번호 로그인한다. 외부 로그인 서비스가 필요 없고, 실서비스에서도 이 방식으로 쓸 예정이다.
```powershell
python make_test_accounts.py     # 처음 한 번. 비밀번호가 무작위로 만들어져 이 화면에 한 번만 출력됨
$env:AUTH_MODE = "local"
streamlit run app.py
```
| 아이디 | Role | 보이는 화면 |
|---|---|---|
| `product_user` | product | 상품 관리 화면 5개 |
| `data_user` | data | 데이터 관리 화면 5개 |
| `admin` | product + data | 전체 10개 |
- 계정 정보는 `dashboard/.local/accounts.json`(Git 제외)에 **비밀번호가 아닌 해시**로 저장된다. 비밀번호를 잊으면 `python make_test_accounts.py --force`로 새로 만든다.
- 아이디/Role 조합을 바꾸려면 `make_test_accounts.py`의 `ACCOUNTS`를 고친다.
- 사이드바 "로그아웃"으로 다른 계정으로 바꿔 들어가 확인한다.
- 로그인 실패 5번이면 그 아이디를 5분간 잠근다 (`LOGIN_MAX_FAILS`, `LOGIN_LOCK_SECONDS`로 조정).

#### 실서비스에서 local 로그인 쓸 때
- **HTTPS 필수.** HTTP로 열면 비밀번호가 평문으로 오간다. 도메인/인증서(ALB)를 먼저 정한다.
- 접속 허용 IP를 제한한다 (ALB 허용 IP). 로그인만으로 보호하지 않는다.
- 계정 파일을 서비스 안에서 만들지 말고, **따로 만든 `accounts.json`을 Secret으로 마운트**하고 `LOCAL_ACCOUNTS_FILE`로 가리킨다. 비밀번호는 안전한 곳(비밀번호 관리 도구 등)에 보관하고 Git/문서에 적지 않는다.
- 비밀번호는 무작위 값을 쓰고, 담당자가 바뀌면 `--force`로 새로 만들어 교체한다.
- 실패 잠금은 서버 메모리에서 센다. 파드를 여러 개로 늘리면 파드마다 따로 세므로, 처음엔 replicas 1로 둔다.
- 세션 만료 시간은 따로 없다 (브라우저를 닫으면 로그아웃). 필요하면 추가한다.
- 계정은 3개 공용이라 **누가 봤는지는 구분되지 않는다.** 개인별 기록이 필요해지면 `oidc`를 검토한다.

### (선택) 실제 OIDC 로그인 시험
로그인은 Streamlit 내장 `st.login`(OIDC)을 쓴다. 로컬에서는 개인 구글 계정으로 시험하는 것이 가장 간단하다.

1. 구글 클라우드 콘솔 > API 및 서비스 > 사용자 인증 정보 > OAuth 클라이언트 ID(웹 애플리케이션) 생성
   - 승인된 리디렉션 URI: `http://localhost:8501/oauth2callback`
   - (OAuth 동의 화면이 테스트 상태이면 "테스트 사용자"에 시험할 계정 이메일을 추가)
2. `dashboard/.streamlit/secrets.toml` 작성 (이 파일은 `dashboard/.gitignore`로 Git에서 제외됨. 값은 절대 올리지 않는다)
```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "임의의 긴 문자열"          # 예: python -c "import secrets;print(secrets.token_urlsafe(32))"
client_id = "구글에서 받은 클라이언트 ID"
client_secret = "구글에서 받은 클라이언트 시크릿"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```
3. 환경변수를 설정하고 실행 (PowerShell)
```powershell
$env:AUTH_MODE = "oidc"
$env:ROLES_JSON = '{"내이메일@gmail.com": ["product","data"], "다른이메일@gmail.com": ["product"]}'
streamlit run app.py
```
4. 확인할 것
   - 로그인 전: "로그인이 필요합니다" 화면과 로그인 버튼만 보이는지
   - `["product","data"]` 계정: 두 그룹 메뉴가 모두 보이는지
   - `["product"]` 계정: 상품 관리 메뉴만 보이고, 데이터 관리 화면 주소(예: `/payments`)를 직접 입력해도 막히는지
   - `ROLES_JSON`에 없는 계정: "접근 권한이 없습니다"가 나오는지
   - 사이드바 "로그아웃"으로 다른 계정으로 바꿔 들어가 보기
- 이메일은 대소문자 구분 없이 비교한다. `ROLES_JSON` 형식이 깨지면 아무도 들어가지 못한다(열어두는 쪽으로 실패하지 않음).
- 로그인 로직(이메일 -> Role) 자체는 로그인 없이도 `AUTH_MODE=dev`(Role 직접 선택)로 화면별 접근 제어를 먼저 확인할 수 있다.
- 구글 대신 사내 공급자(Cognito 등)를 쓸 때는 `[auth]`의 `client_id`, `client_secret`, `server_metadata_url`만 바꾼다.

## 화면 꾸미기 (2026-10-24)
- 차트는 `st.line_chart`/`st.bar_chart` 대신 `charts.py`(Apache ECharts)를 쓴다. 새 화면도 `charts.line(df, key=...)`처럼 같은 함수를 쓴다. `key`는 화면 안에서 차트마다 달라야 한다.
- 숫자 요약은 `st.metric` 대신 `ui.kpis([...])` 카드를 쓴다(증감 배지, 작은 추이선). 섹션은 `with ui.panel("제목", "설명"):`로 감싼다. 아직 `st.metric`을 쓰는 화면도 CSS로 카드 모양이 된다.
- 색을 바꿀 때는 `.streamlit/config.toml`(바탕·계열 색), `charts.py`(PALETTE·상태 색), `ui.py`(`_CSS`) 세 곳을 같이 본다. 계열 색 순서는 색약 구분 검사를 통과한 순서라 바꾸면 다시 검사한다.

## 배포 (EKS, `infra/platform/dashboard/`)
배포 파일과 순서는 [`infra/platform/dashboard/README.md`](../infra/platform/dashboard/README.md), 외부 접속(ALB)은 [`infra/platform/ingress/README.md`](../infra/platform/ingress/README.md)에 있다. 이 앱 쪽에서 알아둘 것만 적는다.
1. 로그인은 `AUTH_MODE=local`이다. 계정 파일(`accounts.json`)을 `python make_test_accounts.py --force`(필요하면 `--same-as-id`)로 만들어 Secret으로 마운트하고 `LOCAL_ACCOUNTS_FILE`로 가리킨다. 이미지에는 넣지 않는다.
2. ALB는 HTTP이고 허용 IP만 접속한다. 운영 전에 도메인과 HTTPS로 바꾼다(위 "실서비스에서 local 로그인 쓸 때" 참고).
3. Athena/S3 읽기 권한(Pod Identity 역할)을 붙인 뒤 `data.py`의 `_REAL`에 조회 함수를 등록하고 `DATA_SOURCE=auto`로 바꾼다. 그 전에는 `dummy`.
4. 감성분석 모델 화면 (**더미 없음**, 2026-10-25): 버전·패치노트·평가 지표는 `MODEL_REGISTRY_URI=s3://<버킷>/review-score/model-registry/releases/`의 `index.json`·`<버전>.json`을, 점수 현황은 Athena(`DASHBOARD_ATHENA_WORKGROUP` 또는 `APPROVAL_ATHENA_WORKGROUP`)로 DB `clothes_query_dev_review_score`(`REVIEW_SCORE_DATABASE`)의 `review_aspect_scores`·`review_score_log`·`silver_reviews_runs`(상품·별점·작성일, 그리고 2탭 '후기 목록'과 3탭 '점수 차가 큰 후기'의 원문. 원문은 팀 내부용)를, Job 실행 요약은 S3 `staging/review-score/_summary_scores_*.json`(`REVIEW_SCORE_STAGING_URI`, 기본은 레지스트리와 같은 버킷)을 읽는다. 최근 Silver 실행은 `silver/runtime/reviews/current.json`(`REVIEW_SILVER_ROOT_URI`)의 PASS 실행이다. 설정이 없거나 읽기에 실패하면 해당 탭·칸을 회색 '미연결'로 보여 주고 가짜 숫자를 만들지 않는다. 조회 코드는 `model_io.py`(시험 `python -m pytest dashboard/test_model_io.py -q`). 읽기 권한은 dashboard-access 의 `enable_review_score_reads` 가 준다. 로컬 확인: AWS 자격증명이 있는 셸에서 `DASHBOARD_ATHENA_WORKGROUP=... MODEL_REGISTRY_URI=... streamlit run app.py`.
5. 파이프라인 상태 › 데이터 흐름 탭: `DASHBOARD_ATHENA_WORKGROUP`(없으면 `APPROVAL_ATHENA_WORKGROUP`)과 `AWS_REGION`이 있으면 Athena에서 `gold_b.bronze_lag_snapshots`, `silver.silver_runs`, `gold_a.gold_runs`, Gold B 원장 3개를 60초마다 읽는다. 이 탭은 **더미로 대체하지 않는다.** workgroup이 없거나 읽는 곳이 아직 없는 단계는 회색 "미연결", 조회가 실패한 단계는 회색 "확인 불가"로 그린다. 같은 환경변수가 있으면 지연·점검 탭의 지연 측정도 실데이터를 읽는다.
6. 결제 관제·형식 오류·재처리 이력 (TODO B1): 같은 workgroup 환경변수가 있으면 `gold_b.payment_attempts` 뷰(최근 6시간), `gold_b.malformed_events`(최근 6시간, 시간 폴더 조건), `gold_b.reprocess_events`(최근 7일)를 읽는다. 조회가 실패하면 다른 화면처럼 더미로 대체하고 화면 아래에 더미라고 적는다. 결과가 없으면 결제 관제는 더미로 대체하고, 형식 오류·재처리 이력은 평소 0건이 정상이라 0건으로 보여 준다 (2026-10-25). 결제 관제는 대시보드 역할에 뷰 `payment_states`·`payment_attempts`의 Glue 읽기 권한(`glue:GetTable`)이 더 있어야 한다 (2026-10-24 기준 없음, TODO F3). 형식 오류·재처리 기록은 지금 권한으로 읽힌다.
7. 시나리오 2·3 (TODO B10): 같은 workgroup 환경변수가 있으면 파이프라인 상태 › 지연·점검 탭이 `gold_b.topic_messages`에서 토픽별 1분 유입(최근 180분, 시간 폴더 조건)을, 결제 관제가 `gold_b.payment_attempts` 뷰에서 최근 6시간에 적재된 성공 결제의 주문 중 성공이 2건 이상인 주문(판정 R5와 같은 방식)을 읽는다. 이 두 칸은 비어 있는 것이 정상이거나 신호라 결과가 비어도 더미로 바꾸지 않고(`dataset(..., allow_empty=True)`), 조회가 실패할 때만 더미로 대체한다. 성공 결제 중복도 결제 뷰 읽기 권한이 필요하다.

## 추후 할 일
baseline 이후 영역별 할 일(담당자·상태 기록용)은 [`TODO.md`](TODO.md)에 정리한다. 아래는 그중 핵심.
- [ ] **원인 리포트에 담을 내용 정하기**: 지금 `원인 리포트` 화면은 임시 구성(제안)이다. 노션에 리포트 항목이 정해져 있지 않아, 조사 에이전트 담당과 맞춰 확정한 뒤 `data.get_rca_reports()`와 `pages_data/rca_report.py`를 고친다.
- [ ] 슬랙 알림 연동 여부, 재처리 승인 화면 호출 방식(Airflow 결정 이후)

## 주의
- 운영에서 `AUTH_MODE=dev` 금지 (누구나 Role 선택 가능).
- 리뷰 원문은 내부용. 외부 서비스/Git에 올리지 않는다.
- 비밀값(계정 파일, OIDC를 쓸 때의 이메일 표·키)은 Git에 넣지 않는다.
