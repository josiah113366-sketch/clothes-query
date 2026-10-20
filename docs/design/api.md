# 업무 API(WAS) 설계

상태: 결정(구조·범위) / 제안(세부 수치) · 2026-10-20 · 담당: WAS 담당(사용자) · 관련: `sim/cdc-orders`(PR 대기), `simulator/`

이 문서의 상태 표현은 **결정 / 제안 / 미정**이다(루트 `CLAUDE.md`). **결정**만 구현한다. **제안**과 **미정**은 사용자가 고른 뒤 결정으로 옮기고, 그다음 작업 지시서(`docs/tasks/api-*.md`)를 쓴다.

## 1. 왜 만드나

지금 시뮬레이터는 RDS에 **직접** 쓴다(`DbOrderSink`, 회원 `INSERT`). API로 바꿀 자리만 있다(`OrderSink`, `ClickSink` 인터페이스, 예정 이름 `ApiOrderSink`, `ApiClickSink`). 이대로 ECS에 올리면 "컨테이너에서 RDS에 직접 넣기"와 다르지 않다.

API를 거치면:

1. **실제 쇼핑몰과 같은 구조**가 된다(클라이언트 → API → DB).
2. **클릭 경로가 단순해진다.** WAS가 EKS 안에서 `clickstream`에 발행하면 지금 Kafka 내부 mTLS 리스너를 그대로 쓴다. ECS → Kafka 외부 리스너, 인증서 전달, SG 작업이 필요 없다.
3. **관제 지표가 생긴다.** API 응답 시간, 에러율, 결제 실패율 같은 지표가 AI 관제 에이전트의 단서가 된다.
4. **CDC와 Bronze는 그대로다.** Debezium은 누가 썼는지와 상관없이 DB 변경을 읽는다.

## 2. 결정된 것 (2026-10-20 사용자)

| 항목 | 결정 |
|---|---|
| 순서 | 시뮬레이터 ECS 배포(`sim/ecs-image`)보다 **API를 먼저** 만든다 |
| 담당 | WAS는 **사용자**가 만든다 |
| 기술 | **FastAPI** (Python) |
| 실행 위치 | **EKS에 새 Pod**로 띄운다 |
| 리뷰 시뮬레이터 | 리뷰 시뮬레이터 ECS와는 **따로** 운영한다 (이 API를 쓰지 않는다) |
| 웹 관리 화면 | 나중에 ECS에서 돌린다 (이 문서 범위 밖, `sim/console`) |
| 책임 나누기 (Q1) | **A. 얇은 API.** 확률·배속·폭주, ID, 시각, 결제 결과는 모두 ECS 시뮬레이터가 정하고, API는 검증하고 저장만 한다 (4절) |
| namespace (Q3) | 새 namespace **`api`**. Kafka 인증서는 `kafka` namespace에서 복사하는 절차를 만든다 (7절) |
| 인증 (Q4) | **없음** (MVP). 내부 ALB와 SG로만 막는다 (10절) |
| 데이터 오염 주입 (Q5) | 컨트롤러가 **DB에 직접** 쓴다(지금 유지). 오염 전용 DB 계정을 따로 둔다 (11절) |
| 배포 도구 (Q6) | **Helm** (9절) |
| replica (Q7) | **1개**로 시작한다. 부하는 ECS 시뮬레이터가 정하고 API는 버티기만 한다. burst 부하는 `api/mvp`에서 측정해 늘릴지 정한다 (9절) |
| 목록 읽기 (Q2) | 시뮬레이터는 회원·상품 목록을 **API로** 읽는다(DB 계정 없음). 상품은 시작 때 한 번, 회원은 시작 때 전체 한 번 + **5초마다 변경분**만. 주문 API는 회원이 `ACTIVE`인지 확인한다 (5절) |
| 노드 (2026-10-21) | **API 전용 노드 풀**에 띄운다. 노드 한 대에 Kafka·Connect·UI·API를 다 올리지 않는다. 기존 노드 풀(Kafka 등)은 바꾸지 않는다 (9절) |
| 기존 `apps` 스택 (Q8) | **쓰지 않는다.** 공개 HTTPS(도메인·인증서 필수)와 WEB이 묶여 있다. api Helm chart가 **내부 HTTP(80) ALB**를 만든다. ALB는 HTTPS가 필수가 아니다 (9절) |

