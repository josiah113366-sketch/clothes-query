# 작업 지시서: sim/behavior-core

> 상태: 완료 · 브랜치: `sim/behavior-core` · 이전 작업: `db/order-schema`, `sim/modes`, `sim/product-seed` · 다음 작업: `sim/controller`, `sim/clickstream`, `sim/cdc-orders`

## 목표

**방문 → 조회 → 장바구니 → 주문 → 결제(재시도 포함) → 상태 전이**를 만들어 `orders`, `order_items`, `payments`에 쓰는 `sim behavior live` 명령을 만든다. 출력은 교체할 수 있는 **Sink 인터페이스**(주문 Sink, 클릭 Sink)로 나누어, 지금은 DB 직접 쓰기와 파일 출력만 구현하고 나중에 쇼핑몰 API나 Kafka로 바꿀 수 있게 한다.

이 브랜치가 끝나면 로컬 DB에서 `sim behavior live`를 켜 두면 일상 곡선대로 방문이 생기고, 주문이 만들어지고, 결제가 시도되고, 예약된 시각마다 주문 상태가 `PLACED → PAID → SHIPPED → DELIVERED`(또는 취소·결제 실패·반품)로 바뀐다. 시작·멈춤·모드는 기존 제어 파일로 바꾼다.

이 시뮬레이터는 **ECS에 그대로 올라가는 것을 전제**로 만든다. 로컬 전용 경로를 따로 두지 않는다. 접속 정보는 환경 변수, 로그는 stdout, 종료는 SIGTERM 처리다.

이 지시서는 **자기 완결형**이다. 설계 문서(`docs/design/*`)가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.** (이 지시서의 `[가정]` 값은 사용자가 팀과 맞추는 임시값이다. 코드에 박지 말고 `params.py` 한 곳에 둔다.)

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `simulator/CLAUDE.md`, `simulator/README.md`
- `docs/tasks/sim-member-live.md` (**같은 패턴**의 선행 작업: 시계, 제어 신호, 재연결, 종료, 시작 인덱스)
- `docs/tasks/sim-modes.md` (`common/curve.py`, 모드 3개)
- 코드: `common/clock.py`, `common/control.py`, `common/curve.py`, `common/rng.py`, `common/db.py`, `common/config.py`, `member/live.py`(실행기 구조 참고. **import하지 않는다**), `member/cli.py`
- DDL: `db/schema/001_member.sql`, `003_product.sql`, `004_orders.sql`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 루트 `CLAUDE.md`의 Git 규칙을 따른다 (작은 커밋, **push와 PR은 사용자 확인 후**). 커밋 메시지는 **타입을 붙인다(사용자 결정, 루트 `CLAUDE.md`의 형식보다 우선)**: `<타입>(sim/behavior-core): <한국어 요약>`. 타입은 `feat`(기능), `fix`(버그 수정), `test`(테스트), `docs`(문서), `refactor`(동작 변화 없는 정리), `chore`(그 외 잡일) 중 하나다. 한 커밋에 타입 하나만 쓰고, 타입이 섞이면 커밋을 나눈다.
- **로컬 DB에만** 쓴다. RDS에는 접속하지 않는다. (원격 DB 허용 스위치 코드는 만들지만 실제 원격 접속은 확인하지 않는다. RDS와 NAT, EKS는 이미 배포되어 있지만 이 브랜치의 검증은 로컬 DB로만 한다. RDS 접속용 TLS(`verify-full`·CA 번들)와 제네레이터 전용 DB 계정은 `sim/ecs-image`에서 다룬다. 여기서는 만들지 않는다.)
- 최신 `main`의 새 규칙을 따른다: 브랜치를 만들면 `docs/BRANCHES.md`의 `sim` 구역에 한 줄을 추가하고(같은 PR), 머지 전에 이 지시서 맨 아래 `작업 결과` 절을 채운다. 이 지시서 파일은 `docs/tasks/sim-behavior-core.md`로 둔다.
- Kafka에는 연결하지 않는다. 클릭 로그는 파일 또는 버린다.
- Python 3.12 가상환경(`simulator/.venv`), 로컬 Docker Compose Postgres를 쓴다. 호스트에 `psql`이 없으면 `docker compose exec postgres psql -U sim -d clothes`로 확인한다.
- 완료 확인 중 만든 `orders`, `order_items`, `payments` 행은 **확인 후 삭제**하고 건수를 보고한다 (단, 시작 전에 비어 있었을 때만).

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 **최신 `main`**에서 만든 `sim/behavior-core`인지 확인한다. `docs/BRANCHES.md`의 `sim` 구역 형식도 읽어 둔다.
- 아래가 **모두 현재 브랜치에 있는지** 확인한다. 하나라도 없으면 만들지 말고 사용자에게 알린다 (브랜치를 쌓을지 먼저 머지할지 사용자가 정한다). `004_orders.sql`은 RDS에는 이미 적용되어 있지만 레포에는 `db/order-schema` 머지 후에야 들어간다.
  - `db/schema/003_product.sql`(`product_variant`), `db/schema/004_orders.sql`
  - `simulator/src/sim/common/curve.py`의 `rate_factor`, `common/control.py`의 `MODES == ("normal", "medium", "burst")`
- `pytest`(단위)와 `ruff check .`가 변경 전에 통과하는지 먼저 본다.
- `docker compose ps`로 로컬 Postgres를 확인하고, `SELECT count(*) FROM members;`(10만 기대), `SELECT count(*) FROM product_variant;`, 주문 테이블 행 수를 확인한다.
  - `product_variant`가 비어 있으면 알린다 (`sim product load`는 S3 접근이 필요하다). 완료 확인에서는 임시 합성 상품으로 대신한다.

## 설계 근거 (결정 / 가정)

### 큰 흐름

```
방문 시작 (회원 선택, session_id 발급)
  → 조회 N번 ─(15%)→ 담기 ─(28%)→ 주문 생성 → 결제 시도(실패 시 재시도) → 상태 전이
       │                └ 이탈        └ 이탈 (담은 채 나감)
       └ 이탈
  (담기 없이 바로 주문: 전체 방문의 0.3%)
```

