# 업무 API(WAS) 설계

상태: 제안 · 2026-10-20 · 담당: WAS 담당(사용자) · 관련: `sim/cdc-orders`(PR 대기), `simulator/`

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

## 3. 전체 구조 (제안)

```
ECS Fargate (시뮬레이터)                 EKS                                       
 member live ─┐                    ┌──────────────────────────────┐
 behavior live┼─HTTP─▶ 내부 ALB ──▶│ api namespace: WAS (FastAPI) │──▶ RDS postgres DB (members, orders, order_items, payments)
 controller ──┘   (VPC 안에서만)    │                              │──▶ Kafka clickstream (mTLS, KafkaUser api)
                                   └──────────────────────────────┘
RDS ──(Debezium, 기존)──▶ Kafka members-events / orders / order-items / payments ──▶ S3 bronze/
```

- 외부(인터넷)에는 열지 않는다. ALB는 VPC 안에서만 닿는다.
- 기존 `infra/stacks/apps`의 Ingress는 **인터넷 공개 HTTPS**(도메인, 인증서 필요)용이라 이번 용도와 다르다. 2026-10-20 기준 AWS에 로드밸런서는 0개이고, EKS Auto Mode 로드밸런싱은 켜져 있어 Ingress를 만들면 ALB가 자동으로 생긴다.

## 4. 책임 나누기 — 무엇을 시뮬레이터가 정하고 무엇을 API가 정하나 (미정, 가장 중요)

시뮬레이터는 지금 **ID, 시각, 결제 결과를 모두 스스로 정한다.**
- **ID**: 시드로 만든 UUID. 같은 시드면 같은 데이터가 나오고, 재실행 때 이미 있는 주문은 `23505`로 건너뛴다.
- **시각**: 배속(`--speed`)이 걸린 **시뮬레이터 시각**. 예를 들어 `ordered_at`, `updated_at`은 실제 UPDATE 시각이 아니라 예정된 시각이다.
- **결제 결과**: 시뮬레이터가 확률로 뽑는다. PG 장애 주입(`pg_extra_fail`)도 시뮬레이터 안에서 결과를 바꾼다.

| 선택지 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. 얇은 API (제안)** | 시뮬레이터가 ID, 시각, 결제 결과를 정해 보내고, API는 **검증하고 저장**한다. 클릭은 받아서 Kafka에 넘긴다 | 지금 시뮬레이터 동작(배속, 재현성, 장애 주입, 테스트 기준값)이 그대로 유지된다. 구현이 작다 | API에 "업무 로직"이 거의 없다 |
| B. 실제 API | API가 ID, 시각(서버 시각)을 정하고, WAS 안의 **가짜 PG**가 결제 결과를 정한다. PG 장애도 WAS에 주입한다 | 더 실제 같다. 장애가 API 지표(결제 API 실패율)로 자연스럽게 드러난다 | 배속을 쓰면 시각이 실제 시각과 어긋난다. 재현성과 기존 테스트 기준값이 깨진다. 장애 주입 경로를 새로 만들어야 한다 |
| C. 섞기 | ID와 시각은 시뮬레이터(A), **결제만** WAS의 가짜 PG(B) | 결제 장애가 API 쪽 지표로 드러난다 | 두 방식이 섞여 복잡하다. 결제 결과의 재현성이 깨진다 |

**제안은 A로 시작하는 것이다.** 지금 시뮬레이터, 컨트롤러, 테스트를 그대로 쓰면서 API 경로부터 만든다. 필요해지면 결제만 C로 옮길 수 있게 엔드포인트를 나눠 둔다.

## 5. 엔드포인트 (제안, 4절 A 기준)

모두 JSON, 경로 앞에 `/v1`. 시각은 **UTC ISO 8601(`…Z`)**. 금액은 정수(원).

| 메서드·경로 | 지금 시뮬레이터가 하는 일 | 내용 | 응답 |
|---|---|---|---|
| `POST /v1/members` | `member live`의 `INSERT INTO members` | 신규 가입 1건. 요청에 PII(`name`, `email`, `phone`, `birth_date`, `password_hash`)가 들어 있다 | 201 생성 / 200 같은 `member_id`가 이미 있음(멱등) / 409 이메일·전화 중복 |
| `POST /v1/orders` | `create_order`: `orders` + `order_items` 한 트랜잭션 | 주문 1건과 항목 N개. `total_amount` = Σ(수량×단가) 검증 | 201 / 200 이미 있음 / 422 검증 실패 |
| `POST /v1/orders/{order_id}/payments` | `add_payment` | 결제 시도 1건(`attempt_no`, `method`, `pg`, `amount`, `status`, `failure_code`, 시각) | 201 / 200 이미 있음 / 404 주문 없음 |
| `PATCH /v1/orders/{order_id}` | `update_order_status` | 상태 전이(`status`, `status_reason`, `updated_at`) | 200 / 404 / 409 허용되지 않는 전이 |
| `POST /v1/events/clicks` | `KafkaClickSink.publish` | 클릭 여러 건(배치, 상한 미정). 키 `session_id`로 `clickstream`에 발행 | 202 받음 |
| `GET /v1/members/active` | `pool.py`의 활성 회원 목록 | `member_id`만, 커서 페이지 | 200 |
| `GET /v1/catalog` | `pool.py`의 상품 가격 | `article_id`, `price`, 커서 페이지 | 200 |
| `GET /healthz`, `GET /readyz` | – | 살아 있음 / DB·Kafka 연결 준비 | 200 / 503 |
| `GET /metrics` | – | Prometheus 지표 (8절) | 200 |