## 3. 전체 구조 (결정)

```
ECS Fargate (시뮬레이터)                 EKS
 member live ──┐                    ┌──────────────────────────────┐
 behavior live ┴─HTTP─▶ 내부 ALB ──▶│ api namespace: WAS (FastAPI) │──▶ RDS postgres DB (members, orders, order_items, payments)
                 (VPC 안에서만)      │                              │──▶ Kafka clickstream (mTLS, KafkaUser api)
                                    └──────────────────────────────┘
 controller ──── 데이터 오염만 DB 직접 (전용 계정, Q5) ─────────────▶ RDS
 (모드·장애 신호는 시뮬레이터에 직접. 방식은 sim/console에서)
RDS ──(Debezium, 기존)──▶ Kafka members-events / orders / order-items / payments ──▶ S3 bronze/
```

- 외부(인터넷)에는 열지 않는다. ALB는 VPC 안에서만 닿는다.
- 기존 `infra/stacks/apps`의 Ingress는 **인터넷 공개 HTTPS**(도메인, 인증서 필요)용이라 이번 용도와 다르다. 2026-10-20 기준 AWS에 로드밸런서는 0개이고, EKS Auto Mode 로드밸런싱은 켜져 있어 Ingress를 만들면 ALB가 자동으로 생긴다.

## 4. 책임 나누기 — 무엇을 시뮬레이터가 정하고 무엇을 API가 정하나 (결정: A)

시뮬레이터는 지금 **ID, 시각, 결제 결과를 모두 스스로 정한다.**
- **ID**: 시드로 만든 UUID. 같은 시드면 같은 데이터가 나오고, 재실행 때 이미 있는 주문은 `23505`로 건너뛴다.
- **시각**: 배속(`--speed`)이 걸린 **시뮬레이터 시각**. 예를 들어 `ordered_at`, `updated_at`은 실제 UPDATE 시각이 아니라 예정된 시각이다.
- **결제 결과**: 시뮬레이터가 확률로 뽑는다. PG 장애 주입(`pg_extra_fail`)도 시뮬레이터 안에서 결과를 바꾼다.

| 선택지 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. 얇은 API (결정)** | 시뮬레이터가 ID, 시각, 결제 결과를 정해 보내고, API는 **검증하고 저장**한다. 클릭은 받아서 Kafka에 넘긴다 | 지금 시뮬레이터 동작(배속, 재현성, 장애 주입, 테스트 기준값)이 그대로 유지된다. 구현이 작다 | API에 "업무 로직"이 거의 없다 |
| B. 실제 API | API가 ID, 시각(서버 시각)을 정하고, WAS 안의 **가짜 PG**가 결제 결과를 정한다. PG 장애도 WAS에 주입한다 | 더 실제 같다. 장애가 API 지표(결제 API 실패율)로 자연스럽게 드러난다 | 배속을 쓰면 시각이 실제 시각과 어긋난다. 재현성과 기존 테스트 기준값이 깨진다. 장애 주입 경로를 새로 만들어야 한다 |
| C. 섞기 | ID와 시각은 시뮬레이터(A), **결제만** WAS의 가짜 PG(B) | 결제 장애가 API 쪽 지표로 드러난다 | 두 방식이 섞여 복잡하다. 결제 결과의 재현성이 깨진다 |

**결정: A** (2026-10-20). 이전 제안 근거: 지금 시뮬레이터, 컨트롤러, 테스트를 그대로 쓰면서 API 경로부터 만든다. 필요해지면 결제만 C로 옮길 수 있게 엔드포인트를 나눠 둔다.

## 5. 엔드포인트 (제안, 4절 A 기준)

모두 JSON, 경로 앞에 `/v1`. 시각은 **UTC ISO 8601(`…Z`)**. 금액은 정수(원).