- 시뮬레이터는 **RDS에만 쓴다.** `orders`, `order_items`, `payments`는 CDC가 Kafka로 보낸다. 클릭 로그(조회·담기)는 RDS에 넣지 않고 Kafka로 직접 발행하는 것이 설계다 (이 브랜치는 Sink 자리만 만든다).
- **방문 단위**로 시뮬레이션한다. 방문 하나가 `session_id`(UUID) 하나다. 모든 방문에 `member_id`가 있다.
- **트래픽은 하루 할당량을 시간대 곡선에 분배**하는 방식이다. 분당 배수를 쏘지 않는다. 방문은 푸아송으로 도착하고(간격은 지수분포), 속도는 `visits_daily ÷ 86,400 × rate_factor(mode, 시뮬레이터 시각)`이다. 주문 수는 고정하지 않고 방문 확률의 결과로 약 5,000건/일이 된다.
- 예약된 상태 전이는 **메모리 큐에만** 둔다. DB에서 복구하지 않는다 (사용자 결정. ECS를 재시작하지 않는다는 전제. 재시작하면 진행 중이던 주문은 그 상태에 멈춘다 — README에 한 줄 적는다).
- `orders.updated_at`과 모든 전이 시각은 **예정된 시각**이다 (실제 UPDATE 시각이 아니다). 그래서 체류시간이 아래 지연 표와 맞는다.
- 쓰기 순서(트랜잭션을 묶지 않고 **따로** 쓴다): `orders`+`order_items` INSERT(`PLACED`) → (결제 시도 결과가 확정된 시각에) `payments` INSERT → `orders` UPDATE. `orders`와 그 `order_items`는 한 트랜잭션이다(주문 행만 먼저 보이지 않게). 나머지는 **자동 커밋 한 건씩**이다.
- `payments`는 INSERT만. 환불은 `payments` 행을 만들지 않는다.
- 행동 성향(고객 유형 등)은 DB에 넣지 않는다.

### 값 (모두 `behavior/params.py` 한 곳에. 출처: 설계=`[설계]`, H&M 실측=`[H&M]`, 임시값=`[가정]`)

**방문**

| 항목 | 값 | 출처 |
|---|---|---|
| 하루 평균 방문 `NORMAL_DAILY_VISITS` | 111,000 | `[가정]` (주문 5,000 ÷ 전환율 4.5%) |
| 방문당 조회 수 | `n = clamp(1 + round(expovariate(1/4)), 1, 20)`, 평균 약 5 (1~20, 오른쪽으로 긴 분포) | `[가정]` |
| 방문 → 담기 | 15% | `[가정]` |
| 담기 → 주문 | 28% | `[가정]` |
| 담기 없이 바로 주문 | 전체 방문의 0.3% (이 경우 담기 로그 없음, 조회 로그는 있음) | `[가정]` |
| 담기만 하고 나간 방문의 담은 개수 | 1~3 균등 | `[가정]` |
| 주문한 방문의 담은 상품 | 담은 것 **전부** 주문 (담은 개수 = 주문 상품 줄 수) | `[가정]` |
| 방문자 선택 | 상위 20% 회원의 가중치 = 나머지의 6배 (방문의 약 60%가 상위 20%) | `[가정]` |

**주문 구성**

| 항목 | 값 | 출처 |
|---|---|---|
| 주문당 상품 줄 수 | 1개 29.8%, 2개 23.5%, 3~4개 24.1% (3, 4 균등), 5~9개 17.1% (균등), 10개 이상 5.5% (10~15 균등) | `[H&M]` |
| 줄당 수량 | 1 → 90.6%, 2 → 6.5%, 3 → 1.8%, 4 → 0.7%, 5 → 0.4% ("5개 이상"은 5로 둔다) | `[H&M]` 해석값 + `[가정]` |
| 한 주문 안의 상품 | 서로 다른 `article_id` (중복 줄 없음) | `[가정]` |
| `unit_price` | 주문 시점의 `product_variant.price` 복사 | `[설계]` |
| `total_amount` | Σ(`quantity` × `unit_price`), **항상 일치** (평소 불일치 0건) | `[설계]` |
| 결제 수단 `method` | CARD 55%, SIMPLE_PAY 35%, BANK_TRANSFER 10% (주문당 한 번 뽑고, 재시도에도 그대로) | `[가정]` |

**상품 선택** (H&M 구매 쏠림: 상위 1% → 18.6%, 5% → 44.0%, 10% → 60.7%, 20% → 79.1%, 50% → 96.8%)

- 상품 목록은 `product_variant`에서 읽는다 (`article_id`, `price`를 `article_id` 순으로).
- 인기 순위는 **시드로 섞은 순열**이다 (파일 없음). 순위 비율 → 누적 비율의 구간 선형 표 `(0,0) (0.01,0.186) (0.05,0.44) (0.10,0.607) (0.20,0.791) (0.50,0.968) (1.0,1.0)`에 **역함수 추첨**으로 순위를 뽑는다(구간 안에서는 균등). 구매 순위 순열과 조회 순위 순열은 **서로 다른 줄기의 시드**로 섞는다.
- 구매(담기) 상품은 구매 순위에서 뽑는다. 조회 상품은 70%는 조회 순위, 30%는 구매 순위에서 뽑는다 (두 랭킹이 똑같아 보이지 않게).
- 나중에 실제 가중치 파일로 바꿀 수 있게 `ProductRanking` 같은 작은 클래스로 감싸 `sample(rng) -> article 인덱스` 인터페이스만 노출한다.

**방문 안의 시각** (`[가정]`, 균등 분포)

| 항목 | 값 |
|---|---|
| 방문 시작(첫 조회) | 방문 도착 시각 |
| 조회 사이 간격 | 10~60초 |
| 담기 | 그 상품 조회 뒤 5~30초 |
| 주문 생성 | 방문의 마지막 이벤트 뒤 20~120초 |

**결제** (`[가정]`)

| 항목 | 값 |
|---|---|
| `PLACED` → 첫 결제 시도 | 3~30초 (결제 전 취소로 정해진 주문은 시도 없음) |
| 결제 시도 처리 시간 (`requested_at` → `completed_at`) | 2~5초 |
| 첫 시도의 PG | PG_A 50%, PG_B 50% |
| 첫 시도 결과 | 성공 92%, 실패 8% (고객 원인 7%, PG 원인 1%) |
| 실패 후 재시도 | 60%, **한 주문의 시도는 최대 3번** (첫 시도 포함) |
| 재시도 간격 | 이전 시도 `completed_at` 뒤 30~120초 |
| 재시도 때 PG | 30% 확률로 **다른 PG로 바꾼다**, 70%는 그대로 |
| 재시도 결과 | 성공 70%, 실패 30% (실패 원인 비율은 고객 7 : PG 1 유지, 즉 고객 26.25%, PG 3.75%) |
| 고객 원인 코드 | INSUFFICIENT_BALANCE 40%, CARD_LIMIT_EXCEEDED 35%, CARD_DECLINED 25% |
| PG 원인 코드 | PG_TIMEOUT 60%, PG_ERROR 40% |
| 코드와 수단 | `CARD_LIMIT_EXCEEDED`, `CARD_DECLINED`는 CARD·SIMPLE_PAY만. BANK_TRANSFER의 고객 원인 실패는 항상 INSUFFICIENT_BALANCE |
| `amount` | 항상 `orders.total_amount`와 같음 |

**기준값 (코드가 아니라 테스트가 확인한다):** 결제 단계에 간 주문 1건당 시도 약 1.057회, 시도 단위 실패율 약 9.2%, 주문 단위 최종 결제 실패(`PAYMENT_FAILED`) 약 4.0%.

**상태 전이** (취소·반품 분기는 그 상태가 될 때 **한 번만** 추첨한다. 취소로 정해진 주문은 다음 단계로 가지 않는다)

