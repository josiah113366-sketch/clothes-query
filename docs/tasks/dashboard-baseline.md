# 작업 지시서: dashboard/baseline

> 상태: 진행 중 · 브랜치: `dashboard/baseline` · 다음 작업: `infra/dashboard-deploy` (배포 소스 `infra/platform/dashboard/`)

## 목표

Gold A·Gold B 결과를 보여 주는 대시보드 앱의 **기본 골격**을 만든다. Role 두 개(상품 관리, 데이터 관리)를 화면 단위로 나누고, 데이터는 우선 더미로 보이게 한다.
실데이터(Athena) 연결, 배포(EKS), 로그인 공급자 연결은 하지 않는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`
- 노션 「Gold A 설계 정리 | 분석 지표·통합 조회·Gold B 연계」 (Gold A 6개 데이터셋, 시나리오 A~E, 7장 통합 조회 화면)
- 노션 「Gold B 칼럼 구성」 (원장 5개, 정리 뷰 2개, 시나리오 1~3, 재처리 단계)
- `docs/design/infra/target_architecture.md` (대시보드는 EKS 안에 올릴 예정)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 앱은 Streamlit으로 만든다. (비교한 대안: 정적 HTML, Grafana, Superset, FastAPI+React → Role이 2개이고 화면 단위 구분이면 Streamlit으로 충분. 사용자별 데이터 행 단위 제한이 필요해지면 Superset을 다시 검토)
- Role은 **상품 관리**(`product`)와 **데이터 관리**(`data`) 두 가지이고, 구분은 **화면 단위**다. 두 Role을 모두 가진 사용자는 전체 화면을 본다.
- 데이터가 없거나 조회에 실패하면 **더미 데이터로 대체**해서 보여 주고, 더미를 쓰는 중이라는 표시를 한다.
- **배포 소스(Dockerfile, k8s YAML)는 이 폴더에 두지 않는다.** 추후 `infra/platform/dashboard/` 아래에 두고 배포한다.
- 코드 주석은 한국어로 자세히 쓴다. (바꿀 값과 이유를 적는다)
- git commit은 하지 않는다. commit 단위가 되었다고 판단되면 메시지만 제안한다.

## 시작 전 확인 (Claude가 한다)

- 브랜치가 최신 `main`에서 만들어졌는지, `docs/BRANCHES.md`에 `dashboard` 영역과 이 브랜치 한 줄이 있는지
- Gold A·Gold B 노션 문서가 이 지시서 작성 이후 바뀌지 않았는지 (컬럼 이름이 바뀌면 `dashboard/data.py`를 맞춘다)

## 만드는 것

### 1. 앱 골격 (`dashboard/`)
- `app.py` 진입점. 로그인 사용자의 Role에 맞는 메뉴만 보여 주고, 더미 사용 중이면 사이드바에 표시
- `auth.py` Role 판정. `AUTH_MODE=dev`(로컬, Role 직접 선택) / `local`(테스트 계정 3개: 상품관리·데이터관리·관리자, 아이디·비밀번호, `make_test_accounts.py`) / `oidc`(로그인 + 이메일→Role 표 `ROLES_JSON`). 목록에 없는 사용자는 접근 불가. 각 화면에서도 Role을 한 번 더 검사
- `data.py` 데이터 조회 함수. 테이블·컬럼 이름은 노션 설계 그대로. `_REAL`에 실조회 함수를 등록하면 먼저 쓰고, 없거나 실패하거나 비면 더미로 대체
- `ui.py` 상품·기간 선택, 비율 표시(분모 0이면 "계산 불가"), 날짜 기준 안내

### 2. 화면
| Role | 화면 | 데이터 |
|---|---|---|
| 상품 관리 | 통합 조회 | Gold A 전체 + Gold B 장애 기록 + 데이터 상태 |
| 상품 관리 | 주문·매출 | `order_sales_hourly` |
| 상품 관리 | 상품 판매 | `product_sales_daily` |
| 상품 관리 | 구매 퍼널 | `funnel_daily`, `funnel_session_product` |
| 상품 관리 | 리뷰·속성 분석 | `review_product_daily`, `review_aspect_daily` |
| 데이터 관리 | 파이프라인 상태 | `bronze_lag_snapshots`, 신뢰성 점검 |
| 데이터 관리 | 결제 관제 | `payment_attempts` 뷰 |
| 데이터 관리 | 형식 오류 | `malformed_events`, `malformed_messages` 뷰 |
| 데이터 관리 | 이상탐지 | `gold_b.anomaly` (컬럼 임시) |
| 데이터 관리 | 재처리 이력 | `reprocess_events` |

### 3. 노션 해석 규칙을 화면에 반영
- 분모 0인 비율은 0%가 아니라 "계산 불가"
- 기간 평균 별점·전환율은 일별 비율의 평균이 아니라 합계끼리 다시 나눔
- 차트 날짜 기준 표시: 판매=결제일, 퍼널=첫 조회일, 리뷰=작성일 (모두 KST). Gold B는 UTC 저장이라 화면에서 KST로 변환
- 속성별 리뷰 수는 합쳐 전체 리뷰 수로 쓰지 않음. 모델 버전은 하나를 골라서 봄
- 낮은 별점(1~2점)과 AI 부정 감성을 구분
- 디자인(`product_code`)별 주문 수는 상품별 주문 수를 합산하지 않음
- 같은 시기에 변한 지표는 원인이 아니라 조사 단서라고 안내

## 만들지 않는 것

- Dockerfile, k8s YAML, Terraform 등 배포 소스 → 이후 브랜치(`infra/dashboard-deploy`, `infra/platform/dashboard/`)
- Athena 실조회 함수 → Gold A·Gold B 테이블이 만들어진 뒤 별도 작업
- 로그인 공급자(OIDC) 연결과 실제 이메일→Role 표 → 배포 구성 때 EKS 담당자와 정함
- 리뷰 원문 목록, LLM 요약, 키워드·벡터 검색 → 노션에서 "조사 편의 기능으로 검토" 단계
- 재처리 승인 화면 (승인은 별도 담당 영역)
- 실제 리뷰 원문·이메일·계정 정보를 코드나 Git에 넣는 것

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. 노션 문서의 컬럼 이름으로 `data.py` 더미 생성 함수를 만든다
3. 화면을 Role별로 만들고 `app.py`에서 메뉴를 구성한다
4. "완료 확인"을 실행하고 결과 보고

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [ ] `cd dashboard && ruff check . && ruff format --check .`
- [ ] `AUTH_MODE=local`로 테스트 계정 3개 로그인·로그아웃, 잘못된 비밀번호 거부
- [ ] Role 조합별(`product`, `data`, 둘 다, 없음)로 앱을 열어 오류가 없고, 메뉴와 접근 거부가 의도대로인지 (Streamlit `AppTest`)
- [ ] 모든 화면 파일을 따로 실행해 예외가 없는지
- [ ] 로컬에서 `streamlit run app.py`로 실제로 열어 화면이 보이는지 (사람이 확인)
- [ ] 사용하는 pandas 최소 버전(2.x)과 최신(3.x)에서 모두 동작하는지

## README 갱신

- `dashboard/README.md` (화면 표, 로컬 실행, 배포 시 정할 것)
- `docs/BRANCHES.md` (영역 표에 `dashboard` 추가, 브랜치 대장에 한 줄)

## 작업 결과 (머지 전에 작성한다. 사람과 AI가 나중에 이 브랜치가 무엇을 했는지 읽는 곳이다)

- **한 줄 요약:** Role 2개(상품 관리, 데이터 관리), 화면 10개를 가진 Streamlit 대시보드 골격. 데이터는 더미이며 실데이터가 없으면 더미로 대체한다.
- **무엇을 만들었나:** `dashboard/` 아래 `app.py`, `auth.py`, `data.py`, `ui.py`, `pages_product/`(5), `pages_data/`(5), `requirements.txt`, `pyproject.toml`(ruff 줄 길이 100), `README.md`
- **왜 그렇게 했나:** Role이 2개이고 구분이 화면 단위라 Streamlit으로 충분하다고 판단했다(Superset은 구성요소가 많아 노드 1대 클러스터에 부담). 화면은 노션 Gold A/B 설계의 테이블·컬럼 이름 그대로 만들어 실연결 때 `data.py`만 바꾸면 되게 했다.
- **입력과 출력:** 입력은 환경변수 `AUTH_MODE`(dev/local/oidc), `LOCAL_ACCOUNTS_FILE`, `ROLES_JSON`(이메일→Role), `DATA_SOURCE`(auto/dummy). 출력은 웹 화면(8501 포트). 다른 영역과의 약속: Gold A/B 테이블과 컬럼 이름은 노션 설계를 따른다.
- **확인한 결과:** (머지 전에 "완료 확인" 실행 결과로 채운다. 세션 중 확인: ruff check/format 통과, Role 조합 4가지 오류 없음, 화면 10개 개별 실행 오류 없음, pandas 2.2.3·3.0.6 모두 통과. PC에서 `streamlit run`으로 직접 연 확인은 사람이 한다.)
- **알려진 한계·남은 일:**
  - `gold_b.anomaly` 컬럼은 탐지 담당이 정의하는 표라 임시다. 확정되면 `data.get_anomalies()`를 맞춘다.
  - 상품 관리 Role의 "관련 장애"에 Gold B 장애 기록이 보인다(노션: Gold A가 Gold B 장애 기록을 함께 조회). 이 정도 노출을 허용할지 확인이 필요하다.
  - Athena 실조회(`data._REAL`), 로그인 공급자 연결, 배포(`infra/platform/dashboard/`)는 다음 브랜치.
  - 리뷰 원문 목록과 LLM 요약은 원문 조회 방식이 정해지면 추가한다. 원문은 내부용이라 외부 서비스에 올리지 않는다.