| 메서드·경로 | 지금 시뮬레이터가 하는 일 | 내용 | 응답 |
|---|---|---|---|
| `POST /v1/members` | `member live`의 `INSERT INTO members` | 신규 가입 1건. 요청에 PII(`name`, `email`, `phone`, `birth_date`, `password_hash`)가 들어 있다 | 201 생성 / 200 같은 `member_id`가 이미 있음(멱등) / 409 이메일·전화 중복 |
| `POST /v1/orders` | `create_order`: `orders` + `order_items` 한 트랜잭션 | 주문 1건과 항목 N개. `total_amount` = Σ(수량×단가) 검증. **회원이 `ACTIVE`가 아니면 거절** | 201 / 200 이미 있음 / 409 회원 비활성 / 422 검증 실패 |
| `POST /v1/orders/{order_id}/payments` | `add_payment` | 결제 시도 1건(`attempt_no`, `method`, `pg`, `amount`, `status`, `failure_code`, 시각) | 201 / 200 이미 있음 / 404 주문 없음 |
| `PATCH /v1/orders/{order_id}` | `update_order_status` | 상태 전이(`status`, `status_reason`, `updated_at`) | 200 / 404 / 409 허용되지 않는 전이 |
| `POST /v1/events/clicks` | `KafkaClickSink.publish` | 클릭 **묶음**(시뮬레이터가 약 1초씩 모아 보냄, 한 번에 최대 500건 제안). 키 `session_id`로 `clickstream`에 발행 | 202 받음 |
| `GET /v1/members/active` | `pool.py`의 활성 회원 목록 (시작 때 한 번) | `member_id`만, 커서 페이지. 응답에 변경분 시작 커서를 같이 준다 | 200 |
| `GET /v1/members/changes?after=<커서>` | (새로 생김) 지금은 60초마다 10만 명을 통째로 다시 읽는다 | 커서 이후 **가입한 회원**(나중에 탈퇴한 회원도)만. 커서는 DB가 기록하는 실제 시각(`created_at`)과 `member_id`로 만든다(시뮬레이터 배속 시각과 섞지 않음). **동시에 처리된 요청은 늦게 커밋될 수 있어**, 커서보다 몇 초 앞부터 겹쳐 읽고 시뮬레이터가 중복을 버린다 | 200 |
| `GET /v1/members/signup-count?from=<시각>` | `member live` 시작 때 `SELECT count(*) FROM members WHERE signup_at >= …` | `signup_at`이 그 시각 이후인 회원 수. `member live`가 몇 번째 가입자부터 이어서 만들지(k) 정하는 데 쓴다. 껐다 켜도 같은 순서로 이어지고 `member_id`가 겹치지 않게 하는 장치다 | 200 |
| `GET /v1/catalog` | `pool.py`의 상품 가격 (시작 때 한 번) | `article_id`, `price`, 커서 페이지 | 200 |
| `GET /healthz`, `GET /readyz` | – | 살아 있음 / DB·Kafka 연결 준비 | 200 / 503 |
| `GET /metrics` | – | Prometheus 지표 (8절) | 200 |

- **멱등성**: ID를 시뮬레이터가 정하므로, 같은 ID로 다시 보내면 새로 만들지 않고 200을 준다. 지금의 "`23505`면 건너뜀"과 같은 효과다. 네트워크 재시도에도 안전하다. 단 **같은 ID인데 내용이 다르면 `409`**(`ID_CONFLICT`)로 거절한다. 조용히 200을 주면 시뮬레이터 버그가 숨는다.
- **탈퇴**(`POST /v1/members/{member_id}/withdraw`, `members_archive` 이동)는 탈퇴 작업이 정해질 때 더한다. 지금 시뮬레이터에 탈퇴가 없다.
- **목록 읽기 (결정, Q2)**: 시뮬레이터는 API로 읽는다. 주문마다 읽지 않고 메모리 목록에서 뽑는다.
  - 목록이 늦어도 오류는 없다. 새 회원은 다음 변경분(최대 약 5초)부터 주문자에 들어간다. 목록에 있는 회원은 모두 DB에 있다.
  - 위험은 (나중에 생길) **탈퇴한 회원이 목록에 남는 것**이다. 그래서 주문 API가 `ACTIVE`를 확인해 `409`로 거절하고, 시뮬레이터는 409를 받으면 그 회원을 목록에서 뺀다.
  - 시뮬레이터 코드에는 이미 `MemberSource`, `CatalogSource` 인터페이스가 있어 `ApiMemberSource`, `ApiCatalogSource`만 더하면 된다.
