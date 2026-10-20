# 대시보드 (Streamlit) 초기 구성

두 Role로 화면을 나눈 Streamlit 앱. 지금은 **더미 데이터**이며 EKS에는 아직 올리지 않았다.

| Role | 화면 | 데이터(노션 설계 기준) |
|---|---|---|
| product (상품 관리) | 통합 조회, 주문·매출, 상품 판매, 구매 퍼널, 리뷰·속성 분석 | Gold A: order_sales_hourly, product_sales_daily, funnel_daily/funnel_session_product, review_product_daily, review_aspect_daily |
| data (데이터 관리) | 파이프라인 상태, 결제 관제, 형식 오류, 이상탐지, 재처리 이력 | Gold B: bronze_lag_snapshots, payment_attempts, malformed_events/messages, anomaly(탐지 담당 정의), reprocess_events |

두 Role을 모두 가진 사용자는 전체 화면을 본다.

## 폴더
- `app.py` 진입점. Role에 맞는 메뉴 구성
- `auth.py` 로그인/Role 판정 (`AUTH_MODE=dev|oidc`)
- `data.py` 데이터 조회 함수(지금은 더미, 테이블/컬럼 이름은 노션 설계 그대로). **실연결 때 함수 본문만 Athena 조회로 교체**
- `ui.py` 공통 선택 위젯(상품·기간)과 표시 도우미(비율 NaN 처리, 날짜 기준 안내)
- `pages_product/`, `pages_data/` 화면 파일
- `Dockerfile`, `k8s/` 배포용 초안

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

### 방법 2. Docker로 실행 (EKS와 같은 이미지로 확인)
```powershell
docker build -t review-dashboard:dev .
docker run --rm -p 8501:8501 review-dashboard:dev     # http://localhost:8501
```
- 이미지의 기본값이 아니라 환경변수 기본값(`AUTH_MODE=dev`)으로 뜬다. 로그인(oidc)까지 시험하려면 OIDC 설정이 필요해 로컬에서는 보통 dev로 확인한다.

### OIDC 로그인 로컬 시험 (선택)
`.streamlit/secrets.toml`(Git 제외)에 `[auth]` 항목(redirect_uri, cookie_secret, client_id, client_secret, server_metadata_url)을 채우고 `AUTH_MODE=oidc`, `ROLES_JSON='{"내이메일":["product","data"]}'` 환경변수를 설정한 뒤 실행한다. 값은 EKS 담당자가 정한 로그인 공급자 기준이다.

## EKS 배포 전에 정할 것 (EKS 담당자와)
1. 네임스페이스, ECR 저장소, 이미지 digest
2. 로그인(OIDC 공급자, 예: Cognito) -> `.streamlit/secrets.toml` 의 `[auth]` 항목을 Secret으로 주입
3. 이메일 -> Role 표(`ROLES_JSON`)를 Secret `dashboard-roles` 로 생성
4. ALB 허용 IP, 도메인/HTTPS
5. Athena/S3를 읽을 ServiceAccount + Pod Identity 역할 (데이터 연결 시)

## 배포 순서 (참고)
`docker build` -> ECR push -> `<자리표시자>` 채우기 -> `kubectl apply -f k8s/`

## 주의
- 운영에서 `AUTH_MODE=dev` 금지 (누구나 Role 선택 가능).
- 리뷰 원문은 내부용. 외부 서비스/Git에 올리지 않는다.
- 비밀값(이메일 표, OIDC 키)은 Git에 넣지 않는다.