| 전이 | 확률 | 소요 시간 (균등) | `status_reason` |
|---|---|---|---|
| `PLACED` → `CANCELLED` (결제 전 취소) | 1.5% (주문 생성 때 추첨) | 주문 후 1~5분 | `USER_REQUEST` |
| `PLACED` → `PAID` | 결제 성공 | 성공한 시도의 `completed_at` | |
| `PLACED` → `PAYMENT_FAILED` | 재시도 소진(재시도 안 함 포함) | 마지막 실패의 `completed_at` | |
| `PAID` → `CANCELLED` (배송 전 취소) | 3% | 결제 후 10분~3시간 | `USER_REQUEST` |
| `PAID` → `SHIPPED` | 97% | 결제 후 2~6시간 | |
| `SHIPPED` → `DELIVERED` | 100% | 16~22시간 | |
| `DELIVERED` → `REFUNDED` (반품) | 7% | 배송 완료 후 2~36시간 (3일 실행에서 보이도록 **압축한 값**) | `RETURN` |

배송은 결제 후 약 하루(18~28시간)다. `CANCELLED`, `PAYMENT_FAILED`, `REFUNDED`는 종결 상태다. `DELIVERED`로 남은 주문은 정상 종료로 본다.

### 장애 주입을 위한 자리 (동작은 지금 0)

PG 장애(`controller` 브랜치)는 **결제 시도 시각의 상태**를 읽어 결과를 바꿔야 한다. 그래서 결제 결과 추첨 함수는 `pg_extra_fail: Mapping[str, float] = {}`(PG 이름 → 그 PG의 PG 원인 실패 확률 추가분) 인자를 **받기만** 한다. 비어 있으면 위 표 그대로 동작한다. 값이 있으면 그 PG의 시도는 (기본 PG 원인 실패 확률 + 추가분, 최대 1)로 PG 원인 실패가 늘고 그만큼 성공이 줄어든다. 이 인자를 채우는 쪽(제어 신호 읽기)은 만들지 않는다. 결과 추첨은 **큐에서 실행되는 시점에** 하며, 주문 생성 때 미리 정해 두지 않는다(그래야 장애 구간에 시도되는 결제만 영향을 받는다).

## 동작

### 시계와 시각

- `common/clock.py`의 `SimClock`을 그대로 쓴다 (`--speed`). 모든 시각은 **시간대 정보가 있는 KST** 값이다. DB 컬럼이 `timestamptz`이므로 psycopg에 그대로 넘긴다.
- 모든 예약 시각(`due`)과 `updated_at`, `event_time`은 **예정된 시뮬레이터 시각**이다. 처리가 늦어도 시각은 바꾸지 않는다.
- 실제 대기는 `간격 ÷ 배속`이다.

### 실행 루프 (한 프로세스, 한 번에 하나씩, 쓰레드·비동기 없음)

1. 약 1초마다 제어 신호를 읽는다 (`FileControlSource`, 기본 `.local/control.json`, `member live`와 **같은 파일**).
   - `mode` 변경: 다음 방문 도착 시각을 지금부터 **다시 뽑는다**(지수분포는 기억이 없다). 출력에 `mode: normal → burst` 한 줄.
   - `running=false`: **새 방문만 멈춘다.** 이미 예약된 클릭·결제·상태 전이는 계속 실행한다. `true`가 되면 새 방문 간격을 다시 뽑는다.
2. 시뮬레이터 시각 `now` 이전에 도착(`visit_due`)하거나 예정된(`queue due`) 것을 **시각 순서대로** 하나씩 실행한다 (같은 시각이면 큐 등록 순서).
3. 다음 일이 올 때까지 기다린다 (최대 1초씩 나누어 제어 신호를 계속 읽는다).
4. 방문 도착 간격: `expovariate(visits_daily ÷ 86,400 × rate_factor(mode, visit_due))`(시뮬레이터 초). 속도가 시간대 경계에서 계단으로 바뀌는 오차는 허용한다.
5. 처리가 밀려 `visit_due`가 `now`보다 `CONTROL_POLL_SECONDS × 배속` 시뮬레이터 초 넘게 뒤처지면 그 이상은 따라잡지 않는다 (밀린 방문을 한꺼번에 쏟지 않는다).

### 방문 한 건 (순수 함수 `plan_visit`)

방문 `k`(0부터)의 난수는 `derive_seed(seed, "visit", run_salt, k)`로 **다시 심어서** 쓴다. 입력은 (난수, 도착 시각, 회원 ID, 상품 목록) 뿐이고 DB, 네트워크, 현재 시각을 안에서 부르지 않는다. 출력은 방문 계획이다.

1. 회원을 가중 추첨한다(회원 풀, 아래). `session_id = rng.uuid4()`.
2. 결과 추첨: `chance(0.003)`이면 바로 주문, 아니면 `chance(0.15)`이면 담기, 담기면 `chance(0.28)`이면 주문, 아니면 이탈.
3. 담을 상품(주문이면 줄 수만큼, 담기만이면 1~3개)을 구매 순위에서 **서로 다르게** 뽑는다.
4. 조회 수 `n`을 뽑고 `n = max(n, 담을 상품 수)`로 보정한다. 조회할 상품 목록은 담을 상품들을 **무작위 위치**에 끼우고 나머지는 조회 분포에서 뽑는다.
5. 시각을 붙인다(위 "방문 안의 시각"). 조회 로그(`view`), 담기 로그(`cart_add`)를 시각 순으로 만든다.
6. 주문이면 주문 계획(`order_id`, 줄들, `total_amount`, `method`, 주문 시각, 결제 전 취소 여부와 시각)을 만든다.

**정합성 규칙 (테스트가 확인한다):**
- `cart_add`한 상품은 같은 `session_id`에서 **먼저 `view`가 있다.**
- 모든 주문의 `session_id`에는 클릭 로그가 먼저 있다 (고아 주문 0건).
- 클릭 로그의 `member_id`는 그 방문 회원이고, `session_id`는 방문 안에서 같고 방문마다 다르다.

방문 계획의 클릭 로그와 주문 생성은 각각 **큐에 등록**하고 그 시각에 실행한다(클릭 `event_time`이 실제 발행 시점과 비슷하도록).

### 결제와 전이 (큐 동작)

큐 항목 종류: `CLICK`, `CREATE_ORDER`, `ATTEMPT_START`, `ATTEMPT_DONE`, `TRANSITION`. 항목은 불변 값(데이터 클래스)이다.

- `CREATE_ORDER`: 주문+줄 INSERT(`PLACED`, `ordered_at = updated_at = due`). 결제 전 취소로 정해졌으면 `TRANSITION(CANCELLED)`를 등록, 아니면 `ATTEMPT_START(1)`을 등록.
- `ATTEMPT_START(n)`: PG를 정하고(1번째는 50/50, 이후는 30%로 바꿈), 결과를 추첨하고(`pg_extra_fail` 반영), `ATTEMPT_DONE`을 `due + 2~5초`에 등록.
- `ATTEMPT_DONE`: `payments` INSERT(`requested_at`, `completed_at`). 성공이면 `orders`를 `PAID`로 UPDATE(`updated_at = completed_at`)하고 `PAID` 이후 전이(취소/배송)를 등록. 실패이면 시도가 3번 미만이고 `chance(0.6)`일 때 `ATTEMPT_START(n+1)`을 30~120초 뒤에 등록, 아니면 `PAYMENT_FAILED`로 UPDATE.
- `TRANSITION`: `UPDATE orders SET status, status_reason, updated_at = due`. 그 상태에서 이어질 다음 전이를 추첨해 등록한다 (`SHIPPED` → `DELIVERED` → 반품 추첨).
- 주문별 후속 추첨의 난수는 `derive_seed(seed, "order", run_salt, k, <단계 이름>)`에서 다시 심는다. 처리 순서에 상관없이 같은 입력이면 같은 값이 나오게 하기 위해서다.