- 지금 시뮬레이터 코드에서 API로 바꿀 곳: `behavior/sink.py`(`OrderSink`, `ClickSink`), `member/live.py`(가입 `INSERT`와 시작 때 `COUNT`), `behavior/pool.py`(목록 읽기). 바꾼 뒤 `member live`·`behavior live`는 DB 계정 없이 돈다.

### 요청·응답 예시

모두 `Content-Type: application/json`. 필드 이름은 지금 시뮬레이터가 DB에 넣는 이름 그대로다(`behavior/model.py`, `db/schema/`). ID와 시각은 시뮬레이터가 정해서 보낸다(Q1 A).

```json
// POST /v1/members  (PII 포함, 로그에 남기지 않는다. status·created_at은 서버가 채운다)
{"member_id": "…", "name": "…", "email": "…", "phone": "…", "birth_date": "1995-03-14",
 "password_hash": "…", "gender": "F", "age_band": "20s", "region_sigungu": "서울특별시 강남구",
 "signup_channel": "app", "marketing_consent": true, "signup_at": "2026-10-20T06:20:01Z"}

// POST /v1/orders  (주문 + 항목 한 번에)
{"order_id": "…", "member_id": "…", "session_id": "…", "status": "PLACED", "total_amount": 15800,
 "ordered_at": "2026-10-20T06:21:10Z",
 "items": [{"order_item_id": "…", "article_id": "0108775015", "quantity": 2, "unit_price": 7900}]}

// POST /v1/orders/{order_id}/payments
{"payment_id": "…", "attempt_no": 1, "method": "CARD", "pg": "PG_A", "amount": 15800,
 "status": "FAILED", "failure_code": "PG_TIMEOUT",
 "requested_at": "2026-10-20T06:21:20Z", "completed_at": "2026-10-20T06:21:23Z"}

// PATCH /v1/orders/{order_id}
{"status": "CANCELLED", "status_reason": "USER_REQUEST", "updated_at": "2026-10-20T06:25:00Z"}

// POST /v1/events/clicks  (각 이벤트를 그대로 clickstream에 한 건씩, 키 session_id. Bronze 모양은 지금과 같다)
{"events": [{"event_id": "…", "event_type": "view", "member_id": "…", "article_id": "0108775015",
             "event_time": "2026-10-20T06:20:05Z", "session_id": "…"}]}

// 응답: GET /v1/catalog,  GET /v1/members/changes?after=…
{"items": [{"article_id": "0108775015", "price": 7900}], "next_cursor": "…"}
{"added": ["…"], "removed": [], "next_cursor": "…"}

// 오류
{"error": "MEMBER_NOT_ACTIVE", "detail": "member_id …"}
```

## 6. 데이터 규칙 (제안)

- 업무 DB는 RDS **`postgres` DB**다(로컬 Docker는 `clothes`). 스키마는 `db/schema/`를 그대로 쓴다. API는 DDL을 바꾸지 않는다.
- 시각은 UTC로 받고 UTC로 저장한다(`timestamptz`). "Bronze는 UTC, Silver에서 KST로 한 번만" 규칙을 지킨다.
- **PII**: 가입 요청 본문에만 있다. **로그, 오류 메시지, 지표 라벨에 PII를 남기지 않는다.** 오류는 `member_id`나 필드 이름만 알린다.
- 검증은 DB 제약과 같게 한다(상태 값, 결제 상태와 실패 코드 짝, 시각 순서 등). DB가 마지막 방어선이다.

