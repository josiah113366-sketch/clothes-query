# 작업 지시서: api/mvp

> 상태: 검토 대기(EKS 적용 완료, 2026-10-21) · 브랜치: `api/mvp` (분기 기준: `sim/cdc-orders`. cdc-orders가 2026-10-21 `main`에 merge commit으로 머지되어 PR base는 **`main`**) · 설계: `docs/design/api.md`(`docs/api-design` PR) · 이전 작업: `sim/cdc-orders`, `docs/api-design` · 다음 작업: `sim/ecs-image`, `sim/console`

## 목표

**업무 API(WAS, FastAPI)를 만들어 EKS에 띄우고, 시뮬레이터가 RDS·Kafka 대신 이 API로 쓰고 읽게 바꾼다.**

이 브랜치가 끝나면:

```
시뮬레이터(로컬 또는 이후 ECS) ─HTTP─▶ 내부 ALB ─▶ WAS(api namespace, Pod 1) ─▶ RDS postgres DB
                                                                             └─▶ Kafka clickstream
RDS ─(Debezium, 기존)─▶ Kafka ─▶ S3 bronze/   ← 그대로
```

- `sim member live`와 `sim behavior live`가 `--backend api`로 돌면 **DB 계정 없이** API만 부른다. 기존 `--backend db`(로컬 직접 쓰기)는 그대로 남긴다.
- 클릭이 API를 거쳐 `clickstream`에 들어가고 S3 Sink가 `bronze/clickstream/`에 쌓는다(이 브랜치에서 처음 실제로 흐른다).
- ECS 배포는 하지 않는다(→ `sim/ecs-image`). 이 브랜치에서는 **로컬 시뮬레이터 → `kubectl port-forward` → EKS의 API**로 끝까지 확인한다.