### 회원 풀과 상품 목록 (DB에서 읽기)

- 시작할 때와 **60초(실제 시간)마다** `SELECT member_id FROM members WHERE status = 'ACTIVE' ORDER BY member_id`로 읽는다. **이름, 전화번호, 이메일 등 PII 컬럼은 읽지 않는다.** 읽기에 실패하면 이전 풀을 유지하고 한 번만 경고한다.
- 가중치: `sha256(f"{seed}:{member_id}")`의 앞 8바이트를 [0,1)로 바꿔 0.2 미만이면 6, 아니면 1. (**DB에 저장하지 않는** 결정론적 성향이다. 풀이 갱신돼도 같은 회원은 같은 가중치다.)
- 누적 가중치 배열과 `bisect`로 추첨한다.
- 풀이 비어 있으면 오류로 멈춘다 ("회원이 없습니다. sim member baseline을 먼저 실행하세요"). 상품이 비어 있으면 같은 식으로 멈춘다 ("sim product load").
- 상품 목록은 시작할 때 한 번만 읽는다.

### 시드와 재시작

- `run_salt`: 기본값은 시작 시점의 시뮬레이터 시각의 epoch 초 (정수). `--run-salt`로 직접 줄 수 있다. 시작 출력에 항상 표시한다. **같은 `seed` + 같은 `run_salt` + 같은 가짜 시계 + 같은 제어 순서이면 결과가 완전히 같다.** 서로 다른 실행(재시작 포함)은 `run_salt`가 달라 UUID가 겹치지 않는다.
- 방문 번호 `k`는 0에서 시작한다 (DB에서 세지 않는다).
- 재시작하면 메모리 큐가 사라져 진행 중이던 주문은 멈춘다. 이 브랜치는 복구하지 않는다.

### 오류와 종료

- `SIGINT`/`SIGTERM`: 지금 실행 중인 항목을 끝내고, 요약을 출력하고, 종료 코드 0으로 끝낸다. 트레이스백을 내지 않는다. 남은 큐 건수는 요약에 보인다.
- DB 연결이 끊기면(`psycopg.OperationalError`) 실패한 항목을 **큐 맨 앞에 되돌려 놓고** 1, 2, 4, … 최대 30초 간격으로 다시 연결한다. 다시 연결되면 그 항목부터 이어서 실행한다. 클릭 로그는 DB와 무관하다.
- 재실행 때 `23505`(PK/UNIQUE 위반)는 **이미 반영된 것으로 보고 넘어간다** (연결이 끊기는 순간 커밋됐을 수 있다). 그 밖의 DB 오류는 `common/db.py`의 오류 가리기를 거쳐 종료 코드 1로 멈춘다.
- 오류와 출력에 **PII가 없어야 한다.** 회원 값은 읽지도 않는다. 식별이 필요하면 `member_id`/`order_id`만 쓴다 (기본은 쓰지 않는다).
- 접속 대상이 `localhost`/`127.0.0.1`이 아니면 **실행을 거부한다.** 단, 환경 변수 `SIM_ALLOW_REMOTE_DB=1`이면 허용한다 (ECS에서 RDS로 붙기 위한 명시적 스위치다). 이 판단은 `common/db.py`의 함수로 둔다 (`member live`는 이번에 바꾸지 않는다).

## 만드는 것

### 1. Sink 인터페이스와 구현 (`behavior/sink.py`)

```python
class OrderSink(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def create_order(self, order: NewOrder, items: Sequence[NewOrderItem]) -> None:
        """orders 1행 + order_items N행을 한 트랜잭션으로."""
    def add_payment(self, payment: NewPayment) -> None: ...
    def update_order_status(
        self, order_id: str, status: str, status_reason: str | None, updated_at: datetime
    ) -> None: ...

class ClickSink(Protocol):
    def publish(self, event: ClickEvent) -> None: ...
    def close(self) -> None: ...
```

| 구현 | 쓰임 |
|---|---|
| `DbOrderSink(database_url, schema=None)` | 자동 커밋 연결로 위 세 가지를 실행한다. `create_order`만 `conn.transaction()` 안에서. 파라미터 바인딩만 쓴다(문자열 이어붙이기 금지). 나중에 `ApiOrderSink`가 같은 인터페이스를 구현한다 |
| `MemoryOrderSink` | 테스트용. 호출을 리스트로 쌓는다 |
| `NullClickSink` | 아무것도 하지 않는다 (CLI 기본값) |
| `JsonlClickSink(path)` | 한 줄에 이벤트 하나를 JSON으로 쓴다. 필드 6개: `event_id`, `event_type`, `member_id`, `article_id`, `event_time`(`+09:00`), `session_id`. `ingest_time`은 넣지 않는다(파이프라인이 붙인다) |
| `MemoryClickSink` | 테스트용 |

클릭 로그는 이번 브랜치에서 Kafka로 보내지 않는다 (→ `sim/clickstream`). 중복·지각 이벤트 노이즈도 이번에 만들지 않는다.

### 2. 코드 (`simulator/src/sim/behavior/`)

| 파일 | 내용 |
|---|---|
| `params.py` | 위 "값" 표의 **모든 수치**. 다른 곳에 숫자를 흩뿌리지 않는다. `[가정]` 표시를 주석으로 남긴다 |
| `model.py` | `ClickEvent`, `NewOrder`, `NewOrderItem`, `NewPayment`, `VisitPlan`, `OrderPlan`, `AttemptResult`, 큐 항목(불변 데이터 클래스) |
| `ranking.py` | `ProductRanking` (구간 선형 누적표의 역함수 추첨, 시드로 섞은 순열) |
| `pool.py` | `MemberPool` (누적 가중치, 결정론적 성향, 갱신), `MemberSource`/`CatalogSource` Protocol과 DB 구현 (`SELECT`는 위에 쓴 컬럼만) |
| `visit.py` | `plan_visit(...)` 순수 함수 |
| `payment.py` | 순수 함수 `choose_pg`, `decide_attempt(rng, attempt_no, method, pg, amount, requested_at, pg_extra_fail)`, `next_transition(rng, state, at)` |
| `queue.py` | `ScheduledQueue` (힙, `(due, 등록순번)` 순서, `push`, `peek_due`, `pop`, `push_front`, 길이) |
| `sink.py` | 위 1번 |
| `runner.py` | `BehaviorRunner` (실행 루프, 제어 신호, 재연결, 종료, 요약). 테스트용으로 `run_until(sim_end)`와 `drain()`(방문은 멈추고 큐가 빌 때까지 처리)을 둔다 |
| `cli.py` | `sim behavior live` |