## 7. 연결과 권한 (제안)

### DB
- **앱 전용 계정**(예: `clothes_app`)을 만든다. 마스터나 CDC 계정(`clothes_cdc`)을 쓰지 않는다.
- 권한: `members` INSERT·SELECT, `orders` INSERT·UPDATE·SELECT, `order_items`·`payments` INSERT·SELECT, `product_variant` SELECT. `members_archive`는 탈퇴 작업 때 정한다.
- 비밀번호는 Secrets Manager(도쿄) → K8s Secret으로 공급한다(CDC와 같은 방식). TLS `verify-full`, RDS CA 번들.
- 연결 풀 크기와 계정 연결 한도는 replica 수에 맞춰 정한다.
- RDS SG: 이미 EKS 클러스터 SG → 5432가 열려 있다(`sim/cdc-orders`). API 전용 노드도 같은 NodeClass(클러스터 보안 그룹)를 쓰므로 추가 규칙은 필요 없다. 적용 때 확인한다.

### Kafka (클릭)
- **KafkaUser `api`**: `clickstream` 쓰기만(`clients`에 한 줄). `acks=all`, idempotent.
- 발행 실패 정책: 지금 시뮬레이터처럼 **버리고 센다**(주문 흐름을 막지 않는다). 대신 실패 수를 지표로 낸다.
- **인증서 전달 (결정)**: Strimzi는 KafkaUser Secret을 `kafka` namespace에만 만든다. WAS가 다른 namespace(`api`)에 있으면 Secret을 옮기는 절차가 필요하다. 인프라 chart도 이 부분을 비워 뒀다.
  - **결정: ② `api` namespace + Secret 복사 절차.** 인증서가 갱신되면 다시 복사해야 하므로 절차를 문서화한다. (버린 대안: `kafka` namespace에 두기, External Secrets)
- Kafka 브로커 NetworkPolicy에 WAS를 허용 대상으로 더한다(`kafka.clientNamespaces` 또는 Pod 선택).

## 8. 관제 (제안)

AI 관제 에이전트와 대시보드가 쓸 수 있게 처음부터 넣는다.

- `/metrics`(Prometheus): 경로별 요청 수, 응답 시간 분포, 상태 코드별 수, DB 풀 사용량, DB 오류 수, Kafka 발행 성공·실패 수
- 로그: stdout JSON 한 줄. `request_id`, 경로, 상태 코드, 걸린 시간. PII 없음.
- ALB 지표(CloudWatch): 5xx, 대상 응답 시간, 정상 대상 수
- 지표 수집 서버는 아직 없다(인프라 `metrics/`에 예시만). 수집 연결은 별도 작업이다.

## 8.5 예상 부하와 안전장치 (제안)

배속 1 기준(하루 방문 11만, 방문당 조회 평균 5, 주문 전환 4.5%, 주문당 API 약 5번, `burst` = 피크의 10배).

| 상황 | 방문/초 | 클릭/초 | 주문 관련 API/초 |
|---|---|---|---|
| 하루 평균 | 약 1.3 | 약 7 | 약 0.3 |
| 피크 시간대 | 약 2.6 | 약 13 | 약 0.7 |
| burst (15분) | 약 26 | 약 135 | 약 6 |

- 클릭을 묶어 보내면 burst 때도 API 요청은 초당 수 건~수십 건이다. Pod 1개와 db.t4g.small로 충분할 것으로 본다. **`api/mvp`에서 초당 200 요청으로 실제 측정한다.** (2026-10-21 로컬 측정: 프로세스 1개 초당 약 200 요청, 오류 0. 결과는 `docs/tasks/api-mvp.md`)
- **배속(`--speed`)을 올리면 위 숫자가 그 배수로 늘어난다.** ECS 기본은 배속 1로 두고, 배속을 올릴 수 있는 한계를 측정으로 정한다.
- 시뮬레이터: 주문·결제·가입 요청이 실패하면 **간격을 늘려 가며 다시 보낸다**(ID가 고정이라 중복 없음). 클릭은 지금처럼 버리고 센다.
- API: DB 연결이 꽉 차면 기다리지 않고 **503**으로 빨리 거절한다. `/readyz`가 실패하면 ALB가 그 Pod로 보내지 않는다.