- **멱등성**: ID를 시뮬레이터가 정하므로, 같은 ID로 다시 보내면 새로 만들지 않고 200을 준다. 지금의 "`23505`면 건너뜀"과 같은 효과다. 네트워크 재시도에도 안전하다.
- **탈퇴**(`POST /v1/members/{member_id}/withdraw`, `members_archive` 이동)는 탈퇴 작업이 정해질 때 더한다. 지금 시뮬레이터에 탈퇴가 없다.
- **읽기 두 개**(활성 회원, 상품 가격)를 API로 할지, 시뮬레이터가 지금처럼 DB에서 직접 읽을지는 **미정**이다. API로 하면 시뮬레이터가 DB 계정을 아예 갖지 않아도 된다(제안).
- 지금 시뮬레이터 코드에서 `ApiOrderSink`, `ApiClickSink`로 바꿀 곳: `behavior/sink.py`(`OrderSink`, `ClickSink`), `member/live.py`(`INSERT`), `behavior/pool.py`(읽기).

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
- RDS SG: 이미 EKS 클러스터 SG → 5432가 열려 있다(`sim/cdc-orders`). WAS Pod도 같은 노드라 추가 규칙은 필요 없을 것으로 본다. 적용 때 확인한다.

### Kafka (클릭)
- **KafkaUser `api`**: `clickstream` 쓰기만(`clients`에 한 줄). `acks=all`, idempotent.
- 발행 실패 정책: 지금 시뮬레이터처럼 **버리고 센다**(주문 흐름을 막지 않는다). 대신 실패 수를 지표로 낸다.
- **인증서 전달 (미정)**: Strimzi는 KafkaUser Secret을 `kafka` namespace에만 만든다. WAS가 다른 namespace(`api`)에 있으면 Secret을 옮기는 절차가 필요하다. 인프라 chart도 이 부분을 비워 뒀다.
  - ① WAS를 `kafka` namespace에 둔다 (간단, 대신 namespace가 섞인다)
  - ② `api` namespace를 두고 Secret 복사 절차를 만든다 (인증서 갱신 때 다시 복사해야 함)
  - ③ 다른 방법(External Secrets 등)
- Kafka 브로커 NetworkPolicy에 WAS를 허용 대상으로 더한다(`kafka.clientNamespaces` 또는 Pod 선택).

## 8. 관제 (제안)

AI 관제 에이전트와 대시보드가 쓸 수 있게 처음부터 넣는다.

- `/metrics`(Prometheus): 경로별 요청 수, 응답 시간 분포, 상태 코드별 수, DB 풀 사용량, DB 오류 수, Kafka 발행 성공·실패 수
- 로그: stdout JSON 한 줄. `request_id`, 경로, 상태 코드, 걸린 시간. PII 없음.
- ALB 지표(CloudWatch): 5xx, 대상 응답 시간, 정상 대상 수
- 지표 수집 서버는 아직 없다(인프라 `metrics/`에 예시만). 수집 연결은 별도 작업이다.

## 9. 배포 (제안)

| 항목 | 제안 | 근거·주의 |
|---|---|---|
| 위치 | EKS, namespace `api` (7절 Kafka 인증서 결정에 따라 바뀔 수 있음) | 사용자 결정(EKS Pod) |
| replica | 처음 **1개**, 나중에 2개 이상 + HPA | 지금 노드 1대(t3a.large) CPU 요청 약 76%. WAS 250m를 더하면 약 90%라 노드 추가 없이 들어갈 수 있다. 2개면 노드가 늘 가능성이 크다(월 약 65달러) |
| 리소스 | requests 250m / 256Mi, limits 500m / 512Mi | 시작값. 부하를 본 뒤 조정 |
| 이미지 | 새 ECR 저장소, digest 고정, 비root 실행 | `infra/stacks/ecr`에 저장소 추가가 필요하다 |
| 노출 | **내부 ALB** (Ingress, `scheme: internal`), HTTP 80, 대상은 WAS Service | 인증서·도메인 불필요. 월 약 20달러. ALB SG는 ECS 시뮬레이터 태스크 SG만 허용 |
| 배포 도구 | Helm chart 또는 매니페스트 (미정) | Kafka처럼 Helm으로 하면 values로 환경을 나누기 쉽다 |
| 기존 `apps` 스택 | 이번에는 쓰지 않는다 (제안) | 공개 HTTPS Ingress와 WEB이 함께 묶여 있다. 재사용할지 재영과 확인 |