- 파일 이름과 함수 이름은 실제 코드 구조에 맞게 조정해도 된다. **책임을 나누는 방식**(순수 함수 / 큐 / Sink / 실행기)은 지킨다.
- `behavior`는 `sim.common.*`만 import한다. **`sim.member`, `sim.controller`, `sim.cdc`, `sim.sink`를 import하지 않는다.** (`SimClock`, `FileControlSource`, `derive_seed`, `SimRandom`, `rate_factor`, `KST`, DB 도구는 `common`에 있다.)
- `sim/cli.py`에 `app.add_typer(behavior_app, name="behavior")`를 추가한다.
- 새 의존성을 추가하지 않는다.

### 3. `common/db.py` 보강

- `check_db_target(database_url, allow_remote: bool)`: 호스트가 `localhost`/`127.0.0.1`이 아니고 `allow_remote`가 아니면 오류를 낸다. 오류 메시지에 **호스트와 비밀번호를 싣지 않는다** ("로컬 DB가 아니면 SIM_ALLOW_REMOTE_DB=1이 필요합니다" 정도).

### 4. CLI

```
sim behavior live [--mode normal|medium|burst] [--visits-daily 111000] [--speed 1]
                  [--duration SECONDS] [--max-visits N] [--control-file PATH]
                  [--seed N] [--run-salt N] [--click-sink none|jsonl] [--click-file PATH]
```

| 옵션 | 환경 변수 | 기본값 | 설명 |
|---|---|---|---|
| `--mode` | `SIM_LIVE_MODE` | `normal` | 시작 모드 (`member live`와 같은 변수) |
| `--visits-daily` | `SIM_VISITS_DAILY` | 111000 | 하루 평균 방문 수 |
| `--speed` | `SIM_LIVE_SPEED` | 1 | 시간 배속 |
| `--duration` | — | 없음 | **실제 시간** 기준 실행 초 |
| `--max-visits` | — | 없음 | 이만큼 방문을 만들면 새 방문을 멈추고 정상 종료 |
| `--control-file` | `SIM_CONTROL_FILE` | `.local/control.json` | 제어 신호 파일 |
| `--seed` | `SIM_SEED` | 42 | 기본 시드 |
| `--run-salt` | — | 시작 시각 epoch 초 | 위 "시드와 재시작" |
| `--click-sink` | — | `none` | `none` 또는 `jsonl` |
| `--click-file` | — | `.local/clicks.jsonl` | `jsonl`일 때 경로 (`.local/`은 커밋하지 않는다) |

시작할 때 출력(PII 없음): 대상 DB(`호스트:포트/DB이름`만), 모드, 배속, 하루 방문 수, 시드, run_salt, 회원 수, 상품 수, 클릭 Sink. 확인 질문은 없다.

**진행 출력:** 실제 시간 10초마다 한 줄 — 모드, 지난 구간의 방문·주문·결제 시도 건수, 누적, 큐 길이, 시뮬레이터 시각. **종료 요약:** 총 방문, 클릭(조회/담기), 주문, 결제(성공/실패), 상태 전이 건수(상태별), 남은 큐 건수, 재연결 횟수, 실행 시간.

## 테스트

**단위 테스트 (DB 없이, 가짜 시계, 기본 `pytest`에 포함).** 합성 데이터는 `conftest`의 픽스처로 만든다 (회원 ID 2,000개, 상품 1,000개와 가격). 통계 검증은 **기대값 ± 5σ**(이항/푸아송)로 한다. 비싼 실행은 `scope="module"` 픽스처 하나를 여러 테스트가 공유한다.

- **방문 속도:** 7일(월요일 00:00 KST 시작) → 방문 수가 `visits_daily × 7` ± 5σ, 시간대 구간별 비율이 곡선 비율 ± 5σ
- **모드:** `burst` 1시간 → `visits_daily ÷ 24 × 18` ± 5σ, `medium`은 5.4배. 전환 `normal → burst → normal`에서 구간별 건수가 각 속도를 따른다
- **멈춤·재개:** `running=false` 동안 새 방문은 늘지 않지만 큐의 결제·전이는 계속 실행된다. `true`로 돌아오면 방문이 다시 는다
- **퍼널:** 담기가 있는 방문 비율 ≈ 0.997 × 15% (바로 주문 제외), 주문 비율 ≈ 4.49% (± 5σ), 바로 주문 ≈ 0.3%
- **조회 수:** 평균 4.8~5.2, 범위 1~20
- **주문 구성:** 줄 수 분포, 수량 분포가 표와 같다(± 5σ). 한 주문 안 `article_id` 중복 0. `total_amount` = Σ(`quantity` × `unit_price`) **전부 일치**. `unit_price`가 상품 목록의 가격과 같다
- **정합성 (한 번 돌린 결과 전체에 대해):** cart_add마다 같은 세션의 앞선 view가 있다 / 모든 주문의 `session_id`에 클릭 로그가 있다 / `payments`가 주문당 `attempt_no` 1..n으로 연속이고 3 이하 / 주문당 SUCCESS ≤ 1 / `PAID`·`SHIPPED`·`DELIVERED`·`REFUNDED`로 간 주문(배송 전 취소 포함)에는 SUCCESS가 정확히 1건 / `PAYMENT_FAILED`는 SUCCESS 0건·FAILED ≥ 1건 / 결제 전 취소 주문은 결제 0건 / `completed_at` ≥ `requested_at` / 주문별 `updated_at`이 전이마다 늘어난다 / `status_reason`은 `CANCELLED`·`REFUNDED`일 때만 있고 값이 맞다 / `amount` = `total_amount`
- **결제 확률 (순수 함수를 10만 번 이상 돌려):** 첫 시도 실패 8%(고객 7 / PG 1), 재시도 성공 70%, PG 바꿈 30%, 코드 분포, 수단-코드 규칙, 결제 단계 주문당 시도 ≈ 1.057, 시도 단위 실패율 ≈ 9.2%, 주문 단위 최종 실패 ≈ 4.0% (모두 ± 5σ). `pg_extra_fail={"PG_A": 0.5}`이면 PG_A 시도의 PG 원인 실패 확률이 기본값(첫 시도 1%, 재시도 3.75%)보다 0.5만큼 오르고 PG_B는 그대로다. 비어 있으면 기본과 같다
- **전이:** 결제 전 취소 1.5%, 배송 전 취소 3%, 반품 7%(± 5σ). 각 지연이 표의 범위 안(경계 포함)에 있다. 종결 상태 뒤에는 전이가 없다. 배송 완료까지가 결제 후 18~28시간이다
- **이어서 끝까지:** 방문을 멈추고 `drain()`하면 큐가 비고, 최종 상태 분포가 대략 결제 실패 4%, 취소 4.3%, 반품 6.4%, 배송 완료 유지 85% (± 허용 오차, 주문 수가 적으면 넓게)
- **상품 순위:** 구매 샘플에서 상위 1% 순위가 18.6%, 5% → 44.0%, 20% → 79.1% (± 5σ). 조회 샘플 중 구매 상위 1% 상품이 차지하는 비율이 약 6%(5~8%) — 두 순위가 다르다는 증거. 순위 순열이 시드가 같으면 같다
- **회원 풀:** 상위 20% 성향 회원이 방문의 약 60%(± 5σ). 같은 회원은 풀이 갱신돼도 같은 가중치. PII 컬럼을 읽지 않는다(`SELECT` 문자열에 `name`, `email`, `phone`, `birth_date`, `password_hash`가 없다)
- **재현성:** 같은 시드 + 같은 `run_salt` + 같은 가짜 시계 + 같은 제어 순서 → `MemoryOrderSink`와 `MemoryClickSink`의 기록이 완전히 같다. `run_salt`가 다르면 UUID가 겹치지 않는다
- **순서 독립성:** 방문 `k`의 계획은 앞선 방문과 무관하다 (`k`번째 방문만 따로 계획해도 같다)
- **제어 파일:** 정상 값 반영 / 파일 없음·깨짐·잘못된 값(`"surge"` 포함)은 마지막 상태 유지
- **재연결:** `OperationalError`를 흉내 내는 가짜 Sink → 실패한 항목이 큐 맨 앞으로 돌아가고 1, 2, 4…초 대기 후 재개되어 **항목이 빠지거나 두 번 반영되지 않는다.** `23505`는 반영 완료로 처리. 출력에 PII 없음
- **종료:** 종료 신호 흉내 → 요약 출력, 트레이스백 없음
- **원격 DB 거부:** `check_db_target` — `localhost` 통과, 원격 거부, 원격+허용 통과, 오류 메시지에 호스트·비밀번호 없음
- **모듈 경계:** `src/sim/behavior/` 아래 어떤 파일도 `sim.member`, `sim.controller`, `sim.cdc`, `sim.sink`를 import하지 않는다 (소스를 읽어 검사하는 테스트)
- **출력:** 진행·시작·종료 출력에 이름·이메일·전화 형식(`example.com`, `010-`)이 없다

