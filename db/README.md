# db/

시뮬레이터가 쓰는 PostgreSQL(RDS)의 스키마 DDL을 둔다. 회원 설계 문서(`docs/design/member.md`)는 따로 추가될 예정이며, 현재 DDL은 `docs/tasks/sim-skeleton.md`의 표를 기준으로 한다.

## 파일 순서

| 파일 | 내용 |
|---|---|
| `schema/001_member.sql` | `member` 테이블 |
| `schema/002_member_archive.sql` | `member_archive` 테이블 (`member` 참조) |
| `schema/003_review.sql` | `reviews` 테이블 (리뷰 시뮬레이터가 씀) |

파일 이름 순서대로 적용한다. 주문 테이블, 복제 슬롯·publication·Debezium 계정, 인덱스는 이후 브랜치에서 추가한다.

## `member`

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `member_id` | `uuid` | PK |
| `name` | `text` | NULL 허용 |
| `email` | `text` | NULL 허용, UNIQUE |
| `phone` | `text` | NULL 허용, UNIQUE |
| `birth_date` | `date` | NULL 허용 |
| `gender` | `text` | NOT NULL, `'F'` 또는 `'M'` |
| `signup_at` | `timestamptz` | NOT NULL |
| `signup_channel` | `text` | NOT NULL, `'web'` 또는 `'app'` |
| `marketing_consent` | `boolean` | NOT NULL |
| `status` | `text` | NOT NULL, `'ACTIVE'` 또는 `'WITHDRAWN'` |
| `withdrawn_at` | `timestamptz` | NULL 허용 |
| `created_at` | `timestamptz` | NOT NULL, `DEFAULT now()` |
| `password_hash` | `text` | NULL 허용 |
| `region_sigungu` | `text` | NOT NULL |
| `age_band` | `text` | NOT NULL, `'~19'`, `'20s'`, `'30s'`, `'40s'`, `'50s'`, `'60s'`, `'70+'` 중 하나 |

테이블 CHECK:
- `status = 'ACTIVE'`이면 `withdrawn_at IS NULL`, `status = 'WITHDRAWN'`이면 `withdrawn_at IS NOT NULL`
- `withdrawn_at`이 있으면 `withdrawn_at >= signup_at`

탈퇴하면 `name`, `email`, `phone`, `birth_date`, `password_hash`가 NULL이 되므로 이 컬럼들은 NULL을 허용한다. PostgreSQL의 UNIQUE는 NULL 여러 개를 허용한다.

## `member_archive`

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `member_id` | `uuid` | PK, `member(member_id)` 참조 |
| `name` | `text` | NOT NULL |
| `email` | `text` | NOT NULL |
| `phone` | `text` | NOT NULL |
| `archived_at` | `timestamptz` | NOT NULL, `DEFAULT now()` |

## `reviews`

리뷰 시뮬레이터(`review-simulator/`)가 주문 기반 실행(`rsim run --source orders --sink postgres`)으로 쓴다.
정답 라벨(속성·감성)은 넣지 않는다. `[임시]` 칸은 주문·상품 테이블이 생기면 참조로 바꾼다.

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `review_id` | `text` | PK |
| `order_id` | `text` | NULL 허용, UNIQUE (주문 하나에 리뷰 하나) [임시: 이후 `orders` 참조] |
| `member_id` | `text` | NOT NULL [임시: 시뮬레이터 값, `member.member_id`(uuid)와 아직 연결 안 함] |
| `product_id` | `text` | NOT NULL [임시] |
| `product_name` | `text` | NOT NULL [임시] |
| `category` | `text` | NOT NULL [임시] |
| `age_group` | `text` | NULL 허용 [임시] |
| `rating` | `smallint` | NOT NULL, 1~5 |
| `body` | `text` | NOT NULL (리뷰 본문) |
| `source` | `text` | NOT NULL (`simulator`) |
| `written_at` | `timestamptz` | NOT NULL (리뷰 작성 시각 = 결제 + 1~14일) |
| `created_at` | `timestamptz` | NOT NULL, `DEFAULT now()` |

## 로컬에서 적용

`simulator/docker-compose.yml`이 `db/schema/`를 `/docker-entrypoint-initdb.d`에 마운트하므로, **빈 볼륨으로 처음 시작할 때** DDL이 자동 적용된다.

```bash
cd simulator
docker compose up -d
docker compose exec postgres psql -U sim -d clothes -c '\d member'
```

이미 볼륨이 있어 새 DDL만 넣으려면 그 파일만 적용한다: `docker compose exec -T postgres psql -U sim -d clothes < ../db/schema/003_review.sql`

DDL을 고쳐 다시 적용하려면 볼륨을 지우고 다시 띄운다: `docker compose down -v && docker compose up -d`