## 9. 배포 (제안)

| 항목 | 제안 | 근거·주의 |
|---|---|---|
| 위치 | EKS, namespace **`api`** (결정) | 사용자 결정(EKS Pod, 새 namespace) |
| replica | **1개로 시작 (결정)**, 부하를 보고 늘린다 | |
| 노드 | **API 전용 노드 풀 `clothes-query-dev-api` (결정, 2026-10-21)**: t3a.medium(2 vCPU, 4 GiB), taint `clothes-query/dedicated=api:NoSchedule`(API Pod만 허용), CPU 한도 2(= 최대 1대). API Helm chart가 Karpenter `NodePool`을 만들고 기존 NodeClass `clothes-query-dev-compute`를 같이 쓴다 | 기존 풀(t3a.large 1대, CPU 요청 약 76%)에 API까지 올리면 약 90%라 빡빡하다. **기존 풀은 바꾸지 않으므로 Kafka 쪽 Pod는 옮겨지거나 줄지 않는다**(그 Pod들은 기존 풀에만 가도록 지정돼 있다). 같은 NodeClass라 서브넷·클러스터 보안 그룹이 같고 RDS 5432 규칙도 그대로다. Terraform(`compute` 스택)은 바꾸지 않는다. 비용: t3a.medium 1대분(도쿄 온디맨드 대략 월 35달러) + Auto Mode 관리비. `helm uninstall`하면 풀과 노드도 지워진다 |
| 리소스 | requests 500m / 256Mi, limits 1500m / 1Gi | 전용 노드를 거의 혼자 쓴다. Python 프로세스 하나는 약 1코어까지만 쓰므로 그 이상은 replica·worker로 늘린다. 로컬 측정(2026-10-21): 프로세스 1개 약 초당 200 요청, p95 77ms |
| 이미지 | 기존 ECR **`clothes-query-dev/was`** 저장소 재사용, digest 고정, 비root 실행 | 2026-10-20 확인: 저장소가 이미 있고 비어 있으며 태그 덮어쓰기 불가(IMMUTABLE). Terraform 변경 없음 |
| 노출 | **내부 ALB** (Ingress, `scheme: internal`), **HTTP 80 (결정)**, 대상은 WAS Service. Helm chart에 `IngressClassParams`(scheme internal) + `IngressClass`(`controller: eks.amazonaws.com/alb`) + `Ingress`를 넣으면 EKS Auto Mode가 ALB를 만든다(`infra/modules/apps/main.tf`의 예시를 internal·HTTP로 바꿔 쓴다). `app-a`·`app-c` 서브넷에 `kubernetes.io/role/internal-elb=1` 태그가 이미 있다(2026-10-20 확인). 헬스체크 `/readyz` | 인증서·도메인 불필요. 월 약 20달러. **접근 제한**: `api/mvp`에서는 ECS 태스크 SG가 아직 없으므로 처음에는 **VPC 대역만** 허용하고, `sim/ecs-image`에서 ECS SG가 생기면 그 SG만 허용하도록 좁힌다 |
| 배포 도구 | **Helm chart (결정)** | Kafka와 같은 방식. values로 환경을 나눈다 |
| 기존 `apps` 스택 | **쓰지 않는다 (결정)** | 공개 HTTPS Ingress(도메인·인증서 필수)와 WEB이 묶여 있다. 재영에게 api 전용으로 따로 간다고 알린다 |

## 10. 보안 (제안)

- 인터넷에 열지 않는다(내부 ALB + SG).
- **인증: 없음 (결정, MVP).** 내부 ALB와 SG로 막는다(처음엔 VPC 대역, ECS SG가 생기면 그 SG만). 나중에 필요하면 API 키 헤더를 더한다.
- TLS: **HTTP 80으로 시작한다 (결정, MVP).** 내부 통신이고 ALB는 HTTPS가 필수가 아니다. 필요하면 나중에 인증서를 붙인다.
- 비밀값(DB 비밀번호, API 키, Kafka 인증서)은 Git, 이미지, 로그에 넣지 않는다.