**통합 테스트 (`@pytest.mark.integration`, 로컬 DB, 임시 스키마).** 기존 `test_live_integration.py`처럼 `localhost`가 아니면 건너뛰고, 임시 스키마에 `db/schema/*.sql`을 파일 이름 순으로 적용해 쓰고 지운다. `003`·`004`가 없으면 건너뛰고 알린다.
- 합성 회원 2,000명과 상품 1,000개를 SQL로 넣는다
- 가짜 시계로 시뮬레이터 1일(`visits_daily=3000`) 실행 후 `drain()` → DB 제약 위반 없이 끝나고 `DbOrderSink`가 쓴 건수 = `MemoryOrderSink`로 같은 설정을 돌린 건수
- 위 정합성 규칙을 **SQL로** 확인 (총액 일치, 주문마다 줄 ≥ 1, SUCCESS ≤ 1, PAID 이상은 SUCCESS 1건, `status_reason` 짝, 종결 상태 후 변화 없음)
- 연결을 끊었다 되살리는 시나리오: 실행 중 연결을 종료시켜도 반영 건수에 빠짐·중복이 없다

## 만들지 않는 것

- 모드 자동 복귀(medium 60분, burst 15분), 장애 주입 버튼, `incident_log`, 모드 전환 이력, 제어 신호 전달 수단(HTTP 등) (→ `controller`)
- `pg_extra_fail`을 **채우는** 쪽 (이 브랜치에서는 인자 자리만 있다)
- Kafka 발행, 클릭 로그의 중복·지각 노이즈 (→ `clickstream`)
- 주문 3개 테이블의 Debezium 커넥터와 S3 Sink (→ `cdc-orders`)
- 탈퇴, 가입 당일 첫 방문 유도, 조회 급상승, 날짜별 이벤트
- 백필(과거 데이터 일괄 생성), RDS에서 진행 중 주문을 읽어 큐를 복구하는 기능
- 쇼핑몰 API 호출용 Sink (`ApiOrderSink`), Dockerfile·`run-all` (→ ECS 이미지 브랜치)
- `db/schema/` 변경 (필요해 보이면 만들지 말고 이유를 설명한다), `infra/` 변경
- 리뷰 시뮬레이터(`review-simulator/`)와의 연결
- 설계 문서(`docs/design/*`) 수정
- 새 의존성

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. `docs/BRANCHES.md`에 `sim/behavior-core` 한 줄 추가(상태: 진행 중) + 이 지시서를 `docs/tasks/sim-behavior-core.md`로 추가 → 커밋 `docs(sim/behavior-core): 브랜치 등록과 작업 지시서 추가`
   `params.py`, `model.py`, `ranking.py` + 단위 테스트 → 커밋 `feat(sim/behavior-core): 파라미터와 상품 순위 추첨 추가`
3. `pool.py`, `visit.py` (순수 함수) + 단위 테스트 → 커밋 `feat(sim/behavior-core): 회원 풀과 방문 계획 추가`
4. `payment.py`, `queue.py` + 단위 테스트 → 커밋 `feat(sim/behavior-core): 결제 추첨과 예약 큐 추가`
5. `sink.py`, `common/db.py`의 `check_db_target` + 단위 테스트 → 커밋 `feat(sim/behavior-core): Sink 인터페이스와 원격 DB 스위치 추가`
6. `runner.py` (루프, 제어 신호, 재연결, 종료) + 단위 테스트 → 커밋 `feat(sim/behavior-core): 행동 실행기 추가`
7. `cli.py`, `sim/cli.py` 등록 + 출력 테스트 → 커밋 `feat(sim/behavior-core): behavior live 명령 추가`
8. 통합 테스트 → 커밋 `test(sim/behavior-core): 통합 테스트 추가`, 이어서 `simulator/README.md`·`simulator/CLAUDE.md` 갱신 → 커밋 `docs(sim/behavior-core): README와 CLAUDE.md 갱신`
9. "완료 확인"을 **실제로 실행**해서 결과 보고
10. 이 지시서 맨 아래 `작업 결과` 절을 채우고, 맨 위 상태를 `완료`로 바꾸고, `docs/BRANCHES.md`의 상태를 "머지됨"으로 바꾼다 → 커밋 `docs(sim/behavior-core): 작업 결과 기록`. 그다음 사용자 확인을 기다린다.

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다. 확인용으로 넣은 행은 마지막에 지운다.