## 10. 보안 (제안)

- 인터넷에 열지 않는다(내부 ALB + SG).
- **인증 (미정)**: ① 없음(네트워크로만 막음) ② **API 키 헤더**(Secrets Manager에 두고 ECS와 WAS에 공급, 제안) ③ IAM 서명 등.
- TLS(ALB → 클라이언트 구간): 내부 통신이라 처음에는 HTTP로 시작하고, 필요하면 내부 인증서를 붙인다(미정).
- 비밀값(DB 비밀번호, API 키, Kafka 인증서)은 Git, 이미지, 로그에 넣지 않는다.

## 11. 장애 주입과의 관계 (미정)

컨트롤러의 사건 종류(`controller/model.py`): `PG_OUTAGE`, `TRAFFIC_SURGE`(medium), `INGEST_LAG`(burst), `DATA_POLLUTION`(금액 불일치, 중복 결제), `OPERATOR_PAUSE`.

| 사건 | 4절 A일 때 | 메모 |
|---|---|---|
| PG 장애 | 지금처럼 시뮬레이터가 결제 결과를 바꿔 API로 보낸다 | API 지표에는 "결제 FAILED 비율 증가"로 보인다 |
| 트래픽 급증, 적재 지연 | 시뮬레이터가 요청을 더 많이 보낸다 | API 응답 시간, ALB 지표에도 드러난다 (좋은 단서) |
| **데이터 오염** | **미정**: ① 컨트롤러가 지금처럼 DB에 직접 쓴다(관리자 작업) ② API에 관리용 엔드포인트를 둔다(버그 흉내) | ①이면 컨트롤러에 DB 계정이 남는다. ②면 관리 엔드포인트를 외부에 노출하지 않게 막아야 한다 |

## 12. 범위 밖 (다음 문서·브랜치)

- 시뮬레이터를 구성요소별 Fargate로 나눌 때의 **제어 방식**. 지금은 같은 컨테이너의 제어 파일(`FileControlSource`)로 소통하므로, 나누면 네트워크 제어가 필요하다 → `sim/console` 설계와 함께
- 웹 관리 화면(시작·정지, 모드, 대시보드) → `sim/console`
- 시뮬레이터 이미지와 ECS 자원 → `sim/ecs-image` (ECS는 사용자가 직접)
- 탈퇴, 리뷰 API

## 13. 브랜치 계획 (제안)

| 순서 | 브랜치 | 영역 | 내용 |
|---|---|---|---|
| 1 | `docs/api-design` | docs | 이 문서, 새 영역 `api` 등록 |
| 2 | `api/skeleton` | api | FastAPI 앱, 5절 엔드포인트, DB·Kafka 연결, 지표, 테스트, 로컬 Docker로 검증 |
| 3 | `api/deploy` | api (+ 인프라 값) | ECR, Helm/매니페스트, 내부 ALB, DB 앱 계정, KafkaUser, EKS 배포 |
| 4 | `sim/api-sink` | sim | `ApiOrderSink`, `ApiClickSink`, 읽기 API 사용. 로컬에서 API와 함께 검증 |
| 5 | `sim/ecs-image` | sim | 시뮬레이터 이미지, Fargate (ECS는 사용자) |
| 6 | `sim/console` | sim | 웹 관리 화면 |

## 14. 사용자가 정할 것 (요약)

| # | 질문 | 선택지 | 제안 |
|---|---|---|---|
| Q1 | 책임 나누기 (4절) | A 얇은 API / B 실제 API / C 결제만 API | **A** |
| Q2 | 읽기(활성 회원, 상품 가격)도 API로? (5절) | API / 시뮬레이터가 DB 직접 | **API** (시뮬레이터에 DB 계정 불필요) |
| Q3 | WAS namespace와 Kafka 인증서 (7절) | ① `kafka` ns ② `api` ns + Secret 복사 ③ 기타 | ② (namespace 분리, 복사 절차는 문서화) |
| Q4 | API 인증 (10절) | 없음 / API 키 / IAM | **API 키** |
| Q5 | 데이터 오염 주입 (11절) | 컨트롤러가 DB 직접 / API 관리 엔드포인트 | 컨트롤러 DB 직접 (지금 유지) |
| Q6 | 배포 도구 (9절) | Helm / 매니페스트 | Helm (Kafka와 같은 방식) |
| Q7 | 시작 replica (9절) | 1 / 2 | **1** (노드 추가 없이 시작) |
| Q8 | 기존 `apps` 스택 재사용 (9절) | 재사용 / 새로 | 새로 (재영과 확인) |