## 11. 장애 주입과의 관계

컨트롤러의 사건 종류(`controller/model.py`): `PG_OUTAGE`, `TRAFFIC_SURGE`(medium), `INGEST_LAG`(burst), `DATA_POLLUTION`(금액 불일치, 중복 결제), `OPERATOR_PAUSE`.

| 사건 | 4절 A일 때 | 메모 |
|---|---|---|
| PG 장애 | 지금처럼 시뮬레이터가 결제 결과를 바꿔 API로 보낸다 | API 지표에는 "결제 FAILED 비율 증가"로 보인다 |
| 트래픽 급증, 적재 지연 | 시뮬레이터가 요청을 더 많이 보낸다 | API 응답 시간, ALB 지표에도 드러난다 (좋은 단서) |
| **데이터 오염** | **결정: 컨트롤러가 지금처럼 DB에 직접 쓴다** | 컨트롤러에 **오염 전용 DB 계정**(예: `clothes_sim_admin`, `orders` UPDATE·SELECT, `payments` INSERT·SELECT만)을 둔다. 앱 계정·CDC 계정과 나눈다 |

## 12. 범위 밖 (다음 문서·브랜치)

- 시뮬레이터를 구성요소별 Fargate로 나눌 때의 **제어 방식**. 지금은 같은 컨테이너의 제어 파일(`FileControlSource`)로 소통하므로, 나누면 네트워크 제어가 필요하다 → `sim/console` 설계와 함께
- 웹 관리 화면 → `sim/console`. 범위 메모(2026-10-20 사용자):
  - **들어가는 것**: 시뮬레이터 시작·정지, 모드 전환, 장애 주입·정답표, 트래픽 보기
  - 트래픽 숫자는 ① **시뮬레이터 자신**(보낸 방문·클릭·주문·결제 실패·가입, API 오류·재시도)과 ② **API `/metrics`**(받은 요청, 응답 코드별 수, 결제 FAILED, 응답 시간)를 나란히 보여 준다. 둘 다 ECS에서 닿는다(내부 ALB). RDS 직접 조회는 필요해지면 나중에
  - **빠지는 것**: 업무 분석 대시보드(매출, 인기 상품 등)는 **Gold 담당**, Kafka 상세는 Kafka UI, 원인 분석은 AI 관제 에이전트
- 시뮬레이터 이미지와 ECS 자원 → `sim/ecs-image` (ECS는 사용자가 직접)
- 탈퇴, 리뷰 API

## 13. 브랜치 계획 (결정, 2026-10-20)

시간 때문에 API 구현·배포·시뮬레이터 연동을 **한 브랜치**로 합친다("PR 하나에 한 영역" 예외, PR 설명에 적는다).

| 순서 | 브랜치 | 내용 |
|---|---|---|
| 1 | `docs/api-design` | 이 문서, 새 영역 `api` 등록 |
| 2 | **`api/mvp`** (이름 제안) | ① FastAPI 앱(5절 엔드포인트, DB·Kafka 연결, 지표, 테스트, 로컬 Docker 검증, 부하 측정) ② 배포(ECR, Helm chart, 내부 ALB, DB 앱 계정, KafkaUser, EKS) ③ 시뮬레이터 연동(`ApiOrderSink`, `ApiClickSink`, `ApiMemberSource`, `ApiCatalogSource`, 재시도) |
| 3 | `sim/ecs-image` | 시뮬레이터 이미지, Fargate (ECS는 사용자) |
| 4 | `sim/console` | 웹 관리 화면 |

## 14. 남은 결정

없음. Q1~Q8 모두 2026-10-20 결정(2절 표). 구현 세부(커서 형식, 묶음 상한, 재시도 간격, 풀 크기)는 `api/mvp` 작업 지시서에서 정한다.