- [ ] `ruff check .`, `ruff format --check .`, `pytest`(단위) 통과, `docker compose up -d` 후 `pytest -m integration` 통과
- [ ] 기존 baseline·live 재현성 테스트가 **그대로 통과**
- [ ] 로컬 DB 상태 확인: `SELECT count(*) FROM members;`(10만), `product_variant`, `orders`, `order_items`, `payments` 행 수. **세 거래 테이블이 비어 있을 때만** 아래를 진행한다 (비어 있지 않으면 멈추고 알린다). `product_variant`가 비어 있으면 합성 상품 2,000개와 `product_design` 1행을 임시로 넣고, 끝에 지운다
- [ ] **실행 (배속 1440, 하루 2만 방문, 클릭 파일):** `sim behavior live --visits-daily 20000 --speed 1440 --duration 60 --click-sink jsonl` → 정상 종료, 요약 출력. 방문 대비 주문 비율이 4.49% ± 5σ 안
- [ ] **모드:** 같은 조건에서 `--mode burst --speed 10 --visits-daily 20000 --duration 30` → 방문이 약 1,250건 (± 5σ), `--mode medium`은 약 375건. 실행 중 `echo '{"running": true, "mode": "normal"}' > simulator/.local/control.json`으로 바꾸면 `mode: burst → normal` 줄이 나온다. `{"mode": "surge"}`는 경고 한 번과 마지막 상태 유지
- [ ] **멈춤:** `{"running": false, "mode": "normal"}`으로 바꾸면 방문이 늘지 않지만 주문 상태 UPDATE 건수는 계속 늘고, `true`로 바꾸면 방문이 다시 는다
- [ ] **DB 정합성 (각 쿼리 결과가 0행/0이어야 한다):**
  - 총액 불일치: `SELECT o.order_id FROM orders o JOIN order_items i USING (order_id) GROUP BY o.order_id, o.total_amount HAVING sum(i.quantity * i.unit_price) <> o.total_amount;`
  - 줄 없는 주문: `SELECT order_id FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id);`
  - SUCCESS 두 건 이상: `SELECT order_id FROM payments WHERE status = 'SUCCESS' GROUP BY order_id HAVING count(*) > 1;`
  - PAID 이상인데 SUCCESS 없음: `status IN ('PAID','SHIPPED','DELIVERED','REFUNDED')`인 주문 중 SUCCESS 결제가 없는 것 (환불 주문 포함. 배송 전 취소(`CANCELLED`)는 결제 전 취소와 구분이 안 되므로 이 쿼리에서 뺀다)
  - `PAYMENT_FAILED`인데 SUCCESS가 있거나 FAILED가 없음
  - 시도 번호가 연속이 아님 / 3 초과
  - 결제 `amount` ≠ 주문 `total_amount`
  - 주문 `session_id`가 클릭 파일에 없음 (파이썬 한 줄로 비교. 스크립트는 커밋하지 않는다)
- [ ] **분포 확인 (보고만):** 상태별 주문 수, 결제 시도 수 / 결제 단계 주문 수(≈ 1.06), 시도 실패율(≈ 9%), 첫 시도 PG 비율, `failure_code` 분포. 하루만 돌려서 `PAID` 이후 전이가 남아 있으므로 최종 분포 비교는 단위 테스트(`drain`) 결과로 대신한다
- [ ] **껐다 켜기:** 실행 → `Ctrl+C` → 종료 코드 0과 요약 출력, 트레이스백 없음. 다시 실행해도 `orders_pkey`/`payments_pkey` 오류가 없다 (`run_salt`가 다르다). 첫 실행에서 멈춘 주문이 그 상태에 남아 있다는 것을 확인하고 보고한다 (이 브랜치의 알려진 한계)
- [ ] **PII가 출력에 없다:** 위 실행 출력을 파일로 저장해 `grep -E "example\.com|010-"` 결과가 없다. `SELECT`가 읽은 컬럼에 PII 컬럼이 없다(코드 확인)
- [ ] **ECS 전제 확인:** `DATABASE_URL`을 원격 호스트처럼 바꾸면 `SIM_ALLOW_REMOTE_DB` 없이 거부되고, 메시지에 호스트·비밀번호가 없다 (실제 접속은 하지 않는다)
- [ ] `docker build -t sim-local ./simulator` 성공, `docker run --rm sim-local behavior live --help`가 옵션 목록을 보여 준다
- [ ] 확인 후 **삭제:** `DELETE FROM payments; DELETE FROM order_items; DELETE FROM orders;` (시작 전에 비어 있었던 경우만). 삭제 건수를 보고하고 세 테이블이 0행인지 확인. 임시로 넣은 합성 상품도 지운다
- [ ] `git status`에 `.env`, `simulator/.local/`(제어 파일, 클릭 파일), 회원 값이 든 파일이 없다
- [ ] push, PR을 하지 않았다 (사용자 확인 대기)

## README 갱신

- `simulator/README.md`: `## 행동 (behavior)` 절 — 명령과 옵션 표, 흐름 한 단락(방문 → 주문 → 결제 → 전이), 값을 바꾸는 곳(`behavior/params.py`), Sink 두 개와 나중에 바꾸는 법, 제어 파일 쓰는 법(모드 3개, `running=false`는 새 방문만 멈춤), `run_salt`, **재시작하면 진행 중 주문이 멈춘다는 한계**, 원격 DB 스위치(`SIM_ALLOW_REMOTE_DB=1`)
- `simulator/CLAUDE.md`: 폴더 구조의 `behavior/` 설명을 "(나중에)"에서 "쇼핑 행동: 방문, 주문, 결제, 상태 전이"로 바꾼다 (이 한 줄만)

## 막히면

- 이 지시서의 내용끼리, 또는 설계 문서·기존 코드와 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일·명령·컬럼·테이블이 필요해 보이면 만들지 말고 먼저 이유를 설명한다.
- `sim/modes`, `db/order-schema`가 아직 머지되지 않아 import나 DDL이 없으면 만들지 말고 알린다.
- 기존 코드가 이 지시서의 가정과 다르면(예: `SimRandom`을 다시 심을 수 없는 구조) 고쳐서 맞추지 말고 먼저 알린다.

## 작업 결과

### 만든 것

- `simulator/src/sim/behavior/`: `params.py`(모든 수치, `[가정]` 표시), `model.py`(불변 데이터 클래스와 큐 항목), `ranking.py`(`ProductRanking`: 시드로 섞은 순열 + 구간 선형 누적표 역함수 추첨), `pool.py`(`MemberPool`: sha256 결정론적 성향, 누적 가중치 + `bisect`. `DbMemberSource`/`DbCatalogSource`는 `member_id`와 `article_id, price`만 읽는다), `visit.py`(`plan_visit` 순수 함수), `payment.py`(`choose_pg`, `decide_attempt(… pg_extra_fail)`, `should_retry`, `next_transition`), `queue.py`(`ScheduledQueue`), `sink.py`(`OrderSink`/`ClickSink`와 `DbOrderSink`, `MemoryOrderSink`, `NullClickSink`, `JsonlClickSink`, `MemoryClickSink`), `runner.py`(`BehaviorRunner`: 루프, 제어 신호, 재연결, 종료, 요약, `run_until`, `drain`), `cli.py`(`sim behavior live`)
- `common/db.py`: `check_db_target(database_url, allow_remote)`와 `DatabaseTargetError`. `sim/cli.py`에 `behavior` 등록
- 테스트: 단위 `test_behavior_{ranking,pool,visit,payment,queue,sink,runner,cli}.py`(+ `behavior_fixtures.py`, `conftest.py` 픽스처), 통합 `test_behavior_integration.py`
- 문서: `simulator/README.md`의 `## 행동 (behavior)` 절과 코드 구조 줄, `simulator/CLAUDE.md`의 `behavior/` 한 줄