이 지시서는 **자기 완결형**이다. 설계 문서(`docs/design/api.md`)가 이 브랜치에 없을 수 있으므로(별도 PR) 필요한 결정은 아래에 옮겨 적었다. 어긋나면 추측하지 말고 묻는다.

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- **한 브랜치에 여러 영역**: `api/`(새 폴더), `simulator/`, `infra/platform/kafka/`(values 한두 줄), `docs/`. "PR 하나에 한 영역"의 예외이며 PR 설명에 적는다(2026-10-20 사용자 결정: 브랜치 수를 줄인다).
- **`sim/cdc-orders` 위에서 시작했다.** Kafka values(`cdc-orders-values.yaml`)가 그 브랜치에만 있었다. cdc-orders는 2026-10-21 `main`에 머지됐다(merge commit, PR #32). 그래서 rebase 없이 PR base를 `main`으로 연다.
- **역할**
  - **Claude**: 코드(`api/`, `simulator/`), Dockerfile, Helm chart, SQL, values, 테스트, 문서. 로컬 Docker 검증과 정적 검사. 커밋까지.
  - **사용자**: 이미지 빌드·ECR push, DB SQL 실행(DBeaver), Secrets Manager, `kubectl`/`helm` 적용, port-forward 시험. Claude는 **명령과 순서**만 준다. push·PR도 사용자.
- Terraform 변경은 **없다**(ECR `clothes-query-dev/was` 재사용, RDS SG는 cdc-orders에서 연 EKS → 5432 그대로, ALB는 Ingress로 Auto Mode가 생성).
- 커밋 메시지: `<타입>(api/mvp): <한국어 요약>`. 타입은 `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `api/mvp`이고 `sim/cdc-orders`의 끝(`022e2a5` 또는 그 이후)에서 갈라졌는지, `docs/api-design` 커밋이 **섞이지 않았는지** 확인한다.
- `simulator/`의 `ruff`, `pytest`가 지금 통과하는지 확인한다(기준선).
- 로컬 Docker(Postgres, Kafka 프로필)가 뜨는지 확인한다.

## 결정된 사항 (설계 문서에서 옮김, 2026-10-20 사용자)

| 항목 | 결정 |
|---|---|
| 기술 | **FastAPI**(Python 3.12), EKS namespace **`api`**, Pod **1개** |
| 책임 | **얇은 API**: 확률·배속·폭주, **ID, 시각, 결제 결과는 시뮬레이터가 정해 보낸다.** API는 검증하고 저장·발행만 한다 |
| 목록 읽기 | 시뮬레이터는 회원·상품 목록을 **API로** 읽는다. 상품은 시작 때 한 번, 회원은 시작 때 전체 + **5초마다 변경분** |
| 회원 확인 | 주문 API는 회원이 `ACTIVE`인지 확인한다(아니면 409) |
| 노출 | **내부 ALB, HTTP 80**, 인증 없음. 처음엔 VPC 대역만 허용 |
| 배포 | **Helm**. 기존 `apps` 스택은 쓰지 않는다. 이미지는 ECR **`clothes-query-dev/was`**(IMMUTABLE) |
| Kafka | KafkaUser **`api`**(`clickstream` 쓰기만). 인증서는 `kafka` → `api` namespace로 **복사** |
| DB | 앱 전용 계정(`clothes_app`). 업무 DB는 RDS **`postgres`** |
| 데이터 오염 주입 | 컨트롤러가 DB에 직접(이 브랜치에서 바꾸지 않는다) |

## 기본값 (지시서가 정한 값. 바꾸려면 사용자에게 알린다)

| 항목 | 기본값 | 이유 |
|---|---|---|
| 폴더 | `api/` (`pyproject.toml`, `src/clothes_api/`, `tests/`, `Dockerfile`, `deploy/chart/`, `deploy/sql/`, `README.md`, `CLAUDE.md`) | 영역 `api` = 폴더 `api/` |
| 의존성 | `fastapi`, `uvicorn[standard]`, `pydantic`, `psycopg[binary,pool]`, `confluent-kafka`, `prometheus-client` / 개발 `pytest`, `httpx`, `ruff` | 시뮬레이터와 같은 드라이버(psycopg v3, confluent-kafka) |
| DB 접근 | 동기 `psycopg_pool.ConnectionPool`(min 1, max 10), FastAPI 동기 엔드포인트(스레드풀). 풀에서 **2초** 안에 연결을 못 받으면 **503 `DB_BUSY`** | 부하가 작다(burst 주문 API 약 6/초). 단순함 우선 |
| 시각 | 요청의 시각은 **시간대가 있는 ISO 8601**만 받는다(없으면 422). 저장은 `timestamptz`, 응답·Kafka는 UTC `…Z` | Bronze UTC 규칙 |
| 멱등 | 같은 ID 재요청: 저장된 내용과 **같으면 200**, **다르면 409 `ID_CONFLICT`** | 재시도 안전 + 버그 노출 |
| 클릭 묶음 | 한 요청 최대 **500건**. 넘으면 413. 각 이벤트를 키 `session_id`로 한 건씩 발행. 응답 202 `{accepted, failed}` | 설계 |
| 클릭 발행 실패 | **버리고 센다**(지표). 시작 때 브로커에 못 닿으면 `/readyz` 503, `/healthz`는 200 | 주문 흐름을 막지 않는다 |
| 회원 변경분 커서 | 불투명 문자열(base64 JSON `{created_at, member_id}`). 서버는 **커서보다 10초 앞부터** 겹쳐 돌려준다. 한 번에 최대 **5,000건**, 더 있으면 `has_more: true` | 늦게 커밋된 행을 놓치지 않는다. 시뮬레이터가 중복 제거 |
| 목록 페이지 | `GET /v1/members/active`, `GET /v1/catalog`: 페이지당 **10,000건**, 커서 페이지 | 10만 명을 한 번에 보내지 않는다 |
| 로그 | stdout JSON 한 줄(`request_id`, `method`, `route`(경로 템플릿), `status`, `ms`). **요청 본문·PII를 남기지 않는다** | 보안 |
| 지표 | `api_requests_total{route,method,status}`, `api_request_seconds{route}`(히스토그램), `api_db_pool_*`, `api_db_errors_total{kind}`, `api_kafka_produced_total{result}`, `api_payments_total{status}` | 관제·콘솔 |
| 시뮬레이터 백엔드 | 새 옵션 `--backend db|api`(환경 변수 `SIM_BACKEND`, 기본 `db`), `SIM_API_URL` | 로컬 직접 쓰기와 기존 테스트를 깨지 않는다 |
| 시뮬레이터 재시도 | 주문·결제·상태·가입: 연결 실패·5xx·503에 **0.5 → 1 → 2 → … 최대 30초** 간격으로 계속 재시도(ID 고정이라 중복 없음). 422는 실패로 센다 | 설계 안전장치 |
| 클릭 전송 | 시뮬레이터가 **1초 또는 500건**마다 묶어 보낸다. 실패하면 그 묶음은 버리고 센다(경고 1회) | 지금 `KafkaClickSink` 정책과 같다 |
| 이미지 태그 | ECR가 IMMUTABLE이므로 **git 짧은 SHA**(`api-<sha>`), Helm에는 **digest**로 넣는다 | 덮어쓰기 불가 |
| 리소스·노드 | **API 전용 노드 풀**(`clothes-query-dev-api`, t3a.medium, taint, CPU 한도 2 = 최대 1대). requests 500m/256Mi, limits 1500m/1Gi | 2026-10-21 사용자 결정: 노드 한 대에 Kafka·Connect·UI·API를 다 올리지 않는다. 기존 풀은 바꾸지 않아 Kafka 영향 없음. 같은 NodeClass라 RDS SG 규칙 그대로 |

## 만드는 것

### 1. API 앱 (`api/src/clothes_api/`)

엔드포인트(모두 `/v1`, JSON). 필드 이름은 DB 컬럼 그대로(`db/schema/001_member.sql`, `004_orders.sql`).

| 메서드·경로 | 동작 | 검증 | 응답 |
|---|---|---|---|
| `POST /v1/members` | `members` INSERT (`status=ACTIVE`, `withdrawn_at` 없음, `created_at`은 DB 기본값) | 성별·채널·연령대 값, 시간대 있는 `signup_at` | 201 / 200 같은 내용 / 409 `ID_CONFLICT` / **409 `PHONE_TAKEN`**(전화 UNIQUE 위반, 시뮬레이터가 번호를 다시 뽑는다) / 409 `EMAIL_TAKEN` / 422 |
| `GET /v1/members/signup-count?from=<시각>` | `SELECT count(*) FROM members WHERE signup_at >= from` | 시간대 있는 시각 | 200 `{count}` |
| `GET /v1/members/active?cursor=` | `ACTIVE` 회원 `member_id`, `member_id` 순 페이지 | – | 200 `{items, next_cursor, changes_cursor}` (`changes_cursor`는 첫 페이지 응답 시각 기준) |
| `GET /v1/members/changes?after=<커서>` | 커서(10초 겹침) 이후 `created_at` 순으로 가입 회원. 탈퇴는 아직 없으므로 `removed`는 항상 빈 목록 | 커서 형식 | 200 `{added, removed, next_cursor, has_more}` |
| `GET /v1/catalog?cursor=` | `product_variant`의 `article_id`, `price`, `article_id` 순 페이지 | – | 200 `{items, next_cursor}` |
| `POST /v1/orders` | `orders`(`status=PLACED`) + `order_items` **한 트랜잭션** | 회원 `ACTIVE`(아니면 409 `MEMBER_NOT_ACTIVE`), `total_amount` = Σ(수량×단가), 항목 1개 이상, 한 주문 안 `article_id` 중복 없음, 상품 존재 | 201 / 200 / 409 `ID_CONFLICT` / 409 `MEMBER_NOT_ACTIVE` / 422 |
| `POST /v1/orders/{order_id}/payments` | `payments` INSERT | 주문 존재(404), `amount` = 주문 총액, 상태·실패 코드 짝, `completed_at >= requested_at`, `(order_id, attempt_no)` 유일 | 201 / 200 / 404 / 409 `ID_CONFLICT` / 422 |
| `PATCH /v1/orders/{order_id}` | `UPDATE orders SET status, status_reason, updated_at` | 주문 존재, 상태·사유 짝, 허용된 전이(아래), `updated_at >= ordered_at`. **같은 상태로의 재요청은 200**(재시도 안전) | 200 / 404 / 409 `INVALID_TRANSITION` / 422 |
| `POST /v1/events/clicks` | 각 이벤트를 `clickstream`에 발행(키 `session_id`, 값은 6필드 JSON, 시각 `…Z`) | 최대 500건, `event_type` ∈ {view, cart_add}, 6필드 | 202 `{accepted, failed}` / 413 / 422 |
| `GET /healthz` | 프로세스 살아 있음 | – | 200 |
| `GET /readyz` | DB `SELECT 1` + Kafka 메타데이터 확인 | – | 200 / 503 |
| `GET /metrics` | Prometheus | – | 200 |

허용 전이: `PLACED → PAID | PAYMENT_FAILED | CANCELLED`, `PAID → SHIPPED | CANCELLED`, `SHIPPED → DELIVERED`, `DELIVERED → REFUNDED`. 2026-10-20 시뮬레이터 코드(`behavior/payment.py`의 `next_transition`, `behavior/runner.py`)와 같은 것을 확인했다. `CANCELLED`는 `USER_REQUEST`, `REFUNDED`는 `RETURN` 사유가 짝이다(`004_orders.sql`).

오류 응답 형식: `{"error": "<코드>", "detail": "<PII 없는 설명>"}`. DB 오류는 sqlstate·제약 이름으로만 분류한다.

모듈 구성(제안): `main.py`(앱·미들웨어·지표), `config.py`(환경 변수), `db.py`(풀), `kafka.py`(프로듀서, 시뮬레이터 `common/kafka.py`의 TLS 환경 변수 방식과 같게), `schemas.py`(pydantic), `routes/members.py`, `routes/orders.py`, `routes/events.py`, `routes/health.py`, `errors.py`.

환경 변수: `DATABASE_URL`(또는 `PGHOST`·`PGDATABASE`·`PGUSER`·`PGPASSWORD`·`PGSSLMODE`·`PGSSLROOTCERT` 조합), `KAFKA_BOOTSTRAP`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SSL_CA_FILE`, `KAFKA_SSL_CERT_FILE`, `KAFKA_SSL_KEY_FILE`, `CLICK_TOPIC`(기본 `clickstream`), `LOG_LEVEL`. **접속 정보는 출력하지 않는다.**

### 2. 테스트 (`api/tests/`)

- 단위(DB 없음): 스키마 검증(값·짝·시간대), 전이 규칙, 커서 인코딩·10초 겹침, 멱등 비교, 오류 코드 매핑, 클릭 묶음 상한, 로그에 본문·PII가 없음
- 통합(`@pytest.mark.integration`, 로컬 Docker Postgres + Kafka): 각 엔드포인트 정상·중복·충돌·404·409, 주문 트랜잭션 원자성(항목 실패 시 주문도 없음), 클릭이 `clickstream`에 키·값 그대로 들어감, `/readyz`가 DB·Kafka가 끊기면 503

### 3. 이미지 (`api/Dockerfile`)

- 베이스 `python:3.12-slim`을 **digest로 고정**, 비root 사용자, `uvicorn clothes_api.main:app --host 0.0.0.0 --port 8000`, 비밀값 없음
- RDS CA 번들은 이미지에 넣지 않고 Secret `rds-ca`(아래)로 붙인다

### 4. DB 앱 계정 (`api/deploy/sql/app-account.sql`, 사용자가 마스터로 `postgres` DB에서 실행)

- `CREATE ROLE clothes_app LOGIN … CONNECTION LIMIT 15` (풀 최대 10 + 재시작 겹침 여유)
- `members` INSERT·SELECT, `orders` INSERT·UPDATE·SELECT, `order_items`·`payments` INSERT·SELECT, `product_variant` SELECT. `members_archive`·`product_design` 권한 없음
- DBeaver용(비밀번호 자리 표시) 안내와 되돌리기 SQL을 함께 둔다

### 5. Helm chart (`api/deploy/chart/`)

- `Deployment`(replica 1, 리소스, `runAsNonRoot`, 읽기 전용 루트, `/healthz` liveness, `/readyz` readiness, 종료 유예), `Service`(ClusterIP 80 → 8000)
- `IngressClassParams`(`scheme: internal`) + `IngressClass`(`controller: eks.amazonaws.com/alb`) + `Ingress`(HTTP 80, 헬스체크 `/readyz`, **인바운드 VPC 대역만**). `infra/modules/apps/main.tf`의 Auto Mode 예시를 internal·HTTP로 바꿔 쓴다
- Secret 참조만: `api-database`(DB 접속), `rds-ca`(`bundle.pem`), `kafka-client`(`user.crt`, `user.key`, `ca.crt`). 값은 chart에 없다
- values: 이미지(digest 필수), 리소스, 허용 CIDR, Kafka bootstrap(`clothes-query-dev-kafka-kafka-bootstrap.kafka.svc:9093`)
- 정적 검사: `helm lint`, `helm template` 렌더 확인(테스트에서 실행, 기존 `infra/checks/install_helm.py`로 받은 Helm 사용)

### 6. Kafka values (`infra/platform/kafka/cdc-orders-values.yaml`)

- `clients`에 `{name: api, produceTopics: [clickstream], consumeTopics: [], consumerGroups: []}`
- `kafka.clientNamespaces: [api]`
- `verify/check.py`의 업무 values 검사에 이 두 가지를 반영한다(브로커 NodePool 불변 검사는 그대로 통과해야 한다)

### 7. 인증서·Secret 절차 (`api/README.md`)

- Secrets Manager `clothes-query-dev-api-db`(도쿄) 생성 → K8s Secret `api-database`
- `rds-ca`를 `api` namespace에도 만든다
- **Kafka 인증서 복사**: `kafka`의 Secret `api`(`user.crt`, `user.key`)와 `clothes-query-dev-kafka-cluster-ca-cert`(`ca.crt`)에서 키만 꺼내 `api` namespace의 `kafka-client`로 만든다. 값은 출력하지 않고, 한글 없는 레포 밖 임시 경로와 `[IO.File]::WriteAllBytes`를 쓴다(cdc-orders에서 겪은 PowerShell 함정 반영). **만료일 확인 명령**과 "갱신되면 다시 복사" 안내를 둔다

### 8. 시뮬레이터 연동 (`simulator/`)

- `common/api_client.py`: `SIM_API_URL` 기반 HTTP 클라이언트(표준 라이브러리 `urllib` 또는 `httpx` 중 의존성 추가를 최소화하는 쪽, 사용자에게 알린다), 재시도·백오프, 오류를 `ApiUnavailable`(일시)·`ApiRejected`(422 등)로 나눈다. **접속 주소 외 정보와 본문을 출력하지 않는다**
- `member/live.py`: `ApiStore`(`MemberStore` 구현). `count_since` → `signup-count`, `insert` → `POST /v1/members`. **`PHONE_TAKEN`을 지금의 전화 UNIQUE 위반과 같게** 처리해 번호를 다시 뽑는다
- `behavior/sink.py` 옆에 `ApiOrderSink`(`OrderSink` 구현), `ApiClickSink`(`ClickSink` 구현, 1초·500건 묶음)
- `behavior/pool.py` 옆에 `ApiMemberSource`(전체 + 변경분, 중복 제거), `ApiCatalogSource`
- `behavior/runner.py`: 회원 목록 갱신을 **5초마다 변경분 반영**으로(백엔드 api일 때). `MEMBER_NOT_ACTIVE`면 그 회원을 목록에서 뺀다. 재연결·재시도 처리를 `ApiUnavailable`에도 적용한다
- CLI: `--backend db|api`(`SIM_BACKEND`), `api`일 때 `DATABASE_URL`을 요구하지 않는다. 시작 출력에 API 주소(호스트만)
- 기존 테스트는 **그대로 통과**해야 한다(`--backend db` 기본). API 백엔드는 가짜 서버(FastAPI `TestClient` 대신 `http.server` 또는 의존성 없는 방식)로 단위 테스트

### 9. 부하 측정

- 로컬 Docker로 API를 띄우고, 시뮬레이터를 `--backend api --mode burst --speed N`으로 돌려 **초당 약 200 요청**을 만든다(별도 부하 도구 없이 시뮬레이터로)
- `/metrics`에서 p95 응답 시간, 5xx 수, `DB_BUSY` 수를 보고한다. EKS Pod(500m 한도)에서 한 번 더 짧게 확인한다

## 만들지 않는 것

- ECS 배포, 시뮬레이터 이미지 변경(→ `sim/ecs-image`), 웹 관리 화면(→ `sim/console`)
- 탈퇴 API, 리뷰 API, 인증(API 키)
- 컨트롤러의 데이터 오염 경로 변경(지금처럼 DB 직접)
- 지표 수집 서버(Prometheus 서버, Grafana), HPA
- Terraform 변경, 기존 `apps` 스택 사용
- `db/schema/` 변경

## 작업 순서

1. 시작 전 확인 → **계획을 먼저 제시해 사용자 확인을 받는다**
2. 이 지시서와 `docs/BRANCHES.md`(`### api` 구역에 한 줄) → 커밋 `docs(api/mvp): 브랜치 등록과 작업 지시서 추가`
3. API 뼈대(설정, 풀, 헬스, 지표, 로그) + 단위 테스트 → `feat(api/mvp): FastAPI 뼈대와 헬스·지표`
4. 회원·상품 엔드포인트 → `feat(api/mvp): 회원·상품 API`
5. 주문·결제·상태 엔드포인트 → `feat(api/mvp): 주문·결제·상태 API`
6. 클릭 엔드포인트(Kafka) → `feat(api/mvp): 클릭 이벤트 API`
7. 통합 테스트 → `test(api/mvp): 로컬 Postgres·Kafka 통합 테스트`
8. Dockerfile, SQL, Helm chart, Kafka values, 검사 → `feat(api/mvp): 이미지·DB 계정·Helm chart·Kafka 계정`
9. 시뮬레이터 API 백엔드 + 테스트 → `feat(api/mvp): 시뮬레이터 API 백엔드`
10. 로컬 끝-끝·부하 측정 → 결과 보고
11. README(`api/README.md`, `api/CLAUDE.md`, `simulator/README.md`) → `docs(api/mvp): README 갱신`
12. 사용자가 EKS에 적용(명령 제공) → "완료 확인" 함께 진행
13. `작업 결과` 작성, 상태 `완료` → `docs(api/mvp): 작업 결과 기록`

## 완료 확인

**로컬 (Claude가 실행)**
- [ ] `api/`: `ruff check`, `ruff format --check`, `pytest`(단위), `pytest -m integration`(로컬 Docker) 통과
- [ ] `simulator/`: 기존 테스트 **그대로 통과** + API 백엔드 테스트 통과
- [ ] `helm lint`·`helm template` 통과, Kafka `verify/check.py` 통과(브로커 NodePool 불변)
- [ ] 로컬 끝-끝: Docker Postgres·Kafka + API 컨테이너 + `sim member live --backend api` + `sim behavior live --backend api` 짧게 실행 → DB 행 수와 시뮬레이터 요약·API 지표가 맞고, `clickstream`에 클릭이 들어감
- [ ] 멱등: 같은 주문을 두 번 보내면 200, 내용을 바꾸면 409. 탈퇴 상태로 바꾼 회원으로 주문하면 409
- [ ] 부하: burst 상당(초당 약 200 요청)에서 5xx 0, p95 보고
- [ ] 로그·출력에 PII·접속 정보 없음(`grep`)

**EKS (사용자가 실행, 결과를 붙여 준다)**
- [ ] `helm upgrade cq-kafka`: 바뀌는 것은 KafkaUser `api` 추가와 브로커 허용 대상(`api` namespace)뿐
- [ ] DB 계정·Secret·인증서 복사 완료(값 출력 없음), `api` Pod Ready, 재시작 0
- [ ] **내부 ALB 생성**(`kubectl get ingress -n api`의 주소가 `internal-…`), 대상 healthy
- [ ] VPC 안에서 `/readyz` 200 (임시 Pod에서 ALB 주소로 요청)
- [ ] 로컬 시뮬레이터 → `kubectl port-forward -n api svc/api` → 실제 RDS·Kafka: 짧게 돌려(예: 방문 300) 주문이 RDS에 들어가고 **CDC → `bronze/orders` 등**까지, 클릭이 **`bronze/clickstream/`**까지 가는지 확인
- [ ] 노드 2대(기존 풀 1 + API 전용 풀 1), Kafka Pod 재시작 0, API Pod 자원 사용량 보고

## README 갱신

- `api/README.md`: 목적, 엔드포인트 표, 로컬 실행, 테스트, 이미지 빌드·push(IMMUTABLE 태그), 배포 순서(DB 계정 → Secret → 인증서 복사 → Kafka values → Helm), 인증서 갱신, 되돌리기
- `api/CLAUDE.md`: 폴더 규칙(PII 로그 금지, 접속 정보 출력 금지, 결정만 구현)
- `simulator/README.md`: `--backend api`, `SIM_API_URL`, 재시도·묶음 정책

## 막히면

- 이 지시서·설계·코드가 어긋나면 **추측하지 말고 묻는다**(특히 상태 전이 표).
- 새 의존성(시뮬레이터에 `httpx` 등)이 필요하면 이유를 먼저 설명한다.
- `helm upgrade cq-kafka` diff에 `api` KafkaUser·허용 대상 말고 다른 변경(브로커, NodePool)이 보이면 멈춘다.
- 노드가 늘어나면(`kubectl get nodes` 2대) 바로 알린다.
- 내부 ALB가 안 생기거나 public으로 생기면 적용을 멈추고 알린다.

## 작업 결과

### 지금까지 만든 것 (커밋됨)

- `api/`: FastAPI 앱(`src/clothes_api/`), 단위 테스트 32개, chart 렌더 테스트 5개, 통합 테스트 6개(로컬 Docker 필요), Dockerfile(베이스 digest 고정, 비root), `deploy/sql/app-account.sql`, `deploy/chart/`(Deployment·Service·내부 ALB), `README.md`, `CLAUDE.md`
- `infra/platform/kafka/cdc-orders-values.yaml`: KafkaUser `api`(`clickstream` 쓰기만), `clientNamespaces: [api]`. `verify/check.py`에 ACL·허용 대상 검사 추가
- `simulator/`: `common/api.py`(urllib 클라이언트, 오류 3종), `member/api_store.py`, `behavior/api_sink.py`, CLI `--backend db|api`, `--click-sink api`, 실행기의 API 오류 처리(재시도, 비활성 회원 제외), 회원 목록 변경분 반영(5초), 테스트 14개
- `.gitignore`: `api/**/*.local.yaml`. 루트 `CLAUDE.md` 폴더 표에 `api/`

### 지시서와 다르게 한 것

- **결제 금액 = 주문 총액 검사를 뺐다.** 컨트롤러의 데이터 오염(`ORDER_TOTAL_MISMATCH`)이 DB에서 총액을 바꾸면, 그 뒤 시뮬레이터의 정상 결제가 API에서 거절돼 실험이 달라진다. DB에도 그런 제약은 없다
- **`404 MEMBER_NOT_FOUND`** 추가(주문의 회원이 아예 없을 때)
- **`--click-sink api`** 추가: `--backend api`와 따로 고를 수 있게 했다(클릭만 API로 보내기 등)
- **API 전용 노드 풀**(2026-10-21 사용자 결정): 설계 문서 9절의 "replica 1개를 기존 노드에"를 바꿨다. chart가 Karpenter NodePool(t3a.medium, taint `clothes-query/dedicated=api`, CPU 한도 2)을 만들고, 기존 NodeClass를 같이 쓴다. Terraform(`compute` 스택)은 바꾸지 않았다(비공개 입력이 이 PC에 없음). 비용은 t3a.medium 1대분(도쿄 온디맨드 대략 월 35달러 + Auto Mode 관리비). 리소스 requests 500m / limits 1500m
- HTTP 클라이언트는 **표준 라이브러리 `urllib`**(시뮬레이터 새 의존성 없음, 사용자 확인)
- API dev 의존성에 `pyyaml`(chart 렌더 테스트)
- **DB 앱 계정에 `members` `UPDATE (status)` 추가**(2026-10-21 사용자 결정): 설계 문서의 `members` INSERT·SELECT와 다르다. 주문 생성이 회원 행을 `SELECT … FOR SHARE`로 잠그는데, PostgreSQL은 잠금 SELECT에 UPDATE 권한(컬럼 하나 이상)을 요구한다. EKS 첫 실행에서 주문만 500(권한 거부)이 나서 찾았다. `status`만으로는 탈퇴로 못 바꾸고(`withdrawn_at` 권한 없음 + CHECK), 잠금은 CDC 이벤트를 만들지 않는다. 대안(잠금을 빼고 재배포)은 버렸다
- **Pod `fsGroup: 10001` 추가**: Secret 볼륨 파일이 root 소유라 비root(10001)가 `kafka-client`(0400)를 못 읽어 시작하자마자 죽었다(`ssl.ca.location failed`). fsGroup으로 그룹 읽기(0440)가 된다. chart 테스트에 검사 추가
- `api/README.md`: 새 PowerShell 창마다 관리자 kubeconfig, 비교 파일은 `Set-Content -Encoding utf8`(5.1의 `>`는 UTF-16), 시뮬레이터는 `--duration`으로. `simulator/README.md` 예시도 `--max-visits 300` → `--visits-daily 20000 --duration 120`

### 확인한 결과

- `api/`: `ruff` 통과, `pytest` 37 통과(단위 32 + chart 5), **통합 6 통과**(2026-10-21, 로컬 Docker Postgres 16·Kafka. 임시 스키마·임시 토픽은 모두 지워짐)
- `simulator/`: `ruff` 통과, `pytest` **412 통과**(기존 398 그대로 + 새 14)
- Kafka `verify/check.py` 통과(브로커 NodePool 불변, `api` ACL = `clickstream` Write·Describe + IdempotentWrite)
- **계약 확인(일회성, 커밋 안 함)**: 실제 FastAPI 앱(가짜 저장소)에 실제 시뮬레이터 실행기를 붙여 시뮬레이터 시각 2일 실행 → 방문 90,715, 주문 4,119 = API 주문 4,119, 결제 4,293 = 4,293, 상태 변경 12,040건 모두 200, 클릭 490,475 = 490,475(묶음 981번), `member live` 가입 50 = 50. **4xx·5xx 0건**

- **로컬 끝-끝**(실제 uvicorn API + 로컬 Postgres·Kafka + 시뮬레이터 `--backend api`): `member live` 가입 20 = DB +20(시작 인덱스 3,690으로 이어짐). `behavior live`(배속 60, 2분) 주문 117 = DB 117, 결제 117(SUCCESS 112·FAILED 5) = DB, 항목 421·금액 불일치 0, 상태 PAID 110·CANCELLED 3·PAYMENT_FAILED 4, 클릭 15,361 = Kafka `clickstream` +15,361. API 오류 응답 0, 시각 UTC 저장
- **부하**: burst·배속 30 시뮬레이터 1개 → 초당 46 요청(클릭 이벤트 약 1,770/초), 전부 2xx, p95 ≤ 50ms. 4개 동시 → 초당 76 요청, 전부 2xx, p95 ≤ 250ms(이때는 시뮬레이터 CPU가 먼저 한계). **API 직접 동시 요청**(이미 있는 주문에 같은 상태 PATCH, 트랜잭션·행 잠금 포함): 동시 10 → **초당 208, p95 77ms**, 동시 30 → 초당 182, p95 267ms, 모두 200. 이 PC에서 프로세스 1개 한계는 초당 약 200이고, 실제 burst(초당 약 7)의 약 30배 여유. EKS Pod(CPU 0.5코어)는 더 낮을 수 있어 배포 후 다시 본다
- 확인 뒤 로컬 DB 정리: 주문 2,300·항목 7,807·결제 2,346·새 회원 20 삭제 → 회원 103,690, 주문 3테이블 0(시작 전과 같음). 로컬 `clickstream` 토픽에는 시험 클릭이 남음(33 → 306,943건, 72시간 보관)
- 발견: 시뮬레이터 시작 모드가 기존 control 파일(`.local/control.json`)의 `normal`로 덮어써진다(설계대로의 동작). 부하 측정은 비어 있는 control 파일 경로로 했다
- 참고: `api_kafka_produced_total`은 전송 완료 알림을 받을 때 세므로 마지막 묶음만큼 실제 발행 수보다 잠깐 적다(토픽에는 모두 들어감)

- **EKS 적용**(2026-10-21, 사용자가 `api/README.md` 1~7단계 실행):
  - `helm upgrade cq-kafka` 전 diff: KafkaUser `api` 추가와 listener 허용 대상 `api` namespace뿐. 적용 후 Kafka Pod 재시작 0, Secret `api` 생성. 사용자 인증서 만료 2027-10-21
  - Secret `api-database`(password 32 bytes), `rds-ca`, `kafka-client` 생성(값 출력 없음)
  - 이미지 `clothes-query-dev/was:api-87cd0a9`(digest로 배포). 첫 설치는 위 fsGroup 문제로 CrashLoopBackOff → 수정 후 revision 2에서 Pod Ready, 재시작 0
  - 노드 2대: 기존 `clothes-query-dev-compute`(t3a.large) + `clothes-query-dev-api`(t3a.medium, Pod 생성 후 약 1분에 뜸)
  - Ingress 주소 `internal-…`(내부 ALB). VPC 안 임시 Pod에서 ALB로 `/readyz`는 사용자 확인 대기
  - 로컬 시뮬레이터 → port-forward → EKS API: `member live` 가입 408. `behavior live`(배속 60, 하루 방문 20,000, 2분) 방문 2,148, 주문 90, 결제 95(성공 86·실패 9), 상태 PAID 86·PAYMENT_FAILED 2·CANCELLED 1, 클릭 11,485 전송 실패 0, 재연결 0(위 권한 추가 뒤). `남은 큐`는 아직 때가 안 된 배송 등 예약
  - S3 bronze(2026-10-21, UTC `day=21`): `clickstream`, `orders`, `payments`, `members-events`에 실행 시각 파일 생성(15분 단위). `order-items`는 사용자 확인 대기
  - 확인 못 한 것: API Pod 자원 사용량(`kubectl top`), EKS에서의 부하 측정

### 다음 할 일

- `docs/api-design` PR 먼저 머지(이 브랜치의 README·CLAUDE.md가 `docs/design/api.md`를 가리킨다). 설계 문서 권한 줄(`members` UPDATE(status))을 맞출지 결정
- 통합 테스트를 `clothes_app`과 같은 권한의 계정으로 돌리기(이번 권한 문제는 테이블 소유자로 돌아서 로컬에서 못 잡았다)
- 비밀값 교체 절차: DB 앱 비밀번호(Secrets Manager → K8s Secret 복사본), Kafka 인증서 갱신(2027-09 무렵) 시 `kafka-client` 재복사. CDC 비밀번호 교체 보류와 함께 정리
- `sim/ecs-image`: 시뮬레이터가 내부 ALB로 호출, `inboundCIDRs`를 ECS 대역으로 좁히기. 클릭도 API로 가므로 ECS→Kafka 경로는 필요 없어졌다
- CI/CD(`ci` 영역): 이미지 빌드·push·배포 자동화(OIDC, EKS 엔드포인트 접근 방식, 승인 절차). 지금은 README 5~6단계 수동