### 지시서와 다르게 하거나 덧붙인 것

- `JsonlClickSink`는 줄마다 비우지 않고 기본 버퍼로 쓴다. WSL의 `/mnt/e`에서 줄마다 비우면 한 줄에 약 0.6ms라(기본 버퍼는 0.013ms) 피크 시간대 클릭 속도를 따라가지 못해 방문이 버려졌다. 버퍼는 `close()`에서 비운다.
- 커밋 직후 연결이 끊기면 그 항목을 다시 실행하면서 같은 `UPDATE`가 한 번 더 나간다. 같은 값을 다시 쓰는 것이라 DB 결과는 같다(INSERT는 `23505`로 건너뛴다). 단위 테스트는 이 경우 연속된 같은 UPDATE를 하나로 보고 비교한다.
- 방문 중 연결이 끊기면 대기한 시간만큼 "밀린 방문은 따라잡지 않는다" 규칙이 적용돼 이후 방문 시각이 달라진다. 그래서 끊김 테스트는 (1) `drain` 중 끊김은 깨끗한 실행과 호출 기록이 같은지, (2) 방문 중 끊김은 정합성·빠짐 없음(모두 종결 상태로 끝남)을 확인한다.
- `tests/test_product_integration.py`의 `DROP TABLE product_variant, product_design`에 `CASCADE`를 붙였다. `004_orders.sql`의 `order_items`가 `product_variant`를 참조하게 되면서 이 기존 테스트가 실패했다(임시 스키마 안에서만 지운다).
- 로컬 DB(public)에 `db/schema/004_orders.sql`을 적용했다(사용자 승인). 테이블은 남겨 두고 행만 지웠다.
- `simulator/CLAUDE.md` 18행의 "`behavior`(쇼핑 행동, 나중에)"는 지시서가 한 줄만 바꾸라고 해서 그대로 두었다.

### 완료 확인 실행 결과 (2026-10-18, 로컬)

| 확인 | 결과 |
|---|---|
| `ruff check .`, `ruff format --check .` | 통과 |
| `pytest` (단위) | 280 passed (기존 baseline·live 재현성 테스트 포함) |
| `pytest -m integration` | 16 passed (행동 3개 포함) |
| 시작 전 DB | `members` 103,690 (베이스라인 10만 + 사용자가 돌린 신규 가입 3,690), `product_variant` 101,452, 거래 테이블은 없어서 004 적용 후 0행 |
| `--visits-daily 20000 --speed 1440 --duration 60 --click-sink jsonl` | 종료 코드 0, 방문 17,145, 주문 759 → **주문 비율 4.43%** (기준 4.49% ± 0.79%). 방문은 기대 약 17,850의 96%로, 10초 구간 하나에서 루프가 1초 넘게 밀려 약 970건이 따라잡기 규칙으로 버려졌다(같은 조건 12초 측정 두 번은 기대값대로 나옴) |
| DB 정합성 8개 (총액, 줄 없는 주문, SUCCESS 2건+, PAID 이상 SUCCESS 없음, PAYMENT_FAILED 짝, 시도 번호, 결제 금액, 클릭 파일에 없는 주문 세션) | 모두 0 |
| 분포 (위 실행) | 상태: SHIPPED 508, PAID 127, DELIVERED 57, CANCELLED 38, PAYMENT_FAILED 29 / 결제 단계 주문당 시도 1.046 / 시도 실패율 8.1% / 첫 시도 PG_A 51.8%·PG_B 48.2% / 수단 CARD 55.9%·SIMPLE_PAY 33.9%·BANK_TRANSFER 10.1% / 실패 코드 INSUFFICIENT_BALANCE 25, CARD_LIMIT_EXCEEDED 20, CARD_DECLINED 12, PG_ERROR 4, PG_TIMEOUT 2 |
| `--mode burst --speed 10 --visits-daily 20000 --duration 30` | 1,180건 (기대 1,250 ± 177) |
| `--mode medium` 같은 조건 | 381건 (기대 375 ± 97) |
| 실행 중 제어 파일 `normal` | `mode: burst → normal` 출력 |
| `{"mode": "surge"}` | 경고 한 번, 다시 써도 추가 경고 없이 normal 유지 |
| 멈춤 `running=false` | 멈춘 10초 구간 방문 0, 그동안 DB의 배송 이후 상태 주문 600 → 776 증가, 다시 켜자 방문 재개 |
| 껐다 켜기 (시작 완료 뒤 SIGINT) | 종료 코드 0, 요약 출력, 트레이스백 없음. 다시 실행해도 `pkey` 오류 없음(`run_salt` 1792310756 → 1792310797). 끊긴 실행의 주문이 `PLACED` 5, `PAID` 707, `SHIPPED` 825 등으로 남음 (알려진 한계) |
| 출력 PII | 모든 실행 출력에 `example.com`, `010-` 없음. `SELECT`는 `member_id`와 `article_id, price`만 읽는다 |
| 원격 DB | `SIM_ALLOW_REMOTE_DB` 없이 종료 코드 1, 메시지에 호스트·비밀번호 없음 (실제 접속 안 함) |
| `docker build -t sim-local ./simulator` / `docker run --rm sim-local behavior live --help` | 성공 / 옵션 목록 출력 |
| 삭제 | 확인 중 세 번 지움: `payments` 794 + 1,247 + 1,775 = 3,816, `order_items` 2,583 + 4,151 + 5,990 = 12,724, `orders` 750 + 1,207 + 1,737 = 3,694. 끝에 세 테이블 0행. 합성 상품은 넣지 않았다 |
| `git status` | `.env`, `simulator/.local/`은 무시됨. push, PR을 하지 않았다 |

### 알려진 한계

- **재시작하면 진행 중이던 주문이 멈춘다.** 예약 큐가 메모리에만 있고 DB에서 복구하지 않는다.
- 이 WSL 환경에서는 `/mnt/e`의 모듈을 읽느라 시작(import)에 약 20초가 걸린다. 이 사이에 `Ctrl+C`를 누르면 신호 처리기가 설치되기 전이라 Python 기본 `KeyboardInterrupt` 트레이스백이 나온다(종료 코드 130). 시작이 끝난 뒤에는 정상 처리된다. 컨테이너에서는 import가 빨라 해당하지 않는다.
- 루프가 실제 시간 1초 넘게 밀리면 그만큼의 방문은 만들지 않는다(지시서 규칙). 로컬에서는 디스크 지연으로 가끔 생긴다.

### 다음 할 일

- `sim/controller`: 모드 자동 복귀, 장애 주입(`pg_extra_fail` 채우기), `incident_log`, 제어 신호 전달 수단
- `sim/ecs-image`: RDS TLS·전용 계정, 이미지·실행
- `sim/clickstream`(클릭 Kafka 발행), `sim/cdc-orders`(주문 3개 테이블 CDC)